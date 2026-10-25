# ClearTrace AML Investigation

A local-first demonstration application for transaction risk triage. ClearTrace combines graph relationships, temporal behavior, Isolation Forest anomaly scores, and transparent rules to help prioritize review. **A risk score is not proof or a confirmed label of money laundering.** This demo is not a production compliance decision system.

## Stack

- React 19, Vite 7, JavaScript, Tailwind CSS 4, Recharts, Cytoscape.js
- FastAPI, SQLAlchemy 2, Pandas, NumPy, scikit-learn, NetworkX
- SQLite database stored locally in `aml_detection.db`

Node 24 satisfies Vite 7's Node requirement. Python 3.13 is supported by the pinned NumPy, Pandas, and scikit-learn versions. Dependencies are pinned in `backend/requirements.txt`; the frontend manifest/lockfile pins the JavaScript tree.

## Run on Windows PowerShell

Open two terminals in this project directory.

### Terminal 1 — backend

```powershell
Set-Location "C:\Users\Tripad\Desktop\ACD CBP"
& "C:\Python313\python.exe" -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
$env:DATABASE_URL = "sqlite:///./aml_detection.db"
$env:API_CORS_ORIGINS = "http://localhost:5173"
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir backend --reload
```

Open `http://localhost:8000/docs` for the API. The SQLite file is created in the project root when the API starts.

### Terminal 2 — frontend

```powershell
Set-Location "C:\Users\Tripad\Desktop\ACD CBP"
npm.cmd install
npm.cmd run dev
```

Open `http://localhost:5173` for the dashboard. Use **Load demo data** to create synthetic transactions covering circular paths, transfer bursts, and low-value sequences. Use **Import CSV** to upload a UTF-8 CSV.

The API URL defaults to `http://localhost:8000/api`. To override it, create a root `.env.local` with `VITE_API_URL=http://localhost:8000/api` and restart Vite.

## CSV format

Required mapped fields: timestamp, sender account, receiver account and non-negative amount. Transaction ID is optional; when missing, ClearTrace creates a stable row identifier and retains the original CSV row. Optional mapped fields include currency, channel and dataset label. Map currency whenever the source has it. Currency values must have the three-letter ISO 4217 code shape; if omitted or blank, that row is explicitly marked currency-unknown. Existing transaction IDs are skipped; duplicate IDs within the file and invalid rows are reported in the import summary.

During import, choose **This import only** or **All imported datasets together**. Combined analysis rescans imported transactions in timestamp order so graph paths and temporal evidence may span imports. Synthetic local demo rows remain intact and are excluded from the imported-only combined scope. Original source IDs, import provenance, labels, and review statuses are retained; repeated uploads are deduplicated.

Amounts are never converted or summed across currencies. Dashboard totals and daily volume are shown only when every transaction has consistent known currency metadata; otherwise totals are unavailable, a warning is displayed, and known values are listed separately by currency. No exchange rates or conversion timestamps are supported. USD rule thresholds apply only to known USD transactions. Isolation Forest uses currency-relative account amount features, or source-dataset-scoped relative values when currency metadata is absent; it does not aggregate money or apply USD thresholds to unknown units.

## IBM AMLSim public data

### Importing the prepared 50,000-row simulation-step sample

The prepared sample lives at `data/processed/transactions_sample_50000.csv`. In ClearTrace choose **Import CSV**, select this file, use the inferred field mappings below, set **Timestamp meaning** to **Integer simulation step**, and choose **This import only** for the first analysis. For repeatable idempotent imports, keep the dataset name exactly `IBM AMLSim 50K sample`.

| ClearTrace field | AMLSim column |
| --- | --- |
| Source transaction ID | `TX_ID` |
| Origin account | `SENDER_ACCOUNT_ID` |
| Destination account | `RECEIVER_ACCOUNT_ID` |
| Amount | `TX_AMOUNT` |
| Payment channel / type | `TX_TYPE` |
| Dataset reference label | `IS_FRAUD` (`True` positive, `False` negative) |
| Timestamp / simulation step | `TIMESTAMP` |
| Source alert ID | `ALERT_ID` |

Use evaluation labels exactly as `True` and `False` in the Dataset & evaluation page. This reports metrics only for explicitly mapped source labels in the chronological holdout; the displayed result is identified as synthetic AMLSim evaluation and does not establish laundering. Rows with the same simulation step are tied: ClearTrace preserves the original integer and treats transactions within a step as simultaneous temporal evidence. Simulation-step windows are measured in steps with configurable defaults; no real clock duration is assumed.

The API equivalent is `POST /api/transactions/upload` with multipart fields `file`, `dataset_name=IBM AMLSim 50K sample`, `timestamp_kind=simulation_step`, `analysis_scope=import`, `mapping={}` (header inference handles the columns), and `detection_config={}`. The upload endpoint reads the prepared ~50,000-row sample in memory; the 595 MB original file is not suitable for browser upload and should not be imported this way. Repeating the same dataset name and source IDs safely skips previously imported rows. This is additive and preserves the original local demo transactions.

To calculate metrics through the API after import, open `http://localhost:8000/api/evaluation?labels_verified=true&positive_label=True&negative_label=False`. The query parameter is an explicit declaration that these source labels are the reference classes. On the prepared 50,000-row sample, the pre-improvement fixed-40 run evaluated 15,018 holdout rows (32 positive, 14,986 negative): TP 0, FP 4, TN 14,982, FN 32; precision/recall/F1 0 and FPR 0.000267. After feature and validation changes, the validation-selected cutoff was the all-negative sentinel 101 because none of six validation positives was detected: TP 0, FP 0, TN 14,986, FN 32; precision/recall/F1 0 and FPR 0. The fixed-40 comparison after the changes had TP 0, FP 51, TN 14,935, FN 32 (FPR 0.003403). Thus the changes did not improve positive-class detection; the all-negative fallback only avoids false alarms. Results are synthetic, highly imbalanced (0.213% positive), and not real-world detection performance.

Obtain AMLSim code and generated/example CSV data from [IBM/AMLSim](https://github.com/IBM/AMLSim) and its [example data download guide](https://github.com/IBM/AMLSim/wiki/Download-Example-Data-Set). ClearTrace does not download data automatically. AMLSim data is synthetic and its labels describe the simulator's generated patterns, not real-world findings.

In the app, choose **Import CSV**, select a transaction CSV, review the detected headers and mappings, then validate and import. The importer recognizes common AMLSim names such as `Timestamp`, `From Bank`, repeated `Account` columns, `To Bank`, `Amount Paid`/`Amount Received`, `Payment Currency`, `Payment Format`, and `Is Laundering`. Repeated `Account` headers are kept distinct; bank identifiers are joined to mapped account identifiers when provided. Confirm the preview before import. Other schemas can be imported by selecting a source column for each field. Labels are stored as `Dataset reference` provenance and never become detector-generated alerts or features.

For the HTTP API, first inspect a file with `POST /api/transactions/inspect` (multipart field `file`), then submit `POST /api/transactions/upload` with `file`, optional `mapping` JSON (canonical field to inspected column), `dataset_name`, `analysis_scope=import|all_imported`, and optional `detection_config` JSON. Example mapping:

```json
{"transaction_id":"tx_id","timestamp":"timestamp","sender":"from_account","receiver":"to_account","amount":"amount","currency":"currency","label":"is_laundering"}
```

Rows that fail validation are skipped and returned with their CSV row numbers and error messages. Internal IDs namespace source IDs by dataset; the exact source transaction ID is retained separately. When no source ID exists, a stable internal ID is generated from the file name, row number and row contents. Original mapped labels, account/bank values, timestamp, amount and the original row are retained.

## Detection and evaluation

- The directed graph is updated chronologically; tied rows are analyzed as one graph slice. Bounded return paths mark cycle evidence, and configurable incoming-account fan-in is scored separately with related accounts and transaction evidence.
- Temporal indicators use earlier simulation steps plus all tied transactions within the current step (or strictly earlier calendar timestamps): rapid repeated outgoing transfers, rapid incoming-to-outgoing fund movement, repeated small USD transfers inside a configurable window, short-window bursts and same-step/same-day activity.
- Isolation Forest fits on the first 56% training segment, with a following 14% validation segment and final 30% holdout (simulation steps stay grouped). Features include currency-scoped prior account amounts or, when a source has no currency column, source-dataset-scoped relative amounts, account activity counts, and calendar time-of-day. Source-unit amount features are relative behavior indicators, not converted currency values or USD rules. The Isolation Forest is fit only on training features and scores validation and holdout rows; calibration uses training scores. Validation labels select an evaluation cutoff under a default 1% validation false-positive-rate cap; if validation detects no positives, evaluation uses an all-negative cutoff. This evaluation cutoff does not modify the configured live alert threshold. Validation and holdout flags are stored separately.
- Risk is a weighted, normalized combination of rule, graph, temporal and anomaly signals. Import form/API `detection_config` can set time windows, transfer thresholds, alert threshold and signal weights. USD amount thresholds are not foreign-exchange normalized.
- Every generated alert stores the explanation, contributing signal keys, related accounts and supporting transaction IDs. Review status is independent from dataset-provided reference labels.
- The **Dataset & evaluation** screen and `GET /api/evaluation` require the caller to confirm labels and explicitly enter the exact positive and negative source-label values. Other strings are ignored; detector alerts are never used as reference labels. Metrics use only verified, explicitly mapped labels in the chronological holdout and report evaluated, positive and negative sample counts plus class proportions. Empty sets and single-class sets return a reason rather than misleading rates. Public synthetic benchmark metrics remain illustrative, not production estimates.

The optional IBM `alerts.csv` sidecar matches all 82 positive sample transaction IDs and source alert IDs; the matched annotations identify 39 cycle and 43 fan-in rows. Those annotations are reported as external dataset evidence and are never detector inputs or evaluation predictions, because using them would leak the source alert result. Automated tests cover tied-step cycles/fan-in evidence, simulation import, validation/holdout separation, exact labels, metrics, and existing API workflows.

## API endpoints

- `GET /api/health`, `GET /api/dashboard`
- `GET /api/transactions?q=&severity=&status=`
- `POST /api/transactions/upload` (multipart CSV; `analysis_scope=import|all_imported`)
- `GET /api/evaluation?labels_verified=true&positive_label=1&negative_label=0` (example labels must match the source exactly)
- `POST /api/demo/load`
- `GET /api/alerts`, `PATCH /api/alerts/{transaction_id}/status?status=reviewing`
- `GET /api/graph?account=`

## Tests

After installing backend requirements, from the project root run:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest backend\tests -q
```

The backend creates tables on startup and performs additive SQLite column upgrades while preserving existing rows. PostgreSQL deployment, exchange-rate conversion, authentication, cloud deployment, and background processing are unsupported in this local stage.

## Detection notes and limitations

- Graph checks find directed cycles up to six accounts and unusually connected sender/receiver relationships.
- Temporal checks identify rapid sequences, repeated small transfers, pass-through movement, and bursts from prior history only.
- Isolation Forest is trained chronologically, with separate validation and later holdout segments; simulation steps remain grouped at each boundary. Reanalysis after additional imports can change the chronological split, scores, and eligibility flags.
- Rule, graph, temporal, and anomaly component scores remain separately visible in investigation details.
- Demo data is synthetic. Imported labels remain explicitly dataset-provided. Detection thresholds are demonstrative, not calibrated for real-world financial decisions. Alerts do not prove money laundering.
- Authentication, authorization, analyst audit logs, calibrated thresholds, migrations, background processing, and production security controls are outside this first local demo.
