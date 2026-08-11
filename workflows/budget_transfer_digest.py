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
SLACK_CHANNEL  = "U07628FGAN9"  # Asin Zahir DM — change to channel ID when going live
GOOGLE_CREDS   = os.environ["GOOGLE_CREDENTIALS"]

# Known Slack user IDs
SLACK_IDS = {
    "Rachel La":        "U06D4UX21U7",
    "Asin Zahir":       "U07628FGAN9",
    "Arslan Farooq":    "U074S9XEE6L",
    "Asher Oosterbaan": "U072E5U4P6V",
}

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
COL_TO_OU         = 9
COL_TO_BUCKET     = 10
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
        if not to_bl or from_bl == to_bl:
            excluded.append(f"{unique_id} — FROM BL = TO BL (no-op, excluded)")
            continue
        comment = safe(row, COL_COMMENTS_AD)
        if is_blocking_comment(comment):
            excluded.append(f"{unique_id} — blocking comment: \"{comment}\"")
            continue

        sign_q = safe(row, COL_SIGN_OFF_Q)
        sign_r = safe(row, COL_SIGN_OFF_R)

        if transfer_type == "internal":
            has_signoff = bool(sign_q and sign_r)
            missing = []
            if not sign_q: missing.append("Col Q")
            if not sign_r: missing.append("Col R")
        else:
            has_signoff = bool(sign_r)
            missing = [] if sign_r else ["Col R"]

        entry = {
            "id":        unique_id,
            "to_ou":     safe(row, COL_TO_OU),
            "to_bucket": safe(row, COL_TO_BUCKET),
            "amount":    safe(row, COL_USD_AMOUNT),
            "owner":     safe(row, COL_MF_OWNER),
            "missing":   missing,
            "tab":       transfer_type,
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
    header = f"{'Unique ID':<{col1}}  {'TO OU / Bucket':<{col2}}  Amount"
    divider_line = "-" * (col1 + col2 + 20)
    lines = [header, divider_line]
    for r in rows:
        bucket = f"{r['to_ou']} / {r['to_bucket']}"
        lines.append(f"{r['id']:<{col1}}  {bucket:<{col2}}  {format_amount(r['amount'])}")
    return "```" + "\n".join(lines) + "```"

def awaiting_rows(rows):
    col1 = max(len(r['id']) for r in rows)
    col2 = max(len(format_amount(r['amount'])) for r in rows)
    header = f"{'Unique ID':<{col1}}  {'Amount':<{col2}}  Missing"
    divider_line = "-" * (col1 + col2 + 20)
    lines = [header, divider_line]
    for r in rows:
        lines.append(f"{r['id']:<{col1}}  {format_amount(r['amount']):<{col2}}  {', '.join(r['missing'])}")
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

    blocks.append(section(
        f":calendar: *Budget Transfer Submission Reminder — {today}*\n"
        f"_TEST RUN — sent to DM only for review before going live_"
    ))
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
        blocks.append(section(":hourglass_flowing_sand: *Awaiting Sign-Off* _(not yet actionable)_"))
        if awaiting_internal:
            blocks.append(section("*Internal Transfers*"))
            blocks.append(section(awaiting_rows(awaiting_internal)))
        if awaiting_external:
            blocks.append(section("*External Transfers*"))
            blocks.append(section(awaiting_rows(awaiting_external)))

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
