# Media Finance AI Workflow — Project Context

## What this project is

A set of automated Slack workflows for the Paid Media Finance team at Salesforce, triggered via GitHub Actions and managed through a web console hosted on GitHub Pages.

**Repo:** `azahir-sf/media-finance-aiworkflow-sf` (private)
**Console (live):** `https://azahir-sf.github.io/media-finance-aiworkflow-sf/`
**Local path:** `/Users/azahir/claude/media-finance-aiworkflow-sf/`

---

## File structure

```
index.html                          Web console (all UI in one file)
logo.png                            Salesforce cloud logo for header
workflows/
  budget_transfer_digest.py         Budget Transfer Digest workflow
  ump_lock.py                       UMP Lock Announcement workflow
  ipro_sync_reminder.py             iProspect Finance Sync Reminder workflow
  edit_message.py                   One-off utility to edit a bot message
.github/workflows/
  budget-transfer.yml               GitHub Actions for Budget Transfer
  ump-lock.yml                      GitHub Actions for UMP Lock
  ipro-sync-reminder.yml            GitHub Actions for iPro Reminder
  edit-message.yml                  GitHub Actions for edit utility
```

---

## Workflows built

### 1. Budget Transfer Digest (`budget_transfer_digest.py`)
- Reads FY27 Paid Media Budget Transfer Google Sheet (ID: `1zr_aKPzHIlYhbO4V7DUR24CsQC1ICsBeMWB6dIikI1A`)
- Filters pending TRX submissions from Internal and External Transfer tabs
- Groups by MF owner, shows actionable vs. awaiting sign-off rows
- Posts formatted Slack Block Kit message
- **Schedule:** Tuesday & Thursday at 8am GMT (auto via GitHub Actions)
- **Tabs read:** `FY27Q# Internal Transfers` and `FY27Q# External Transfers`

### 2. UMP Lock Announcement (`ump_lock.py`)
- Reads per-channel lock data from UMP Lock Sheet (ID: `1Lx-4CoNRXpazJ5VtnslHO3P2TWlZ50VNM7IytBaAJ6c`)
- Posts intro message to MF channel, then per-channel drafts in a thread
- Each draft shows 5-quarter amounts, ATB change summary, CC line
- **Trigger:** On demand (quarterly — Q2, Q3, Q4)
- **Quarter config:** Q2 (19 Jun / 23 Jun), Q3 (18 Sep / 22 Sep), Q4 (11 Dec / 15 Dec)

### 3. iProspect Finance Sync Reminder (`ipro_sync_reminder.py`)
- Posts a weekly Wednesday reminder to update the iPro Finance call agenda
- Links to the shared Google Doc agenda
- **Schedule:** Wednesday at 3pm GMT (auto via GitHub Actions)

### 4. Edit Message utility (`edit_message.py`)
- One-off script to edit an existing bot message by channel + timestamp
- Used manually when a correction is needed post-send

---

## Web Console (`index.html`)

A single-page HTML/CSS/JS dashboard that lets the team trigger workflows manually.

- GitHub Personal Access Token stored in browser localStorage (never sent anywhere except GitHub)
- Each workflow card has a **Send To** dropdown (test channel, team channel, individual DMs, sandbox)
- **Test/Live toggle** — Test adds a 🧪 disclaimer to the message; Live sends clean
- Sandbox channel option shows a workspace selector (sandbox vs production)
- Activity log panel at the bottom shows trigger status
- Fetches last run status from GitHub Actions API for the Budget Transfer card

**Channels hardcoded in the console:**
- `C0BPQEHNGUV` — #mf-testing-ai-workflow (default / safe test destination)
- `CHANNEL` — #media-finance-team-channel (real team channel, uses `SLACK_CHANNEL_ID` secret)
- `C0BUK5NBC11` — Sandbox channel

**Planned / coming soon (greyed out cards):**
- PR / CO Status Tracker (Coupa)
- Invoice Tracker
- AI Procurement Agent

---

## Environment variables / secrets (GitHub Actions)

| Secret | Purpose |
|--------|---------|
| `SLACK_BOT_TOKEN` | Bot token for all Slack posts |
| `GOOGLE_CREDENTIALS` | GCP service account JSON for Sheets access |
| `SLACK_CHANNEL_ID` | Real team channel ID (used when `SEND_TO=CHANNEL`) |

- `WORKFLOW_MODE` — `test` (adds disclaimer) or `live` (clean message); set per-run via workflow dispatch inputs
- `SEND_TO` — target channel/user ID; set per-run; defaults to Asin's DM if not supplied
- `QUARTER` — for UMP Lock only; set per-run via dispatch inputs

---

## Slack IDs (MF team)

| Name | Slack ID |
|------|----------|
| Rachel La | U06D4UX21U7 |
| Asin Zahir | U07628FGAN9 |
| Arslan Farooq | U074S9XEE6L |
| Asher Oosterbaan | U072E5U4P6V |
| Andrea Li | D075ZC50RP1 |

ML Strategist Slack IDs are not yet mapped — names display as plain text until IDs are added to `SLACK_IDS` in `budget_transfer_digest.py`.

---

## GCP / Google Sheets auth

- Service account JSON stored as `GOOGLE_CREDENTIALS` GitHub secret
- Currently under a personal Gmail GCP project (working in production)
- Pending migration to Salesforce AppDev GCP tenant (tracked in memory: `project_gcp_setup.md`)
- Scopes: `spreadsheets.readonly`

---

## Slack Bot approval status

- Bot posts to internal MF Slack channels — approved and working
- **Phase 2 (posting to 8 ML Slack Connect external channels) is blocked** — requires IT approval via #slack-app-approvals
- Pre-requisites: sandbox testing, video walkthrough, code-level channel restriction confirmed
- Tracked in memory: `project_slack_bot_approval.md`

---

## Key design decisions

- All workflow Python files are self-contained — no shared utility modules
- `WORKFLOW_MODE=test` and `SEND_TO` are set via GitHub Actions dispatch inputs, not hardcoded
- The console always defaults to test mode on load (never restores last toggle state) to prevent accidental live sends
- Block Kit is used for all Slack messages for consistent formatting
- Column indexes in `budget_transfer_digest.py` are constants at the top — update these if the sheet structure changes
