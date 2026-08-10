"""
Budget Transfer Digest
Reads FY27 Paid Media Budget Transfer Google Sheet, filters pending transfers,
and posts a grouped digest to Slack.
"""

import os
import sys
from datetime import date
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# ── Config ────────────────────────────────────────────────────────────────────

SPREADSHEET_ID = "1zr_aKPzHIlYhbO4V7DUR24CsQC1ICsBeMWB6dIikI1A"
SLACK_CHANNEL  = os.environ["SLACK_CHANNEL_ID"]   # set in GitHub secrets
SLACK_TOKEN    = os.environ["SLACK_BOT_TOKEN"]     # set in GitHub secrets
GOOGLE_CREDS   = os.environ["GOOGLE_CREDENTIALS"]  # JSON string in GitHub secrets

# ── Quarter logic ─────────────────────────────────────────────────────────────

def current_quarter():
    month = date.today().month
    if month in (2, 3, 4):   return "Q1"
    if month in (5, 6, 7):   return "Q2"
    if month in (8, 9, 10):  return "Q3"
    return "Q4"

# ── Google Sheets ─────────────────────────────────────────────────────────────

def get_sheets_service():
    import json, tempfile
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

# Column indices (0-based, row 6 = headers)
COL_UNIQUE_ID     = 0
COL_FROM_BL_CODE  = 2
COL_FROM_BL_NAME  = 3
COL_TO_OU         = 9
COL_TO_BUCKET     = 10
COL_USD_AMOUNT    = 14
COL_SIGN_OFF_Q    = 16   # ML strat sign off FROM (Internal only)
COL_SIGN_OFF_R    = 17   # ML strat sign off TO
COL_MF_OWNER      = 18
COL_TO_BL_CODE    = 23
COL_TRX_SUBMITTED = 24
COL_COMMENTS_AD   = 29

def safe(row, idx):
    try: return str(row[idx]).strip()
    except IndexError: return ""

def is_blocking_comment(comment):
    """Comments that indicate no action needed."""
    c = comment.lower()
    return "same bl" in c or "no action" in c

def filter_rows(rows, transfer_type):
    """Apply all 5 filters and return (actionable, awaiting) lists."""
    data_rows = rows[6:]  # skip headers (rows 1-6)
    actionable = []
    awaiting   = []

    for row in data_rows:
        unique_id = safe(row, COL_UNIQUE_ID)
        if not unique_id:
            continue

        # Filter 1: TRX Submitted = FALSE
        if safe(row, COL_TRX_SUBMITTED).upper() != "FALSE":
            continue

        # Filter 2: Required columns populated (C, D, J, K, O)
        if not all([
            safe(row, COL_FROM_BL_CODE),
            safe(row, COL_FROM_BL_NAME),
            safe(row, COL_TO_OU),
            safe(row, COL_TO_BUCKET),
            safe(row, COL_USD_AMOUNT),
        ]):
            continue

        # Filter 3: FROM BL ≠ TO BL
        if safe(row, COL_FROM_BL_CODE) == safe(row, COL_TO_BL_CODE):
            continue

        # Filter 4: No blocking comments in Col AD
        if is_blocking_comment(safe(row, COL_COMMENTS_AD)):
            continue

        # Filter 5: Sign-off check
        sign_q = safe(row, COL_SIGN_OFF_Q)
        sign_r = safe(row, COL_SIGN_OFF_R)

        if transfer_type == "internal":
            has_signoff = bool(sign_q and sign_r)
        else:
            has_signoff = bool(sign_r)

        entry = {
            "id":       unique_id,
            "to_ou":    safe(row, COL_TO_OU),
            "to_bucket":safe(row, COL_TO_BUCKET),
            "amount":   safe(row, COL_USD_AMOUNT),
            "owner":    safe(row, COL_MF_OWNER),
            "missing":  [] if has_signoff else (
                ["Col Q", "Col R"] if transfer_type == "internal" and not sign_q and not sign_r
                else ["Col Q"] if transfer_type == "internal" and not sign_q
                else ["Col R"]
            )
        }

        if has_signoff:
            actionable.append(entry)
        else:
            awaiting.append(entry)

    return actionable, awaiting

# ── Slack user lookup ─────────────────────────────────────────────────────────

_user_cache = {}

def resolve_slack_id(client, name):
    if name in _user_cache:
        return _user_cache[name]
    try:
        res = client.users_list()
        for member in res["members"]:
            profile = member.get("profile", {})
            full_name = profile.get("real_name", "")
            if name.lower() in full_name.lower():
                _user_cache[name] = member["id"]
                return member["id"]
    except SlackApiError:
        pass
    _user_cache[name] = None
    return None

# ── Message builder ───────────────────────────────────────────────────────────

def format_amount(raw):
    raw = raw.replace("$", "").replace(",", "").strip()
    try:
        return f"${float(raw):,.2f}"
    except ValueError:
        return raw

def build_message(actionable, awaiting, quarter, client):
    today = date.today().strftime("%A, %d %B %Y")
    lines = [
        f":calendar: *Budget Transfer Submission Reminder — {today}*",
        f"Hi team! The following Q{quarter[-1]} transfers are pending BudgetForce submission. Please submit your TRX today :white_check_mark:",
        ""
    ]

    # Group actionable by owner
    by_owner = {}
    for row in actionable:
        owner = row["owner"] or "Unassigned"
        by_owner.setdefault(owner, []).append(row)

    grand_total = 0.0

    for owner, rows in sorted(by_owner.items()):
        slack_id = resolve_slack_id(client, owner)
        mention = f"<@{slack_id}>" if slack_id else f"*{owner}*"
        lines.append(f"*{mention}*")
        lines.append("| Unique ID | TO OU / Bucket | Amount |")
        lines.append("|---|---|---|")

        subtotal = 0.0
        for r in rows:
            amt_str = format_amount(r["amount"])
            try:
                subtotal += float(r["amount"].replace("$","").replace(",",""))
            except ValueError:
                pass
            lines.append(f"| {r['id']} | {r['to_ou']} / {r['to_bucket']} | {amt_str} |")

        grand_total += subtotal
        lines.append(f"*Subtotal: ${subtotal:,.2f}* _({len(rows)} transfer{'s' if len(rows)>1 else ''})_")
        lines.append("")

    lines.append(f":moneybag: *Grand Total: ${grand_total:,.2f}* across {len(actionable)} transfer{'s' if len(actionable)!=1 else ''}")
    lines.append("")

    if awaiting:
        lines.append(":hourglass_flowing_sand: *Awaiting Sign-Off* _(missing ML Strat sign-off)_")
        lines.append("| Unique ID | MF Owner | TO OU / Bucket | Amount | Missing |")
        lines.append("|---|---|---|---|---|")
        for r in awaiting:
            slack_id = resolve_slack_id(client, r["owner"]) if r["owner"] else None
            mention = f"<@{slack_id}>" if slack_id else r["owner"] or "—"
            amt_str = format_amount(r["amount"])
            missing = ", ".join(r["missing"])
            lines.append(f"| {r['id']} | {mention} | {r['to_ou']} / {r['to_bucket']} | {amt_str} | {missing} |")
        lines.append("")

    lines.append("_Please reply in thread or update the tracker once submitted. Thanks!_ :pray:")
    return "\n".join(lines)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    quarter = current_quarter()
    print(f"Running digest for {quarter}...")

    service = get_sheets_service()
    internal_tab = f"FY27{quarter} Internal Transfers"
    external_tab = f"FY27{quarter} External Transfers"

    print(f"Reading: {internal_tab}")
    internal_rows = read_tab(service, internal_tab)
    print(f"Reading: {external_tab}")
    external_rows = read_tab(service, external_tab)

    int_action, int_await = filter_rows(internal_rows, "internal")
    ext_action, ext_await = filter_rows(external_rows, "external")

    actionable = int_action + ext_action
    awaiting   = int_await  + ext_await

    print(f"Actionable: {len(actionable)} | Awaiting sign-off: {len(awaiting)}")

    client = WebClient(token=SLACK_TOKEN)

    if not actionable and not awaiting:
        message = f":white_check_mark: *Budget Transfer Digest — {date.today().strftime('%A, %d %B %Y')}*\nNo pending transfers to action for {quarter}. All clear!"
    else:
        message = build_message(actionable, awaiting, quarter, client)

    client.chat_postMessage(channel=SLACK_CHANNEL, text=message, mrkdwn=True)
    print("Message sent to Slack.")

if __name__ == "__main__":
    main()
