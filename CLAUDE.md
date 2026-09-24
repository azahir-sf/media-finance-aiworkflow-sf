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
  keepalive.yml                     Daily no-op to prevent GitHub disabling scheduled workflows
```

---

## Workflows built

### 1. Budget Transfer Digest (`budget_transfer_digest.py`)
- Reads FY27 Paid Media Budget Transfer Google Sheet (ID: `1zr_aKPzHIlYhbO4V7DUR24CsQC1ICsBeMWB6dIikI1A`)
- Filters pending TRX submissions from Internal and External Transfer tabs
- Groups by MF owner, shows actionable vs. awaiting sign-off rows
- Posts formatted Slack Block Kit message
- **Schedule:** Tuesday & Thursday at 8am UTC (auto via GitHub Actions)
- **Current quarter:** Q4 — tabs read: `FY27Q4 Internal Transfers` and `FY27Q4 External Transfers`
- **Quarter control:** Set via `QUARTER` input in yml (default Q4). Update default when quarter changes.
- When 0 actionable rows, posts a single "all caught up" line with excluded row count (listing all rows caused `invalid_blocks` error — do not revert this)

### 2. UMP Lock Announcement (`ump_lock.py`)
- Reads per-channel lock data from UMP Lock Sheet (ID: `1Lx-4CoNRXpazJ5VtnslHO3P2TWlZ50VNM7IytBaAJ6c`)
- Tab: `UMP LOCK MESSAGE AUTOMATION_ASIN`
- Posts intro message to MF channel, then per-channel drafts in a thread
- Each draft shows 5-quarter amounts, ATB change summary, CC line with iPro POC tags
- **Trigger:** On demand (quarterly — Q2, Q3, Q4)
- **Quarter config:** Q2 (19 Jun / 23 Jun), Q3 (18 Sep / 22 Sep), Q4 (11 Dec / 15 Dec)
- **Column mapping (0-indexed):**
  - W(22)=Q1, X(23)=Q2, Y(24)=Q3, Z(25)=Q4, AA(26)=Q5
  - AB(27)=Total ATB, AD(29)=ATB#1, AE(30)=ATB#2, AF(31)=ATB#3, AG(32)=ATB#4, AH(33)=ATB#5, AI(34)=Total Revised Cost
  - ATB#5 shows only when column AH has a non-zero value
- **Sheet read range:** `A1:AJ20`
- **Bucket name in sheet:** `"Cloud Priorities & Global Campaigns"` (combined — not separate). This key must exist in `IPRO_IDS` and `ATB5_BUCKETS`.

### 3. iProspect Finance Sync Reminder (`ipro_sync_reminder.py`)
- Posts a weekly Wednesday reminder to update the iPro Finance call agenda
- Links to the shared Google Doc agenda
- **Schedule:** Wednesday at 10am UTC (moved from 3pm — GitHub runners run 3-5hrs late, so 10am ensures delivery by ~2pm GMT)
- No Google Sheets dependency

### 4. Edit Message utility (`edit_message.py`)
- One-off script to edit an existing bot message by channel + timestamp
- Used manually when a correction is needed post-send

### 5. Keepalive (`keepalive.yml`)
- Runs daily at 6am UTC with `echo "keepalive"`
- Prevents GitHub from disabling scheduled workflows on inactive repos

---

## Web Console (`index.html`)

A single-page HTML/CSS/JS dashboard that lets the team trigger workflows manually.

- GitHub Personal Access Token stored in browser localStorage (never sent anywhere except GitHub)
- Each workflow card has a **Send To** dropdown (test channel, team channel, individual DMs, sandbox)
- **Test/Live toggle** — Test adds a 🧪 disclaimer to the message; Live sends clean
- Sandbox channel option shows a workspace selector (sandbox vs production)
- Activity log panel at the bottom shows trigger status
- Fetches last run status from GitHub Actions API for the Budget Transfer card
- Budget Transfer card has a **Quarter dropdown** (Q1–Q4, default Q4) — same pattern as UMP Lock card

**Channels hardcoded in the console:**
- `C0BPQEHNGUV` — #mf-testing-ai-workflow (default / safe test destination)
- `CHANNEL` — #media-finance-team-channel (real team channel, uses `SLACK_CHANNEL_ID` secret)
- `C0721HF08ES` — #media-finance-team-channel actual channel ID (stored as `SLACK_CHANNEL_ID` secret)
- `C0BUK5NBC11` — Sandbox channel

**Planned / coming soon (greyed out cards):**
- PR / CO Status Tracker (Coupa)
- Invoice Tracker
- AI Procurement Agent

---

## Environment variables / secrets (GitHub Actions)

| Secret | Purpose |
|--------|---------|
| `SLACK_BOT_TOKEN` | Bot token for all Slack posts (production) |
| `SLACK_BOT_TOKEN_SANDBOX` | Bot token for sandbox workspace |
| `GOOGLE_CREDENTIALS_APPDEV` | GCP service account JSON (Salesforce AppDev tenant) for Sheets access |
| `SLACK_CHANNEL_ID` | Real team channel ID — `C0721HF08ES` — used when `SEND_TO=CHANNEL` |

- `WORKFLOW_MODE` — `test` (adds disclaimer) or `live` (clean message); set per-run via dispatch inputs
- `SEND_TO` — target channel/user ID; set per-run; defaults to Asin's DM if not supplied
- `QUARTER` — for UMP Lock and Budget Transfer; set per-run via dispatch inputs

**Important:** Every workflow yml that uses `SEND_TO=CHANNEL` must also pass `SLACK_CHANNEL_ID` as an env var. Missing this causes messages to fall back to Asin's DM silently.

---

## Slack IDs (MF team)

| Name | Slack ID |
|------|----------|
| Rachel La | U06D4UX21U7 |
| Asin Zahir | U07628FGAN9 |
| Arslan Farooq | U074S9XEE6L |
| Asher Oosterbaan | U072E5U4P6V |
| Andrea Li | U039M2ZENLE |
| Erika Baggs-Geoghegan | U02RWMXJC72 |
| Antoinette Mendoza | U09C1NRJ857 |

---

## iPro POC Slack IDs (UMP Lock CC line)

| Bucket | Slack ID(s) |
|--------|-------------|
| Core Cloud Search | U08PVDE05K2 |
| Cloud Priorities | U08RWMNDNRH (Walker Osterberg) |
| Global Campaigns | U08RWMNDNRH |
| Cloud Priorities & Global Campaigns | U08RWMNDNRH |
| AMER Field Priorities | U0B86B1QN2K |
| EMEA Field Priorities (UKI & CENTRAL) | U090BG92P39, U08SY1KDNPQ, U08PTCS2ARZ |
| EMEA Field Priorities (FRANCE & NORTH & SOUTH) | U090BG92P39, U08SY1KDNPQ, U08PTCS2ARZ |
| APAC Field Priorities | U09GQCW89TP |
| LATAM Field Priorities | U09D6CBDXGS |
| SMB & NextGen Platform Field Priorities Global OUs | U08VC29F8CW, U0B4EN9J3RT, U09B8UK5E8M |
| Public Sector Field Priorities Global OU | U090BG92P39, U08SY1KDNPQ, U08PTCS2ARZ |

Every UMP Lock message CC line also always includes: Andrea Li (`U039M2ZENLE`), Erika Baggs-Geoghegan (`U02RWMXJC72`), Antoinette Mendoza (`U09C1NRJ857`).

---

## GCP / Google Sheets auth

- Service account JSON stored as `GOOGLE_CREDENTIALS_APPDEV` GitHub secret
- Under Salesforce AppDev GCP tenant (migrated from personal Gmail — complete)
- AppDev is dev/test only. Production GCP project requires BaseCamp ticket (pending — lower priority)
- Scopes: `spreadsheets.readonly`

---

## Slack Bot approval status

- Bot posts to internal MF Slack channels — approved and working
- **Phase 2 (posting to 8 ML Slack Connect external channels) is blocked** — requires IT approval via #slack-app-approvals
- Pre-requisites: sandbox testing, video walkthrough, code-level channel restriction confirmed
- Tracked in memory: `project_slack_bot_approval.md`

---

## Open items / next to build

- **UMP Lock POC preview flow** — before live send to iPro channels, bot DMs each MF owner their draft so they can verify numbers and react ✅. Prevents wrong numbers going out unchecked. Manager-requested after Q3 incident where iPro POC used wrong number from the message.
- **Production GCP project** — BaseCamp ticket needed to move off AppDev tenant for production use

---

## Key design decisions

- All workflow Python files are self-contained — no shared utility modules
- `WORKFLOW_MODE=test` and `SEND_TO` are set via GitHub Actions dispatch inputs, not hardcoded
- The console always defaults to test mode on load (never restores last toggle state) to prevent accidental live sends
- Block Kit is used for all Slack messages for consistent formatting
- Column indexes in `ump_lock.py` are constants at the top — update these if the sheet structure changes
- GitHub scheduled workflows run 3-5 hours late — set crons early enough to account for this
- Unicode fullwidth `＃` (U+FF03) used in ATB issue numbers to prevent Slack parsing `#2` as a channel link
- Each UMP Lock quarter is its own Block Kit section block — putting all 5 in one block exceeds Slack's 3000-char limit
