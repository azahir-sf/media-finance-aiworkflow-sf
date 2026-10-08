"""
Strategy vs Execution UMP Reconciliation
Reads Strategy GLOBAL AGGREGATION and GLOBAL AGGREGATION EXECUTION tabs
from the FY27 Global UMP Aggregation sheet, compares Briefed Budget vs
Planned Budget by Unique Key for the given quarter, and posts to Slack.
"""

import os
import json
from datetime import date
from google.oauth2 import service_account
from googleapiclient.discovery import build
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# ── Config ─────────────────────────────────────────────────────────────────────

SLACK_TOKEN   = os.environ["SLACK_BOT_TOKEN"]
GOOGLE_CREDS  = os.environ["GOOGLE_CREDENTIALS"]
WORKFLOW_MODE = os.environ.get("WORKFLOW_MODE", "test").strip().lower()

SEND_TO = os.environ.get("SEND_TO", "U07628FGAN9").strip()
if SEND_TO == "CHANNEL":
    SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL_ID", "U07628FGAN9")
else:
    SLACK_CHANNEL = SEND_TO or "U07628FGAN9"

# ── Sheet config ───────────────────────────────────────────────────────────────

GLOBAL_SHEET_ID = "1TlKzFr-C7QEW-1b-Hp9Ccvzeh5IetMg-P3fUVaeUuXQ"
STRATEGY_TAB    = "Strategy GLOBAL AGGREGATION"
EXECUTION_TAB   = "GLOBAL AGGREGATION EXECUTION"

# Column indexes (0-based)
COL_UNIQUE_KEY = 0   # A — Unique Key
COL_QUARTER    = 3   # D — Campaign Quarter
COL_OU         = 8   # I — Campaign OU
COL_BUCKET     = 10  # K — Bucket
COL_BRIEFED    = 4   # E — Briefed Budget $ (Strategy tab)
COL_PLANNED    = 48  # AW — Planned Budget $ (Execution tab)

# Rows 1-6 are title/header/label rows; data starts at row 7 (index 6)
DATA_START_ROW = 6

MF_SLACK_IDS = {
    "Rachel La":        "U06D4UX21U7",
    "Asin Zahir":       "U07628FGAN9",
    "Arslan Farooq":    "U074S9XEE6L",
    "Asher Oosterbaan": "U072E5U4P6V",
}

# ── Quarter logic ──────────────────────────────────────────────────────────────

def current_quarter():
    override = os.environ.get("QUARTER", "").strip().upper()
    if override in ("Q1", "Q2", "Q3", "Q4"):
        return override
    month = date.today().month
    if month in (2, 3, 4):  return "Q1"
    if month in (5, 6, 7):  return "Q2"
    if month in (8, 9, 10): return "Q3"
    return "Q4"

# ── Google Sheets ──────────────────────────────────────────────────────────────

def get_sheets_service():
    creds_dict = json.loads(GOOGLE_CREDS)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    return build("sheets", "v4", credentials=creds)

def read_tab(service, tab_name, max_col):
    result = service.spreadsheets().values().get(
        spreadsheetId=GLOBAL_SHEET_ID,
        range=f"'{tab_name}'!A1:{max_col}5000"
    ).execute()
    return result.get("values", [])

# ── Parsing ────────────────────────────────────────────────────────────────────

def safe(row, idx):
    try: return str(row[idx]).strip()
    except IndexError: return ""

def to_float(raw):
    try:
        return float(
            raw.replace("$", "").replace(",", "")
               .replace("(", "-").replace(")", "").strip()
        )
    except (ValueError, AttributeError):
        return 0.0

def get_mf_owner(key, bucket, ou):
    """Map a row to its MF owner based on key prefix, bucket, and Campaign OU."""
    k = key.strip()
    b = bucket.strip().lower()
    o = ou.strip().upper()

    # Global OU — split by Unique Key prefix
    if k.startswith(("NextGen", "SMB")):
        return "Asher Oosterbaan"

    # Cloud channels → Rachel
    if "core cloud search" in b:
        return "Rachel La"
    if "cloud priorities" in b or "global campaigns" in b:
        return "Rachel La"

    # Field Priorities — split by Campaign OU
    if "field priorities" in b:
        if "latam" in o:
            return "Asin Zahir"
        if o in ("UKI", "CENTRAL"):
            return "Arslan Farooq"
        if "amer" in o or "acc" in o or "namer" in o:
            return "Asher Oosterbaan"
        if "apac" in o:
            return "Asher Oosterbaan"
        # Remaining EMEA (France, North, South) → Asin
        return "Asin Zahir"

    # Public Sector / remaining Global OU → Arslan
    return "Arslan Farooq"

def parse_rows(rows, quarter, budget_col, sum_duplicates=False):
    """Returns {unique_key: (budget, bucket, ou)} filtered to the given quarter."""
    data = {}
    for row in rows[DATA_START_ROW:]:
        key = safe(row, COL_UNIQUE_KEY)
        if not key:
            continue
        if safe(row, COL_QUARTER).upper() != quarter:
            continue
        budget = to_float(safe(row, budget_col))
        if sum_duplicates and key in data:
            prev_budget, bucket, ou = data[key]
            data[key] = (prev_budget + budget, bucket, ou)
        else:
            data[key] = (budget, safe(row, COL_BUCKET), safe(row, COL_OU))
    return data

# ── Reconciliation ─────────────────────────────────────────────────────────────

def reconcile_and_group(strategy_data, execution_data):
    """Joins on Unique Key using Strategy as master list, returns {owner: [row_dicts]}."""
    owner_rows = {}
    for key in sorted(strategy_data):
        s_budget, s_bucket, s_ou = strategy_data.get(key, (0.0, "", ""))
        e_budget, e_bucket, e_ou = execution_data.get(key, (0.0, "", ""))
        bucket = s_bucket or e_bucket
        ou     = s_ou or e_ou
        owner  = get_mf_owner(key, bucket, ou)
        owner_rows.setdefault(owner, []).append({
            "key":       key,
            "strategy":  s_budget,
            "execution": e_budget,
            "variance":  s_budget - e_budget,
            "bucket":    bucket,
            "ou":        ou,
        })
    return owner_rows

# ── Helpers ────────────────────────────────────────────────────────────────────

def mention(name):
    uid = MF_SLACK_IDS.get(name)
    return f"<@{uid}>" if uid else f"*{name}*"

def fmt(amount):
    return f"(${abs(amount):,.2f})" if amount < 0 else f"${amount:,.2f}"

def is_zero(v):
    return abs(v) < 0.01

# ── Block Kit ──────────────────────────────────────────────────────────────────

def section(text):
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}

def divider():
    return {"type": "divider"}

def recon_table(rows):
    col1 = max(max(len(r["key"]) for r in rows), len("Unique Key"))
    col2 = max(max(len(fmt(r["strategy"])) for r in rows), len("Briefed"))
    col3 = max(max(len(fmt(r["execution"])) for r in rows), len("Planned"))
    col4 = max(max(len(fmt(r["variance"])) for r in rows), len("Variance"))
    header = f"{'Unique Key':<{col1}}  {'Briefed':<{col2}}  {'Planned':<{col3}}  {'Variance':<{col4}}"
    sep    = "-" * (col1 + col2 + col3 + col4 + 8)
    lines  = [header, sep]
    for r in rows:
        v_str = fmt(r["variance"])
        if not is_zero(r["variance"]):
            v_str = f"⚠ {v_str}"
        lines.append(
            f"{r['key']:<{col1}}  {fmt(r['strategy']):<{col2}}  {fmt(r['execution']):<{col3}}  {v_str}"
        )
    return "```" + "\n".join(lines) + "```"

def build_blocks(owner_rows, quarter, has_variances):
    today = date.today().strftime("%A, %d %B %Y")
    blocks = []

    mode_label = "🧪 _TEST RUN — this message is a test and was not sent to the team channel_" if WORKFLOW_MODE == "test" else ""
    header_text = f":bar_chart: *Strategy vs Execution UMP Reconciliation — {today}*"
    if mode_label:
        header_text += f"\n{mode_label}"
    blocks.append(section(header_text))

    if not has_variances:
        blocks.append(section(
            f":white_check_mark: *All clear — {quarter} Strategy and Execution UMPs are fully reconciled. No variances found.*"
        ))
        blocks.append(divider())
        blocks.append(section("_Great work team! :tada:_"))
        return blocks

    total_var_rows = sum(1 for rows in owner_rows.values() for r in rows if not is_zero(r["variance"]))
    blocks.append(section(
        f"Hi team! The {quarter} reconciliation has flagged *{total_var_rows} row(s) with variances* "
        f"between Strategy (Briefed Budget) and Execution (Planned Budget). "
        f"Please review and align with your iPro POC. :white_check_mark:"
    ))
    blocks.append(divider())

    grand_briefed  = 0.0
    grand_planned  = 0.0

    for owner, rows in sorted(owner_rows.items()):
        variance_rows = [r for r in rows if not is_zero(r["variance"])]
        if not variance_rows:
            continue

        clean_count = sum(1 for r in rows if is_zero(r["variance"]))
        subtotal_s  = sum(r["strategy"]  for r in rows)
        subtotal_e  = sum(r["execution"] for r in rows)
        total_var   = subtotal_s - subtotal_e
        grand_briefed += subtotal_s
        grand_planned += subtotal_e

        blocks.append(section(f"*{mention(owner)}*"))

        # Chunk table to avoid Slack's 3000-char block limit
        chunk_size = 20
        for i in range(0, len(variance_rows), chunk_size):
            blocks.append(section(recon_table(variance_rows[i:i + chunk_size])))

        clean_note = f" _({clean_count} clean row{'s' if clean_count != 1 else ''} not shown)_" if clean_count else ""
        blocks.append(section(
            f"*Briefed: {fmt(subtotal_s)}* | *Planned: {fmt(subtotal_e)}* | "
            f"*Net Variance: {fmt(total_var)}*{clean_note}"
        ))
        blocks.append(divider())

    grand_var = grand_briefed - grand_planned
    blocks.append(section(
        f":moneybag: *Overall — Briefed: {fmt(grand_briefed)} | Planned: {fmt(grand_planned)} | "
        f"Net Variance: {fmt(grand_var)}*"
    ))
    blocks.append(divider())
    blocks.append(section("_Please reply in thread or update your UMP once aligned. Thanks!_ :pray:"))

    return blocks

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    quarter = current_quarter()
    print(f"Running Strategy vs Execution reconciliation for {quarter}...")

    service = get_sheets_service()

    print(f"  Reading {STRATEGY_TAB}...")
    strat_raw = read_tab(service, STRATEGY_TAB, max_col="Z")
    print(f"  Reading {EXECUTION_TAB}...")
    exec_raw  = read_tab(service, EXECUTION_TAB, max_col="AX")

    strat_data = parse_rows(strat_raw, quarter, COL_BRIEFED)
    exec_data  = parse_rows(exec_raw,  quarter, COL_PLANNED, sum_duplicates=True)

    # Verify total unique Strategy IDs across all quarters
    all_strat_keys = {safe(r, COL_UNIQUE_KEY) for r in strat_raw[DATA_START_ROW:] if safe(r, COL_UNIQUE_KEY)}
    print(f"  Total unique Strategy IDs (all quarters): {len(all_strat_keys)}")
    print(f"  Strategy rows for {quarter}: {len(strat_data)}")
    print(f"  Execution rows for {quarter} (after summing duplicates): {len(exec_data)}")

    if not strat_data and not exec_data:
        print(f"No {quarter} data found in either tab.")
        return

    owner_rows    = reconcile_and_group(strat_data, exec_data)
    has_variances = any(
        not is_zero(r["variance"])
        for rows in owner_rows.values()
        for r in rows
    )
    total_var_rows = sum(
        1 for rows in owner_rows.values()
        for r in rows if not is_zero(r["variance"])
    )
    print(f"  Total rows with variance: {total_var_rows}")

    client = WebClient(token=SLACK_TOKEN)
    try:
        channel = SLACK_CHANNEL
        if channel.startswith("U"):
            resp = client.conversations_open(users=[channel])
            channel = resp["channel"]["id"]

        blocks = build_blocks(owner_rows, quarter, has_variances)
        client.chat_postMessage(
            channel=channel,
            text=f"Strategy vs Execution UMP Reconciliation — {quarter}",
            blocks=blocks,
        )
        print(f"  Message sent to {channel}.")
    except SlackApiError as e:
        print(f"  Slack error: {e.response['error']}")
        raise SystemExit(1)

if __name__ == "__main__":
    main()
