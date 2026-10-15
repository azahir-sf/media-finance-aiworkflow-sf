"""
iProspect Finance Sync Reminder
Posts a weekly reminder to the Media Finance channel every Wednesday
asking the team to update the agenda ahead of the Thursday iPro call.
"""

import os
from datetime import date, timedelta
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# ── Config ────────────────────────────────────────────────────────────────────

SLACK_TOKEN   = os.environ["SLACK_BOT_TOKEN"]
WORKFLOW_MODE = os.environ.get("WORKFLOW_MODE", "test").strip().lower()
SEND_TO       = os.environ.get("SEND_TO", "U07628FGAN9").strip()

if SEND_TO == "CHANNEL":
    SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL_ID", "U07628FGAN9")
else:
    SLACK_CHANNEL = SEND_TO or "U07628FGAN9"

# ── Channel allowlist — fails closed ─────────────────────────────────────────
APPROVED_CHANNELS = {
    "C0BUK5NBC11",  # Sandbox channel
    "C0BPQEHNGUV",  # #mf-testing-ai-workflow
    "C0721HF08ES",  # #media-finance-team-channel
    "C09BHTMPG1J",  # #ip-core-cloud-search-budget
    "C09BHTN4K7E",  # #ip-cloud-priorities-budget
    "C09AWF3BD0T",  # #ip-amer-field-budget
    "C09BFT2HNCW",  # #ip-emea-field-budget
    "C095L26C3GF",  # #ip-sf-apac-media-budget
    "C09D76FDW6B",  # #ip-latam-field-budget
    "C09THMZ4FEF",  # #ip-global-ou-field-budget
    "C08NCK7F5HD",  # #team-finance-iprospect
}
if SLACK_CHANNEL.startswith("C") and SLACK_CHANNEL not in APPROVED_CHANNELS:
    raise SystemExit(f"Channel {SLACK_CHANNEL} is not on the approved list. Aborting.")

AGENDA_URL = "https://docs.google.com/document/d/1GBBX3sUDFckBbO_thSInEo0YkJNAJqmMUW0e0Gx6iBE/edit?tab=t.0"

# ── Helpers ───────────────────────────────────────────────────────────────────

def next_thursday():
    today = date.today()
    days_ahead = (3 - today.weekday()) % 7
    return today + timedelta(days=days_ahead)

def section(text):
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}

def divider():
    return {"type": "divider"}

# ── Message builder ───────────────────────────────────────────────────────────

def build_blocks():
    thursday = next_thursday()
    thursday_str = thursday.strftime("%-d %B")
    mode_label = "🧪 _TEST RUN — this message is a test and was not sent to the team channel_\n" if WORKFLOW_MODE == "test" else ""

    return [
        section(
            f"{mode_label}"
            f"👋 Hey team! Hope everyone's doing well! <!here>\n\n"
            f"\n"
            f"Just a heads-up — our *iProspect Finance Sync is this Thursday, {thursday_str}*. "
            f"Please take a moment to add any updates, questions or topics to the agenda before the call "
            f"so we can make the most of the session.\n\n"
            f"\n"
            f"📋 *<{AGENDA_URL}|Weekly SF+IP Finance Connect: Agenda / Notes>*\n\n"
            f"\n"
            f"Thank you! 🙏"
        ),
    ]

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Sending iProspect Finance Sync reminder...")
    client = WebClient(token=SLACK_TOKEN)
    try:
        blocks = build_blocks()
        client.chat_postMessage(
            channel=SLACK_CHANNEL,
            text="Weekly iProspect Finance Sync — agenda reminder",
            blocks=blocks,
        )
        print(f"Reminder sent to {SLACK_CHANNEL}.")
    except SlackApiError as e:
        print(f"Slack error: {e.response['error']}")
        raise SystemExit(1)

if __name__ == "__main__":
    main()
