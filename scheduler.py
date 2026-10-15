"""
MF Bot — clock process for scheduled workflows.
Runs as a separate Heroku dyno (clock: python scheduler.py).
"""

import os
import subprocess
import schedule
import time
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def run(script, overrides=None):
    env = os.environ.copy()
    env["SLACK_BOT_TOKEN"]    = os.environ.get("SLACK_BOT_TOKEN", "")
    env["GOOGLE_CREDENTIALS"] = os.environ.get("GOOGLE_CREDENTIALS", "")
    env["SLACK_CHANNEL_ID"]   = os.environ.get("SLACK_CHANNEL_ID", "")
    if overrides:
        env.update(overrides)
    print(f"[{datetime.now(timezone.utc).isoformat()}] Running {script}", flush=True)
    subprocess.run(["python", script], env=env, cwd=BASE_DIR)


def budget_transfer():
    run("workflows/budget_transfer_digest.py", {
        "WORKFLOW_MODE": "live",
        "SEND_TO":       "CHANNEL",
        "QUARTER":       "Q4",
    })


def ipro_reminder():
    run("workflows/ipro_sync_reminder.py", {
        "WORKFLOW_MODE": "live",
        "SEND_TO":       "CHANNEL",
    })


# Budget Transfer Digest — every Tuesday and Thursday at 8am UTC
schedule.every().tuesday.at("08:00").do(budget_transfer)
schedule.every().thursday.at("08:00").do(budget_transfer)

# iPro Finance Sync Reminder — every Wednesday at 10am UTC
schedule.every().wednesday.at("10:00").do(ipro_reminder)

print("MF Bot scheduler started.", flush=True)
while True:
    schedule.run_pending()
    time.sleep(30)
