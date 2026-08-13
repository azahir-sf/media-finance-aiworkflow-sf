"""
One-off script to edit a specific bot message.
"""

import os
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

SLACK_TOKEN  = os.environ["SLACK_BOT_TOKEN"]
CHANNEL_ID   = os.environ["EDIT_CHANNEL_ID"]
MESSAGE_TS   = os.environ["EDIT_MESSAGE_TS"]
NEW_TEXT     = os.environ["EDIT_NEW_TEXT"]

client = WebClient(token=SLACK_TOKEN)

try:
    client.chat_update(
        channel=CHANNEL_ID,
        ts=MESSAGE_TS,
        text=NEW_TEXT,
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": NEW_TEXT}
            }
        ]
    )
    print(f"Message updated successfully.")
except SlackApiError as e:
    print(f"Slack error: {e.response['error']}")
    raise SystemExit(1)
