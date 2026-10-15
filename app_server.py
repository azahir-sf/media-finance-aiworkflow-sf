"""
MF Bot — Flask API server.
Receives trigger requests from the web console and runs workflow scripts
as background threads.
"""

import os
import subprocess
import threading
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

API_KEY = os.environ.get("MF_BOT_API_KEY", "")

WORKFLOW_SCRIPTS = {
    "budget_transfer": "workflows/budget_transfer_digest.py",
    "ump_lock":        "workflows/ump_lock.py",
    "ipro_sync":       "workflows/ipro_sync_reminder.py",
    "strat_ex_recon":  "workflows/strat_ex_recon.py",
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _run(script, env):
    subprocess.run(["python", script], env=env, cwd=BASE_DIR)


@app.route("/run/<workflow>", methods=["POST"])
def trigger(workflow):
    auth = request.headers.get("Authorization", "")
    if API_KEY and auth != f"Bearer {API_KEY}":
        return jsonify({"error": "Unauthorized"}), 401

    if workflow not in WORKFLOW_SCRIPTS:
        return jsonify({"error": f"Unknown workflow: {workflow}"}), 404

    data      = request.get_json(force=True, silent=True) or {}
    workspace = data.get("workspace", "production")

    env = os.environ.copy()
    env["SLACK_BOT_TOKEN"]   = (
        os.environ.get("SLACK_BOT_TOKEN_SANDBOX", "")
        if workspace == "sandbox"
        else os.environ.get("SLACK_BOT_TOKEN", "")
    )
    env["GOOGLE_CREDENTIALS"] = os.environ.get("GOOGLE_CREDENTIALS", "")
    env["SLACK_CHANNEL_ID"]   = os.environ.get("SLACK_CHANNEL_ID", "")
    env["WORKFLOW_MODE"]      = data.get("mode", "test")
    env["SEND_TO"]            = data.get("send_to", "U07628FGAN9")
    env["QUARTER"]            = data.get("quarter", "Q4")

    t = threading.Thread(target=_run, args=(WORKFLOW_SCRIPTS[workflow], env), daemon=True)
    t.start()

    return "", 204


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
