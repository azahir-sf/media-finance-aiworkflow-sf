"""
UMP Lock Announcement — Phase 1
Reads per-channel lock data from Google Sheets and posts draft UMP lock messages
to the Media Finance Slack channel for team review before sending to external channels.
"""

import os
import json
from datetime import date
from google.oauth2 import service_account
from googleapiclient.discovery import build
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# ── Config ────────────────────────────────────────────────────────────────────

SPREADSHEET_ID = "1Lx-4CoNRXpazJ5VtnslHO3P2TWlZ50VNM7IytBaAJ6c"
SHEET_TAB      = "UMP LOCK MESSAGE AUTOMATION_ASIN"
SLACK_TOKEN    = os.environ["SLACK_BOT_TOKEN"]
GOOGLE_CREDS   = os.environ["GOOGLE_CREDENTIALS"]
WORKFLOW_MODE  = os.environ.get("WORKFLOW_MODE", "test").strip().lower()
QUARTER        = os.environ.get("QUARTER", "Q3").strip().upper()
SEND_TO        = os.environ.get("SEND_TO", "U07628FGAN9").strip()
SLACK_CHANNEL  = SEND_TO if SEND_TO else "U07628FGAN9"

SLACK_IDS = {
    "Rachel La":        "U06D4UX21U7",
    "Asin Zahir":       "U07628FGAN9",
    "Arslan Farooq":    "U074S9XEE6L",
    "Andrea Li":        "PLACEHOLDER_ANDREA",
    "Asher Oosterbaan": "U072E5U4P6V",
}

GMT_OWNERS = {"Asin Zahir", "Arslan Farooq"}

QUARTER_CONFIG = {
    "Q2": {"lock_date": "June 19, 2026",      "atb_deadline": "June 23, 2026",      "locked_q_num": 2},
    "Q3": {"lock_date": "September 18, 2026", "atb_deadline": "September 22, 2026", "locked_q_num": 3},
    "Q4": {"lock_date": "December 11, 2026",  "atb_deadline": "December 15, 2026",  "locked_q_num": 4},
}

Q_LABELS = {1: "Q1 FY27", 2: "Q2 FY27", 3: "Q3 FY27", 4: "Q4 FY27", 5: "Q1 FY28 PRELIM"}
Q_EMOJIS = {1: ":1-blue:", 2: ":2-blue-9096:", 3: ":3-blue:", 4: ":4-blue:", 5: ":5-blue:"}
Q_DATES  = {
    1: ("2/1/2026",  "4/30/2026"),
    2: ("5/1/2026",  "7/31/2026"),
    3: ("8/1/2026",  "10/31/2026"),
    4: ("11/1/2026", "1/31/2027"),
    5: ("2/1/2027",  "4/30/2027"),
}
Q_COL = {1: 7, 2: 8, 3: 9, 4: 10, 5: 11}  # 0-indexed column positions in sheet row

# ── Google Sheets ─────────────────────────────────────────────────────────────

def get_sheets_service():
    creds_dict = json.loads(GOOGLE_CREDS)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    return build("sheets", "v4", credentials=creds)

def read_sheet(service):
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{SHEET_TAB}'!A1:V15"
    ).execute()
    return result.get("values", [])

# ── Helpers ───────────────────────────────────────────────────────────────────

def safe(row, idx):
    try: return str(row[idx]).strip()
    except IndexError: return ""

def mention(name):
    uid = SLACK_IDS.get(name)
    return f"<@{uid}>" if uid else f"*{name}*"

def timezone_for(owner):
    return "GMT" if owner in GMT_OWNERS else "PST"

def fmt_amount(raw):
    val = raw.strip().replace("$", "").replace(",", "")
    if val.startswith("(") and val.endswith(")"):
        val = val[1:-1]
    try:
        return f"${int(float(val)):,}"
    except ValueError:
        return raw

def fmt_atb(raw):
    val = raw.strip()
    if not val or val == "0":
        return "$0"
    if val.startswith("(") and val.endswith(")"):
        num = val[1:-1].replace(",", "")
        try:
            return f"${int(float(num)):,} decrease"
        except ValueError:
            return f"{val} decrease"
    try:
        return f"${int(float(val.replace(',', ''))):,} increase"
    except ValueError:
        return val

def section(text):
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}

def divider():
    return {"type": "divider"}

# ── Quarter section builder ───────────────────────────────────────────────────

def quarter_line(q_num, amount, locked_q_num):
    emoji        = Q_EMOJIS[q_num]
    label        = Q_LABELS[q_num]
    d_start, d_end = Q_DATES[q_num]

    if q_num == 5:
        note     = "(Decrease reflected by Media Finance)"
        amt_type = "Estimated Amount"
        extra    = (
            "\n:importantred: Please note that Media Finance reserves the rights to update Q1FY28 "
            "amount upon receiving the ATB from iPro and before final PR submission. Should the amount "
            "for Q1FY28 change, Media Finance will own adjusting the campaign detail table proportionally "
            "and will inform iPro on the changes."
        )
    elif q_num == locked_q_num:
        note     = "(to be updated by iPro)"
        amt_type = "Final Amount"
        extra    = ""
    elif q_num < locked_q_num:
        note     = "(No change from ATB issue 2)"
        amt_type = "Final Amount"
        extra    = ""
    else:
        note     = "(No change from ATB issue 2)"
        amt_type = "Initial Amount"
        extra    = ""

    return f"{emoji} *{label}* {note}\n\n{amt_type}: {fmt_amount(amount)}\nDates: {d_start}-{d_end}{extra}"

# ── Per-channel message blocks ────────────────────────────────────────────────

def build_channel_blocks(row, config):
    locked_q  = config["locked_q_num"]
    lock_date = config["lock_date"]
    atb_date  = config["atb_deadline"]

    channel  = safe(row, 1)
    bucket   = safe(row, 5)
    po       = safe(row, 6)
    sf_owner = safe(row, 3)
    ipro     = safe(row, 4)
    tz       = timezone_for(sf_owner)

    q_amounts = {q: safe(row, Q_COL[q]) for q in range(1, 6)}
    total_atb = safe(row, 12)
    atb1      = safe(row, 14)
    atb2      = safe(row, 15)
    atb3      = safe(row, 16)
    atb4      = safe(row, 17)
    total_rev = safe(row, 18)

    blocks = [
        divider(),
        section(f"*{channel}* — _{bucket}_"),
        section(
            f":announce-2711:: <!here>\n"
            f":lock: The {QUARTER} FY27 *{bucket}* Strategy UMP is officially locked as of 5PM {tz} "
            f"on {lock_date}. Please provide ATB/Change form based on instructions provided below "
            f"by EOD {atb_date} {tz}."
        ),
        section(
            f":memo: *Amounts to be included on ATB*\n"
            f"Below are the details of what must be included on the Change Form for *{po}*, following "
            f"the established 5-qtr PR approach. You only need to complete the ATB for the final "
            f"{QUARTER} portion; all others have been completed by Media Finance. Please validate you "
            f"are aligned with all other quarters."
        ),
        section(
            "\n\n".join(quarter_line(q, q_amounts[q], locked_q) for q in range(1, 6))
            + f"\n\n*TOTAL ATB AMOUNT: {fmt_amount(total_atb)}*"
        ),
    ]

    atb4_line = f"\nATB Issue #4: {fmt_atb(atb4)}" if atb4 and atb4 != "0" else ""
    blocks.append(section(
        f":channel_summary_alt: *Change Summary to be included in Change Form for PO {po}:*\n\n"
        f"ATB Issue #1 Amount: {fmt_atb(atb1)}\n"
        f"ATB Issue #2: {fmt_atb(atb2)}\n"
        f"ATB Issue #3: {fmt_atb(atb3)}"
        f"{atb4_line}\n"
        f"Total Revised Cost: {fmt_amount(total_rev)}\n\n"
        f"Please acknowledge the message here with :eyes: and please do not hesitate to reach out "
        f"to me with any questions. Thanks!\n"
        f"CC: {mention(sf_owner)} / {ipro}"
    ))

    return blocks

# ── Intro message ─────────────────────────────────────────────────────────────

def build_intro_blocks(config, num_channels):
    today      = date.today().strftime("%A, %d %B %Y")
    lock_date  = config["lock_date"]
    atb_date   = config["atb_deadline"]
    mode_label = "" if SLACK_CHANNEL.startswith("C") else "_Sent to DM only — not posted to team channel_\n"

    return [
        section(
            f":lock: *UMP Lock Announcement — {QUARTER} FY27 — {today}*\n{mode_label}"
            f"<!here> Hi team! Please see below for the {QUARTER} UMP lock messages "
            f"({num_channels} channels). We will publish in our respective channels on "
            f"*{lock_date}* at 5pm local time.\n\n"
            f"Please remember to fill out the ATB for all Qs except *{QUARTER}* and include in your "
            f"publish message. ATB/Change form due by *{atb_date}*. "
            f"Please let me/Andrea know if any questions!"
        ),
    ]

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    config = QUARTER_CONFIG.get(QUARTER)
    if not config:
        print(f"Unknown quarter: {QUARTER}. Must be Q2, Q3, or Q4.")
        raise SystemExit(1)

    print(f"Building UMP Lock digest for {QUARTER}...")

    service  = get_sheets_service()
    all_rows = read_sheet(service)

    # Data rows start at index 4 (row 5) — filter to rows with a channel name in col B
    data_rows = [r for r in all_rows[4:] if len(r) > 6 and safe(r, 1).startswith("#")]
    print(f"Found {len(data_rows)} channel rows.")

    client = WebClient(token=SLACK_TOKEN)

    try:
        # Post intro to channel
        intro_blocks = build_intro_blocks(config, len(data_rows))
        resp = client.chat_postMessage(
            channel=SLACK_CHANNEL,
            text=f"UMP Lock Announcement — {QUARTER} FY27",
            blocks=intro_blocks,
        )
        thread_ts = resp["ts"]
        print(f"Intro posted. Posting {len(data_rows)} channel drafts in thread...")

        # Post each channel's draft as a thread reply
        for i, row in enumerate(data_rows):
            channel_name = safe(row, 1)
            print(f"  [{i+1}/{len(data_rows)}] {channel_name}")
            blocks = build_channel_blocks(row, config)
            client.chat_postMessage(
                channel=SLACK_CHANNEL,
                text=f"Draft: {channel_name}",
                blocks=blocks,
                thread_ts=thread_ts,
            )

        print(f"Done. {len(data_rows)} drafts posted in thread.")

    except SlackApiError as e:
        print(f"Slack error: {e.response['error']}")
        raise SystemExit(1)

if __name__ == "__main__":
    main()
