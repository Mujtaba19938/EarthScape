= EarthScape Developer Guide
=- System architecture, data workflows, models and maintenance

[[toc]]

# 1. System overview

EarthScape stores public climate data in HDFS, processes it with Hadoop MapReduce, keeps the results in MongoDB, trains models on them, and serves everything through a FastAPI backend and a browser dashboard. Apache sits in front, handling HTTPS and balancing requests across two backend instances.

![System architecture](docs/diagrams/architecture.png)

| Part | Technology | Where |
| --- | --- | --- |
| Web server and load balancer | Apache httpd 2.4 | `deploy/apache/httpd.conf` |
| Backend API | Python 3.13, FastAPI, uvicorn | `backend/app/` |
| Database | MongoDB, database `earthscape` | Windows service |
| Distributed storage and processing | Hadoop 2.9.2 (HDFS, YARN), Hadoop Streaming | `hadoop/`, `deploy/hadoop/` |
| Machine learning | Python 3.7 (Anaconda), scikit-learn, statsmodels | `ml/` |
| Live data | Open-Meteo API, Python service | `backend/collector.py`, `backend/app/live.py` |
| Frontend | HTML, JavaScript, Tailwind CSS, Chart.js | `frontend/` |
| Operations | Python and PowerShell | `ops/` |

# 2. Repository layout

| Path | Contents |
| --- | --- |
| `backend/app/` | API routes, login and roles, database setup, encryption, alerts, live data |
| `backend/tests/` | Automated API tests |
| `backend/seed.py` | First-time setup: writes `backend/.env` and creates the first users |
| `backend/serve.py`, `backend/collector.py` | Runs one backend instance; runs the live data collector |
| `data/` | Download scripts. Downloaded files go in `data/raw/`, which git ignores |
| `hadoop/run_pipeline.py`, `hadoop/jobs/` | Batch pipeline and the five MapReduce jobs |
| `ml/` | Training script, its tests, notebook, R correlation script |
| `frontend/` | Website, sign-in page and dashboard. `vendor/` holds local copies of libraries |
| `deploy/apache/`, `deploy/hadoop/` | Apache configuration, and a copy of the Hadoop settings used |
| `deploy/tailwind/` | Source for rebuilding `frontend/css/dashboard.css` |
| `ops/` | Backup, health monitor, start and stop scripts, scheduled tasks, demo data loader |
| `tableau/` | Export script and CSV files for Tableau |
| `test_data/` | Sample input files, upload test cases, demo results |
| `docs/` | These documents, their sources, screenshots and diagrams |

# 3. Data processing workflows

## 3.1 Batch pipeline

`hadoop/run_pipeline.py` has three stages. Running it with no arguments runs them all, or name one of `load`, `jobs` or `mongo`.

1. **load** unpacks the downloaded files and copies them into HDFS, foldered by source and year.
2. **jobs** submits each Hadoop Streaming job to YARN.
3. **mongo** reads each job's output from HDFS and loads it into MongoDB, recording run times in `pipeline_runs`.

| Job | Input | Output | What it does |
| --- | --- | --- | --- |
| `data_quality` | GHCN-Daily | `data_quality` | Counts valid, missing, failed-QC and malformed readings |
| `regional_monthly` | GHCN-Daily and station list | `regional_monthly` | Monthly means by latitude zone |
| `station_anomalies` | GHCN-Daily | `station_anomalies` | Readings more than 3 standard deviations from that station and month's mean |
| `satellite_zonal` | NASA POWER | `satellite_zonal` | Zonal means of solar radiation and surface temperature |
| `air_quality_monthly` | OpenAQ | `air_quality_monthly` | Monthly mean and maximum for each sensor location |

Bad data is handled in the mappers. Malformed rows, failed quality flags and missing values are skipped and counted, so a bad row never stops a job. The `data_quality` job reports how many were found.

HDFS layout:

```
/climate/raw/ghcn_daily/year_2020, year_2023   partitioned by year
/climate/raw/gistemp, co2, power, openaq       one folder per source
/climate/raw/live                              hourly batches from the collector
/climate/raw/uploads                           files uploaded through the dashboard
/climate/reference                             GHCN station list
/climate/processed                             job output
```

![Flowchart of the batch pipeline](docs/diagrams/flow_pipeline.png)

## 3.2 Live data and alerts

The collector calls `live.poll()` every 15 minutes (`LIVE_POLL_MINUTES`). Each poll fetches 12 cities from Open-Meteo and stores new readings. Then `alert_checks.check_rules()` compares the newest values with every rule. Each hour (`LIVE_BATCH_MINUTES`), unarchived readings are written to HDFS as a CSV batch, which joins the live feed to batch storage.

This is scheduled collection, not a streaming system such as Kafka. A new value is available within one 15-minute cycle.

![Flowchart of live collection and alerts](docs/diagrams/flow_live.png)

## 3.3 Sharing work across instances

Both backend instances, the collector and the monitor use the same MongoDB, so no state lives inside one process. Sign-in tokens are signed and work on either instance. Failed sign-in counts are in `login_failures`. The `locks` collection (`backend/app/locks.py`) makes sure only one job, retraining run or poll runs at a time. Each lock expires, so a crashed process can't hold it forever.

# 4. Machine learning models

`ml/train_models.py` runs in Anaconda's Python. A retrain from the dashboard runs it as a separate process, and each run saves scores to `ml_runs` and model files to `ml/saved_models/`. Because a run reads whatever is currently in MongoDB and the data files, retraining refines the models on the latest data.

## 4.1 Trend prediction

For each of nine series (global and eight latitude zones) of NASA GISTEMP data:

1. Several methods compete: last value (the baseline), linear trends over recent windows, and Holt exponential smoothing.
2. They are compared by backtesting from 1950 onward, using only what was known at each point, predicting 10 years ahead.
3. The winner is scored once on the final, unseen 10 years (2016-2025). The baseline can't be chosen, so a forecast always shows a trend.
4. The range is taken from the method's own past errors, and checked against those 10 years.

## 4.2 Anomaly detection

An Isolation Forest on daily OpenAQ readings, with each day's values expressed as z-scores against that sensor's previous 30 days. This stops naturally dirty locations from dominating. Nobody has labelled true anomalies, so it's tested by injecting artificial spikes into held-out data and measuring how many are found.

## 4.3 Correlation analysis

Pearson and Spearman correlations between variables. Two rising series always correlate strongly, so CO₂ and temperature are compared both as raw values and as year-to-year changes. `ml/correlation_analysis.R` repeats the analysis in R, and hasn't been run because R wasn't installed.

![Flowchart of model training](docs/diagrams/flow_training.png)

# 5. Backend

## 5.1 API

Interactive reference: `/docs` on a running backend. All routes need a valid token unless marked as public, and those marked Admin need the Admin role.

| Area | Routes |
| --- | --- |
| Sign-in | `POST /api/auth/login` (public), `logout`, `GET` and `PATCH /api/auth/me`, `POST /api/auth/password` |
| Users | `GET /api/users`, `POST /api/users` (Admin), `PATCH /api/users/{id}` (Admin) |
| Climate data | `GET /api/overview`, `/api/climate/global`, `zonal`, `monthly`, `zones`, `/api/anomalies`, `/api/air-quality`, `/api/quality` |
| Reports | `GET /api/reports`, `/api/reports/{id}?format=csv, json or geojson` |
| Cluster | `GET /api/cluster`, `/api/jobs`, `/api/jobs/{id}`, `POST /api/jobs/{name}/run` (Admin) |
| Datasets | `GET /api/datasets`, `POST /api/datasets` (Admin) |
| Live | `GET /api/live/latest`, `/api/live/history`, `POST /api/live/poll` (Admin) |
| Models | `GET /api/ml/summary`, `forecast`, `anomalies`, `correlations`, `POST /api/ml/retrain` (Admin) |
| Alerts | `GET /api/alerts`, `PATCH /api/alerts/{id}`, `GET /api/alert-metrics`, `/api/alert-rules`, `POST` and `DELETE` rules (Admin) |
| Support | `GET` and `POST /api/tickets`, `PATCH /api/tickets/{id}` (Admin), `GET /api/notifications`, `POST /api/notifications/read` |
| System | `GET /api/health` (public), `/api/status`, `GET /api/maintenance` (public), `PUT /api/maintenance` (Admin) |

## 5.2 Data model

![Main MongoDB collections](docs/diagrams/data_model.png)

Indexes are created at startup by `ensure_indexes()` in `backend/app/db.py`, which also encrypts any older plain email or ticket fields. `health_checks` expire after 90 days, and `login_failures` and `revoked_tokens` expire when no longer needed.

## 5.3 Security

| Concern | How it's handled | File |
| --- | --- | --- |
| Passwords | bcrypt hashes | `security.py` |
| Sessions | Signed JWT, 8 hours, revoked on sign-out | `security.py` |
| Roles | `require_admin` checked on the server for each route | `security.py` |
| Sensitive fields | Emails and ticket text encrypted with Fernet (AES) | `field_crypto.py` |
| Finding a user by encrypted email | HMAC-SHA256 blind index | `field_crypto.py` |
| Password guessing | 5 failures per account, 30 per address, in 15 minutes | `login_limit.py` |
| Transport | TLS 1.2 or newer, HTTP redirected to HTTPS | `httpd.conf` |
| Browser headers | `nosniff`, `DENY` framing, `same-origin` referrer | `main.py` |

Climate data, names and roles aren't encrypted. HSTS is left off because the certificate is self-signed for localhost.

## 5.4 Settings

Set in `backend/.env` or as environment variables. `seed.py` generates the keys and the first users' details.

| Setting | Purpose |
| --- | --- |
| `JWT_SECRET`, `ENCRYPTION_KEY` | Signing and encryption keys. Keep a safe copy: backups can't be read without `ENCRYPTION_KEY` |
| `SEED_ADMIN_EMAIL`, `SEED_ADMIN_PASSWORD`, `SEED_ANALYST_*` | First users' details |
| `MONGO_URI`, `MONGO_DB` | Database connection |
| `YARN_URL`, `NAMENODE_URL` | Hadoop web addresses |
| `ML_PYTHON` | Python used for training |
| `LIVE_POLL_MINUTES`, `LIVE_BATCH_MINUTES` | Collector timing |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TLS`, `ALERT_EMAIL_TO` | Alert emails |
| `BACKUP_DIR`, `BACKUP_KEEP`, `MONGO_TOOLS_DIR` | Backups |
| `MONITOR_TARGETS` | What the health monitor checks |

# 6. Frontend

`frontend/dashboard.html` holds every page as a `section`, and `frontend/js/earthscape.js` shows one at a time, fetches its data and draws its charts. To add a page, add a `section id="view-name"`, add it to `NAV` and give it a render function.

The sign-in page and dashboard store their libraries locally, so they work without internet. The public website is the starting template, and loads some images and fonts from the internet. Its pages check `frontend/css/harvestra.webflow.shared.css` and `frontend/js/` against fixed checksums, so `.gitattributes` stops Git changing their line endings. Tailwind is built ahead of time, so after adding a new class, rebuild:

```
npx tailwindcss@3.4.16 -c deploy/tailwind/tailwind.config.js -i deploy/tailwind/input.css -o frontend/css/dashboard.css --minify
```

# 7. Operations

## 7.1 Starting and stopping

After a restart:

1. In a normal Command Prompt, run `C:\hadoop\hadoop-2.9.2\sbin\start-dfs.cmd`.
2. In a Command Prompt run as administrator, run `C:\hadoop\hadoop-2.9.2\sbin\start-yarn.cmd`. Without administrator rights, jobs fail with `CreateSymbolicLink error (1314)`.
3. In PowerShell, run `ops\start_all.ps1`. It starts both backends, the collector, the monitor and Apache, and skips anything already running.

Stop them with `ops\stop_all.ps1`. Service output goes to `logs/`, and Apache's to `logs/apache/`.

## 7.2 Monitoring

`ops/health_monitor.py --loop 60` checks each target every minute, writes to `health_checks` and `logs/health.log`, and sends a notification when something goes down or recovers. The System Status page turns those checks into availability figures, and shows job and training times. YARN and HDFS have their own pages at ports 8088 and 50070.

## 7.3 Backup and restore

`ops/backup.py` dumps MongoDB, restores the dump into a separate database to prove it works, copies the HDFS data that can't be downloaded again, and keeps the last seven backups. A failure raises a notification. `ops/install_scheduled_tasks.ps1` schedules it for 2 am daily.

To restore a backup:

```
"C:\Program Files\MongoDB\Tools\100\bin\mongorestore" --gzip --drop --dir=backups\<folder>\mongo
```

`ENCRYPTION_KEY` isn't in the backup, because storing the key with the data would defeat the encryption. Keep it separately.

## 7.4 Load balancing and scaling

Apache's `balancer://earthscape` sends requests in turn to ports 8000 and 8001, checks `/api/health` every 5 seconds, and retries a failed request on the other instance. To add an instance, start `backend\serve.py --port 8002` and add a `BalancerMember` line. The `X-EarthScape-Instance` response header shows which instance answered.

For more data, HDFS and YARN scale by adding DataNodes and NodeManagers. This is standard Hadoop behaviour, but this project has only run it on one node.

# 8. Testing

Run the backend tests with `pytest` in `backend`, using the backend's Python. Run `ml\test_train_models.py` with `pytest` using Anaconda's Python. Tests use a separate database, so they don't touch real data.

# 9. Known limitations and next steps

- Polling, not streaming. Kafka or Spark Streaming could replace the collector.
- Uploaded files are stored, but aren't processed until a matching job is written.
- No satellite imagery is processed. NASA POWER provides satellite-derived values as tables.
- Impala is listed in the brief but isn't installed. Queries go through MongoDB.
- Everything runs on one machine, so it can't survive a hardware failure.
- The app has no password reset for other users.
- Rebuilding the pipeline requires downloading about 330 MB, which unpacks to about 2.6 GB.
