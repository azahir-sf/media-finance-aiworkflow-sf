"""
Strategy vs Execution UMP Reconciliation
Reads Strategy Input and Execution Input Aggr tabs from each Execution UMP Google Sheet,
compares Briefed Budget by Unique Key, and posts a variance digest to Slack.
"""

import os
import json
from datetime import date
from google.oauth2 import service_account
from googleapiclient.discovery import build
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# ── Config ────────────────────────────────────────────────────────────────────

SLACK_TOKEN   = os.environ["SLACK_BOT_TOKEN"]
GOOGLE_CREDS  = os.environ["GOOGLE_CREDENTIALS"]
WORKFLOW_MODE = os.environ.get("WORKFLOW_MODE", "test").strip().lower()

SEND_TO = os.environ.get("SEND_TO", "U07628FGAN9").strip()
if SEND_TO == "CHANNEL":
    SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL_ID", "U07628FGAN9")
else:
    SLACK_CHANNEL = SEND_TO or "U07628FGAN9"

# ── UMP sheet registry ────────────────────────────────────────────────────────
# Add remaining UMPs here once sheet IDs are confirmed.
# Each entry: name, sheet_id, owner (MF team member), slack_id

UMPS = [
    {
        "name": "LATAM Field Priorities",
        "sheet_id": "1mhBdeU1mfqsUg9pxYhI4RXPfYKLs5rtWfrJSYiIMQh0",
        "owner": "Asin Zahir",
        "slack_id": "U07628FGAN9",
    },
    # EMEA FP (France, North & South) — Asin Zahir
    # "sheet_id": "TBD", "owner": "Asin Zahir", "slack_id": "U07628FGAN9"

    # EMEA FP (UKI & Central) — Arslan Farooq
    # "sheet_id": "TBD", "owner": "Arslan Farooq", "slack_id": "U074S9XEE6L"

    # Public Sector Global OU — Arslan Farooq
    # "sheet_id": "TBD", "owner": "Arslan Farooq", "slack_id": "U074S9XEE6L"

    # AMER Field Priorities — Asher Oosterbaan
    # "sheet_id": "TBD", "owner": "Asher Oosterbaan", "slack_id": "U072E5U4P6V"

    # APAC Field Priorities — Asher Oosterbaan
    # "sheet_id": "TBD", "owner": "Asher Oosterbaan", "slack_id": "U072E5U4P6V"

    # SMB & NextGen Global OUs — Asher Oosterbaan
    # "sheet_id": "TBD", "owner": "Asher Oosterbaan", "slack_id": "U072E5U4P6V"

    # Core Cloud Search — Rachel La
    # "sheet_id": "TBD", "owner": "Rachel La", "slack_id": "U06D4UX21U7"

    # Cloud Priorities & Global Campaigns — Rachel La
    # "sheet_id": "TBD", "owner": "Rachel La", "slack_id": "U06D4UX21U7"
]

MF_SLACK_IDS = {
    "Rachel La":        "U06D4UX21U7",
    "Asin Zahir":       "U07628FGAN9",
    "Arslan Farooq":    "U074S9XEE6L",
    "Asher Oosterbaan": "U072E5U4P6V",
}

# ── Quarter logic ─────────────────────────────────────────────────────────────

def current_quarter():
    override = os.environ.get("QUARTER", "").strip().upper()
    if override in ("Q1", "Q2", "Q3", "Q4"):
        return override
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

def read_tab(service, sheet_id, tab_name):
    result = service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range=f"'{tab_name}'!A1:Z2000"
    ).execute()
    return result.get("values", [])

# ── Parsing ───────────────────────────────────────────────────────────────────

COL_UNIQUE_KEY = 0
COL_QUARTER    = 3
COL_BUDGET     = 4  # Briefed Budget $ in both tabs

def safe(row, idx):
    try: return str(row[idx]).strip()
    except IndexError: return ""

def to_float(raw):
    try: return float(raw.replace("$", "").replace(",", "").strip())
    except (ValueError, AttributeError): return 0.0

def parse_budget_rows(rows, quarter):
    """Returns dict of {unique_key: briefed_budget_float} for the given quarter."""
    data = {}
    for row in rows[6:]:  # row 6 (index 6) is first data row; rows 0-5 are headers/labels
        key = safe(row, COL_UNIQUE_KEY)
        if not key:
            continue
        qtr = safe(row, COL_QUARTER).upper()
        if qtr != quarter:
            continue
        budget = to_float(safe(row, COL_BUDGET))
        data[key] = budget
    return data

# ── Reconciliation ────────────────────────────────────────────────────────────

def reconcile(strategy_data, execution_data):
    """
    Returns list of dicts: {key, strategy_budget, execution_budget, variance}
    Only includes rows present in strategy_data. Missing execution keys get $0.
    """
    results = []
    all_keys = set(strategy_data.keys()) | set(execution_data.keys())
    for key in sorted(all_keys):
        strat  = strategy_data.get(key, 0.0)
        exe    = execution_data.get(key, 0.0)
        variance = strat - exe
        results.append({
            "key":      key,
            "strategy": strat,
            "execution": exe,
            "variance": variance,
        })
    return results

# ── Helpers ───────────────────────────────────────────────────────────────────

def mention(name):
    uid = MF_SLACK_IDS.get(name)
    return f"<@{uid}>" if uid else f"*{name}*"

def fmt(amount):
    if amount < 0:
        return f"(${abs(amount):,.2f})"
    return f"${amount:,.2f}"

def is_zero(v):
    return abs(v) < 0.01

# ── Block Kit ─────────────────────────────────────────────────────────────────

def section(text):
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}

def divider():
    return {"type": "divider"}

def recon_table(rows):
    col1 = max(max(len(r["key"]) for r in rows), len("Unique Key"))
    col2 = max(max(len(fmt(r["strategy"])) for r in rows), len("Briefed Budget"))
    col3 = max(max(len(fmt(r["execution"])) for r in rows), len("Planned Budget"))
    col4 = max(max(len(fmt(r["variance"])) for r in rows), len("Variance"))

    header = (
        f"{'Unique Key':<{col1}}  "
        f"{'Briefed Budget':<{col2}}  "
        f"{'Planned Budget':<{col3}}  "
        f"{'Variance':<{col4}}"
    )
    divider_line = "-" * (col1 + col2 + col3 + col4 + 8)
    lines = [header, divider_line]
    for r in rows:
        variance_str = fmt(r["variance"])
        if not is_zero(r["variance"]):
            variance_str = f"⚠ {variance_str}"
        lines.append(
            f"{r['key']:<{col1}}  "
            f"{fmt(r['strategy']):<{col2}}  "
            f"{fmt(r['execution']):<{col3}}  "
            f"{variance_str}"
        )
    return "```" + "\n".join(lines) + "```"

def build_blocks(owner_results, quarter, has_variances):
    today = date.today().strftime("%A, %d %B %Y")
    blocks = []

    mode_label = "🧪 _TEST RUN — this message is a test and was not sent to the team channel_" if WORKFLOW_MODE == "test" else ""

    header_text = f":bar_chart: *Strategy vs Execution UMP Reconciliation — {today}*"
    if mode_label:
        header_text += f"\n{mode_label}"
    blocks.append(section(header_text))

    if not has_variances:
        blocks.append(section(
            f":white_check_mark: *All clear — {quarter} Strategy and Execution UMPs are fully reconciled. No variances.*"
        ))
        return blocks

    blocks.append(section(
        f":warning: *{quarter} reconciliation flagged variances. Please review and align with your iPro POC.*"
    ))
    blocks.append(divider())

    for owner, data in owner_results.items():
        rows      = data["rows"]
        ump_name  = data["ump_name"]
        variance_rows = [r for r in rows if not is_zero(r["variance"])]
        clean_rows    = [r for r in rows if is_zero(r["variance"])]

        subtotal_strat = sum(r["strategy"] for r in rows)
        subtotal_exe   = sum(r["execution"] for r in rows)
        total_variance = subtotal_strat - subtotal_exe

        blocks.append(section(f"*{mention(owner)} — {ump_name}*"))

        if variance_rows:
            blocks.append(section(f":warning: *{len(variance_rows)} row(s) with variance:*"))
            blocks.append(section(recon_table(variance_rows)))
        else:
            blocks.append(section(":white_check_mark: No variances in this UMP"))

        blocks.append(section(
            f"*Briefed Budget Total: {fmt(subtotal_strat)}* | "
            f"*Planned Budget Total: {fmt(subtotal_exe)}* | "
            f"*Net Variance: {fmt(total_variance)}*"
            + (f" _(clean rows: {len(clean_rows)})_" if clean_rows else "")
        ))
        blocks.append(divider())

    return blocks

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    quarter = current_quarter()
    print(f"Running Strategy vs Execution reconciliation for {quarter}...")

    service = get_sheets_service()

    owner_results = {}
    has_variances = False

    for ump in UMPS:
        print(f"  Reading {ump['name']}...")
        try:
            strat_rows = read_tab(service, ump["sheet_id"], "Strategy Input")
            exec_rows  = read_tab(service, ump["sheet_id"], "Execution Input Aggr")
        except Exception as e:
            print(f"  ERROR reading {ump['name']}: {e}")
            continue

        strat_data = parse_budget_rows(strat_rows, quarter)
        exec_data  = parse_budget_rows(exec_rows,  quarter)

        if not strat_data and not exec_data:
            print(f"  No {quarter} rows found in {ump['name']} — skipping")
            continue

        rows = reconcile(strat_data, exec_data)
        owner = ump["owner"]

        if owner not in owner_results:
            owner_results[owner] = {"rows": [], "ump_name": ump["name"]}
        owner_results[owner]["rows"].extend(rows)

        if any(not is_zero(r["variance"]) for r in rows):
            has_variances = True

    if not owner_results:
        print(f"No data found for {quarter} across all UMPs.")
        return

    total_variance_rows = sum(
        1 for data in owner_results.values()
        for r in data["rows"] if not is_zero(r["variance"])
    )
    print(f"Total rows with variance: {total_variance_rows}")

    client = WebClient(token=SLACK_TOKEN)
    try:
        blocks = build_blocks(owner_results, quarter, has_variances)
        client.chat_postMessage(
            channel=SLACK_CHANNEL,
            text=f"Strategy vs Execution UMP Reconciliation — {quarter}",
            blocks=blocks
        )
        print(f"Message sent to {SLACK_CHANNEL}.")
    except SlackApiError as e:
        print(f"Slack error: {e.response['error']}")
        raise SystemExit(1)

if __name__ == "__main__":
    main()
