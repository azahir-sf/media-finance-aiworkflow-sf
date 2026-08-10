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

# Set to True to send to your DM for review, False to send to the team channel
TEST_MODE     = True
SLACK_CHANNEL = os.environ["SLACK_CHANNEL_DM"] if TEST_MODE else os.environ["SLACK_CHANNEL_ID"]

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

def is_blocking_comment(comment):
    c = comment.lower()
    return "same bl" in c or "no action" in c

def filter_rows(rows, transfer_type):
    data_rows = rows[6:]
    actionable, awaiting = [], []

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
            continue
        if safe(row, COL_FROM_BL_CODE) == safe(row, COL_TO_BL_CODE):
            continue
        if is_blocking_comment(safe(row, COL_COMMENTS_AD)):
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
        }

        if has_signoff:
            actionable.append(entry)
        else:
            awaiting.append(entry)

    return actionable, awaiting

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

# ── Message builder ───────────────────────────────────────────────────────────

def build_message(actionable, awaiting, quarter):
    today = date.today().strftime("%A, %d %B %Y")
    lines = [
        f":calendar: *Budget Transfer Submission Reminder — {today}*",
        f"Hi team! The following {quarter} transfers are pending BudgetForce submission. Please submit your TRX today :white_check_mark:",
        ""
    ]

    by_owner = {}
    for row in actionable:
        by_owner.setdefault(row["owner"] or "Unassigned", []).append(row)

    grand_total = 0.0

    for owner, rows in sorted(by_owner.items()):
        lines.append(f"*{mention(owner)}*")
        lines.append("| Unique ID | TO OU / Bucket | Amount |")
        lines.append("|---|---|---|")
        subtotal = sum(to_float(r["amount"]) for r in rows)
        grand_total += subtotal
        for r in rows:
            lines.append(f"| {r['id']} | {r['to_ou']} / {r['to_bucket']} | {format_amount(r['amount'])} |")
        lines.append(f"*Subtotal: ${subtotal:,.2f}* _({len(rows)} transfer{'s' if len(rows) > 1 else ''})_")
        lines.append("")

    lines.append(f":moneybag: *Grand Total: ${grand_total:,.2f}* across {len(actionable)} transfer{'s' if len(actionable) != 1 else ''}")
    lines.append("")

    if awaiting:
        lines.append(":hourglass_flowing_sand: *Awaiting Sign-Off* _(missing ML Strat sign-off)_")
        lines.append("| Unique ID | MF Owner | TO OU / Bucket | Amount | Missing |")
        lines.append("|---|---|---|---|---|")
        for r in awaiting:
            lines.append(f"| {r['id']} | {mention(r['owner'])} | {r['to_ou']} / {r['to_bucket']} | {format_amount(r['amount'])} | {', '.join(r['missing'])} |")
        lines.append("")

    lines.append("_Please reply in thread or update the tracker once submitted. Thanks!_ :pray:")
    return "\n".join(lines)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    quarter = current_quarter()
    print(f"Running digest for {quarter}...")

    service = get_sheets_service()
    internal_rows = read_tab(service, f"FY27{quarter} Internal Transfers")
    external_rows = read_tab(service, f"FY27{quarter} External Transfers")

    int_action, int_await = filter_rows(internal_rows, "internal")
    ext_action, ext_await = filter_rows(external_rows, "external")

    actionable = int_action + ext_action
    awaiting   = int_await  + ext_await

    print(f"Actionable: {len(actionable)} | Awaiting: {len(awaiting)}")

    if not actionable and not awaiting:
        message = f":white_check_mark: *Budget Transfer Digest — {date.today().strftime('%A, %d %B %Y')}*\nNo pending transfers to action for {quarter}. All clear!"
    else:
        message = build_message(actionable, awaiting, quarter)

    client = WebClient(token=SLACK_TOKEN)
    try:
        client.chat_postMessage(channel=SLACK_CHANNEL, text=message, mrkdwn=True)
        print(f"Message sent to {SLACK_CHANNEL}.")
    except SlackApiError as e:
        print(f"Slack error: {e.response['error']}")
        raise SystemExit(1)

if __name__ == "__main__":
    main()
