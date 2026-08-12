"""
Budget Transfer Digest
Reads FY27 Paid Media Budget Transfer Google Sheet, filters pending transfers,
and posts a grouped digest to Slack via bot token.
"""

import os
import json
from datetime import date
from google.oauth2 import service_account
from googleapiclient.discovery import build
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# ── Config ────────────────────────────────────────────────────────────────────

SPREADSHEET_ID = "1zr_aKPzHIlYhbO4V7DUR24CsQC1ICsBeMWB6dIikI1A"
SLACK_TOKEN    = os.environ["SLACK_BOT_TOKEN"]
GOOGLE_CREDS   = os.environ["GOOGLE_CREDENTIALS"]

WORKFLOW_MODE  = os.environ.get("WORKFLOW_MODE", "test").strip().lower()

# Known Slack user IDs — MF team
SLACK_IDS = {
    "Rachel La":        "U06D4UX21U7",
    "Asin Zahir":       "U07628FGAN9",
    "Arslan Farooq":    "U074S9XEE6L",
    "Asher Oosterbaan": "U072E5U4P6V",
    "Andrea Li":        "D075ZC50RP1",
    # ML Strategists — mapping needed, add names + Slack IDs here
    # "First Last": "UXXXXXXXX",
}

# SEND_TO: real Slack channel/user ID, or "CHANNEL" to use the SLACK_CHANNEL_ID secret
SEND_TO = os.environ.get("SEND_TO", "U07628FGAN9").strip()
if SEND_TO == "CHANNEL":
    SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL_ID", "U07628FGAN9")
else:
    SLACK_CHANNEL = SEND_TO or "U07628FGAN9"

# ── Quarter logic ─────────────────────────────────────────────────────────────

def current_quarter():
    month = date.today().month
    if month in (2, 3, 4):  return "Q1"
    if month in (5, 6, 7):  return "Q2"
    if month in (8, 9, 10): return "Q3"
    return "Q4"

# ── Google Sheets ─────────────────────────────────────────────────────────────

def get_sheets_service():
    creds_dict = json.loads(GOOGLE_CREDS)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    return build("sheets", "v4", credentials=creds)

def read_tab(service, tab_name):
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{tab_name}'!A1:AE200"
    ).execute()
    return result.get("values", [])

# ── Filtering ─────────────────────────────────────────────────────────────────

COL_UNIQUE_ID     = 0
COL_FROM_BL_CODE  = 2
COL_FROM_BL_NAME  = 3
COL_FROM_REGION   = 4
COL_FROM_OU       = 5
COL_FROM_BUCKET   = 6
COL_FROM_CAMPAIGN = 7
COL_TO_REGION     = 8
COL_TO_OU         = 9
COL_TO_BUCKET     = 10
COL_TO_CAMPAIGN   = 11
COL_USD_AMOUNT    = 14
COL_SIGN_OFF_Q    = 16
COL_SIGN_OFF_R    = 17
COL_MF_OWNER      = 18
COL_TO_BL_CODE    = 23
COL_TRX_SUBMITTED = 24
COL_COMMENTS_AD   = 29

def safe(row, idx):
    try: return str(row[idx]).strip()
    except IndexError: return ""

BLOCKING_KEYWORDS = ["no action needed", "not needed", "cancelled", "on hold", "skip", "n/a", "same bl", "no action"]

# ── ML Strategist mapping ─────────────────────────────────────────────────────

_CLOUD_PRIORITIES = {
    "Commerce": "Mandy Sheldon", "Sales": "Mandy Sheldon",
    "Marketing": "Steven Piccione", "Service": "Steven Piccione",
    "Platform": "Michelle Thatcher", "Analytics": "Gwen Baer",
    "Data": "Broden Chapman", "AI": "Janelle Triana",
}
_CORE_CLOUD_SEARCH = {
    "AI": "Michael Quinoy", "Integration": "Michael Quinoy",
    "GPS": "Maxwell Trotter", "Data": "Maxwell Trotter",
    "Sales": "Aviva Isakov", "Marketing": "Aviva Isakov",
    "HLS": "Andrew Howe", "FINS": "Andrew Howe", "MAE": "Andrew Howe",
    "RCG": "Andrew Howe", "CMT": "Andrew Howe",
    "SMB": "Christian Morneweck", "Commerce": "Emily Nguyen",
    "Platform": "Dan Idesis", "Service": "Sarah Nolan",
}
_FIELD_GLOBAL = {
    "SMB": "Justin Myong", "Integration": "Marion Gardoce", "GPS": "Vikram Kakaria",
}
_FIELD_AMER = {
    "AMER PACE & AFD360": {"RCG": "Zee Khetani", "MAE": "Zee Khetani"},
    "AMER REG":           {"HLS": "Kait Callahan", "FINS": "Kait Callahan"},
    "AMER TMT":           {"CMT": "Victoria Mioduszewski"},
    "AMER CBS":           {"CBS": "Victoria Mioduszewski"},
}
_FIELD_EMEA = {
    "EMEA Central": "Luke Holland", "EMEA North": "Mary Cole",
    "EMEA South": "Giulia Duminuco", "France": "Alida Dubner", "UKI": "Veronica Gota",
}
_FIELD_APAC = {
    "ANZ": "Scarlett Shing", "ASEAN": "Ayush Chaddha",
    "INDIA": "Ayush Chaddha", "South Asia": "Ayush Chaddha",
}

def lookup_strategist(region, ou, bucket, campaign):
    if bucket == "Cloud Priorities":
        return _CLOUD_PRIORITIES.get(campaign)
    if bucket == "Core Cloud Search":
        return _CORE_CLOUD_SEARCH.get(campaign)
    if bucket == "Field Priorities":
        if ou in _FIELD_EMEA:
            return _FIELD_EMEA[ou]
        if ou in _FIELD_APAC:
            return _FIELD_APAC[ou]
        if ou == "LATAM":
            return "Henrique Sá"
        if ou in _FIELD_AMER:
            return _FIELD_AMER[ou].get(campaign)
        return _FIELD_GLOBAL.get(campaign)
    return None

def is_blocking_comment(comment):
    c = comment.lower()
    return any(k in c for k in BLOCKING_KEYWORDS)

def filter_rows(rows, transfer_type):
    data_rows = rows[6:]
    actionable, awaiting, excluded = [], [], []

    for row in data_rows:
        unique_id = safe(row, COL_UNIQUE_ID)
        if not unique_id:
            continue
        if safe(row, COL_TRX_SUBMITTED).upper() != "FALSE":
            continue
        if not all([
            safe(row, COL_FROM_BL_CODE),
            safe(row, COL_FROM_BL_NAME),
            safe(row, COL_TO_OU),
            safe(row, COL_TO_BUCKET),
            safe(row, COL_USD_AMOUNT),
        ]):
            excluded.append(f"{unique_id} — incomplete row (missing required fields)")
            continue
        from_bl = safe(row, COL_FROM_BL_CODE)
        to_bl   = safe(row, COL_TO_BL_CODE)
        if transfer_type == "internal" and to_bl and from_bl == to_bl:
            excluded.append(f"{unique_id} — FROM BL = TO BL (no-op, excluded)")
            continue
        comment = safe(row, COL_COMMENTS_AD)
        if is_blocking_comment(comment):
            excluded.append(f"{unique_id} — blocking comment: \"{comment}\"")
            continue

        sign_q_raw = safe(row, COL_SIGN_OFF_Q)
        sign_r_raw = safe(row, COL_SIGN_OFF_R)

        # Sign-off status based on actual sheet values only
        if transfer_type == "internal":
            has_signoff = bool(sign_q_raw and sign_r_raw)
            missing = []
            if not sign_q_raw: missing.append("Col Q")
            if not sign_r_raw: missing.append("Col R")
        else:
            has_signoff = bool(sign_r_raw)
            missing = [] if sign_r_raw else ["Col R"]

        # Display name: use sheet value if present, else look up expected strategist
        from_region   = safe(row, COL_FROM_REGION)
        from_ou       = safe(row, COL_FROM_OU)
        from_bucket   = safe(row, COL_FROM_BUCKET)
        from_campaign = safe(row, COL_FROM_CAMPAIGN)
        to_region     = safe(row, COL_TO_REGION)
        to_ou_val     = safe(row, COL_TO_OU)
        to_bucket_val = safe(row, COL_TO_BUCKET)
        to_campaign   = safe(row, COL_TO_CAMPAIGN)

        sign_q_display = sign_q_raw or lookup_strategist(from_region, from_ou, from_bucket, from_campaign) or "—"
        sign_r_display = sign_r_raw or lookup_strategist(to_region, to_ou_val, to_bucket_val, to_campaign) or "—"

        entry = {
            "id":         unique_id,
            "from_ou":    from_ou,
            "from_bucket": from_bucket,
            "to_ou":      to_ou_val,
            "to_bucket":  to_bucket_val,
            "amount":     safe(row, COL_USD_AMOUNT),
            "owner":      safe(row, COL_MF_OWNER),
            "missing":    missing,
            "tab":        transfer_type,
            "sign_q":     sign_q_display,
            "sign_r":     sign_r_display,
        }

        if has_signoff:
            actionable.append(entry)
        else:
            awaiting.append(entry)

    return actionable, awaiting, excluded

# ── Helpers ───────────────────────────────────────────────────────────────────

def mention(name):
    uid = SLACK_IDS.get(name)
    return f"<@{uid}>" if uid else f"*{name}*"

def format_amount(raw):
    raw = raw.replace("$", "").replace(",", "").strip()
    try: return f"${float(raw):,.2f}"
    except ValueError: return raw

def to_float(raw):
    try: return float(raw.replace("$", "").replace(",", "").strip())
    except ValueError: return 0.0

# ── Block Kit builder ─────────────────────────────────────────────────────────

def section(text):
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}

def divider():
    return {"type": "divider"}

def table_rows(rows):
    col1 = max(len(r['id']) for r in rows)
    col2 = max(len(f"{r['to_ou']} / {r['to_bucket']}") for r in rows)
    col2 = max(col2, len("TO OU / Bucket"))
    from_vals = [f"{r['from_ou']} / {r['from_bucket']}" if r['tab'] == "internal" else "N/A" for r in rows]
    col3 = max(max(len(v) for v in from_vals), len("FROM OU / Bucket"))
    header = f"{'Unique ID':<{col1}}  {'TO OU / Bucket':<{col2}}  {'FROM OU / Bucket':<{col3}}  Amount"
    divider_line = "-" * (col1 + col2 + col3 + 24)
    lines = [header, divider_line]
    for r, from_val in zip(rows, from_vals):
        to_b = f"{r['to_ou']} / {r['to_bucket']}"
        lines.append(f"{r['id']:<{col1}}  {to_b:<{col2}}  {from_val:<{col3}}  {format_amount(r['amount'])}")
    return "```" + "\n".join(lines) + "```"

def awaiting_rows(rows, transfer_type):
    col1 = max(len(r['id']) for r in rows)
    col2 = max(len(format_amount(r['amount'])) for r in rows)
    col3 = max((len(', '.join(r['missing'])) for r in rows), default=0)
    col3 = max(col3, len("Missing"))

    if transfer_type == "internal":
        col4 = max(max(len(r['sign_q']) for r in rows), len("Sign-Off Needed (FROM)"))
        col5 = max(max(len(r['sign_r']) for r in rows), len("Sign-Off Needed (TO)"))
        header = f"{'Unique ID':<{col1}}  {'Amount':<{col2}}  {'Missing':<{col3}}  {'Sign-Off Needed (FROM)':<{col4}}  {'Sign-Off Needed (TO)':<{col5}}"
        divider_line = "-" * (col1 + col2 + col3 + col4 + col5 + 16)
        lines = [header, divider_line]
        for r in rows:
            lines.append(f"{r['id']:<{col1}}  {format_amount(r['amount']):<{col2}}  {', '.join(r['missing']):<{col3}}  {r['sign_q']:<{col4}}  {r['sign_r']:<{col5}}")
    else:
        col4 = max(max(len(r['sign_r']) for r in rows), len("Sign-Off Needed"))
        header = f"{'Unique ID':<{col1}}  {'Amount':<{col2}}  {'Missing':<{col3}}  {'Sign-Off Needed':<{col4}}"
        divider_line = "-" * (col1 + col2 + col3 + col4 + 12)
        lines = [header, divider_line]
        for r in rows:
            lines.append(f"{r['id']:<{col1}}  {format_amount(r['amount']):<{col2}}  {', '.join(r['missing']):<{col3}}  {r['sign_r']:<{col4}}")

    return "```" + "\n".join(lines) + "```"

def build_blocks(actionable, awaiting, excluded, quarter):
    today = date.today().strftime("%A, %d %B %Y")
    blocks = []

    if not actionable:
        blocks.append(section(":white_check_mark: *No actionable transfers today — all caught up!*"))
        if excluded:
            excl_text = "\n".join(f"• {e}" for e in excluded)
            blocks.append(section(f"*Excluded rows:*\n{excl_text}"))
        return blocks

    mode_label = "" if SLACK_CHANNEL.startswith("C") else f"_Sent to DM only — not posted to team channel_"
    header_text = f":calendar: *Budget Transfer Submission Reminder — {today}*"
    if mode_label:
        header_text += f"\n{mode_label}"
    blocks.append(section(header_text))
    blocks.append(section(
        f"Hi team! The following {quarter} transfers are pending BudgetForce submission. "
        f"Please submit your TRX today :white_check_mark:"
    ))
    blocks.append(divider())

    by_owner = {}
    for row in actionable:
        by_owner.setdefault(row["owner"] or "Unassigned", []).append(row)

    grand_total = 0.0

    for owner, rows in sorted(by_owner.items()):
        subtotal = sum(to_float(r["amount"]) for r in rows)
        grand_total += subtotal
        blocks.append(section(f"*{mention(owner)}*"))
        blocks.append(section(table_rows(rows)))
        blocks.append(section(
            f"*Subtotal: ${subtotal:,.2f}* _({len(rows)} transfer{'s' if len(rows) > 1 else ''})_"
        ))
        blocks.append(divider())

    blocks.append(section(
        f":moneybag: *Total pending: ${grand_total:,.2f}* across "
        f"{len(actionable)} transfer{'s' if len(actionable) != 1 else ''}"
    ))

    awaiting_internal = [r for r in awaiting if r["tab"] == "internal"]
    awaiting_external = [r for r in awaiting if r["tab"] == "external"]

    if awaiting_internal or awaiting_external:
        blocks.append(divider())
        blocks.append(section(":hourglass_flowing_sand: *Awaiting Sign-Off* _(not yet actionable — ML Strategist sign-off required before Media Finance can submit)_"))
        if awaiting_internal:
            blocks.append(section("*Internal Transfers*"))
            blocks.append(section(awaiting_rows(awaiting_internal, "internal")))
        if awaiting_external:
            blocks.append(section("*External Transfers*"))
            blocks.append(section(awaiting_rows(awaiting_external, "external")))
        blocks.append(section("_:memo: Note: some ML Strategist names above are not yet mapped to Slack IDs — tags will appear as plain text until the mapping is provided._"))

    blocks.append(divider())
    blocks.append(section("_Please reply in thread or update the tracker once submitted. Thanks!_ :pray:"))

    return blocks

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    quarter = current_quarter()
    print(f"Running digest for {quarter}...")

    service = get_sheets_service()
    internal_rows = read_tab(service, f"FY27{quarter} Internal Transfers")
    external_rows = read_tab(service, f"FY27{quarter} External Transfers")

    int_action, int_await, int_excl = filter_rows(internal_rows, "internal")
    ext_action, ext_await, ext_excl = filter_rows(external_rows, "external")

    actionable = int_action + ext_action
    awaiting   = int_await  + ext_await
    excluded   = int_excl   + ext_excl

    print(f"Actionable: {len(actionable)} | Awaiting: {len(awaiting)} | Excluded: {len(excluded)}")

    client = WebClient(token=SLACK_TOKEN)
    try:
        blocks = build_blocks(actionable, awaiting, excluded, quarter)
        client.chat_postMessage(
            channel=SLACK_CHANNEL,
            text=f"Budget Transfer Digest — {quarter}",
            blocks=blocks
        )
        print(f"Message sent to {SLACK_CHANNEL}.")
    except SlackApiError as e:
        print(f"Slack error: {e.response['error']}")
        raise SystemExit(1)

if __name__ == "__main__":
    main()
