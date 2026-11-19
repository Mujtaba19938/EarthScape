= EarthScape Developer Guide
=- System architecture, data workflows, models and maintenance

[[toc]]

# 1. System overview

EarthScape stores public climate data in HDFS, processes it with Hadoop MapReduce, keeps the results in MongoDB, trains models on them, and serves everything through a Django web application: the public website, the sign-in pages and the dashboard. Apache sits in front, handling HTTPS and balancing requests across two Django instances.

![System architecture](docs/diagrams/architecture.png)

| Part | Technology | Where |
| --- | --- | --- |
| Web server and load balancer | Apache httpd 2.4 | `deploy/apache/httpd.conf` |
| Web application | Python 3.13, Django 5.1, waitress | `web/` |
| Database | MongoDB, database `earthscape` | Windows service |
| Distributed storage and processing | Hadoop 2.9.2 (HDFS, YARN), Hadoop Streaming | `hadoop/`, `deploy/hadoop/` |
| Machine learning | Python 3.7 (Anaconda), scikit-learn, statsmodels | `ml/` |
| Live data | Open-Meteo API, Django command | `web/dashboard/management/commands/collect_live.py`, `web/dashboard/live.py` |
| Pages | Django templates, JavaScript, Tailwind CSS, Chart.js | `web/*/templates/`, `web/*/static/` |
| Operations | Python and PowerShell | `ops/` |

# 2. Repository layout

| Path | Contents |
| --- | --- |
| `web/earthscape/` | Django settings and top-level URLs, `config.py` (reads `web/.env`), MongoDB setup and locks, encryption, test helpers |
| `web/accounts/` | Sign-in, sign-up, sign-in limits, roles, settings, users |
| `web/dashboard/` | Dashboard pages, Hadoop and model views, live data and alerts, the Ask panel, and the `seed` and `collect_live` commands |
| `web/website/` | The public website |
| `web/manage.py`, `web/serve.py` | Django commands; runs one instance with waitress |
| `data/` | Download scripts. Downloaded files go in `data/raw/`, which git ignores |
| `hadoop/run_pipeline.py`, `hadoop/jobs/` | Batch pipeline and the five MapReduce jobs |
| `ml/` | Training script, its tests, notebook, R correlation script |
| `deploy/apache/`, `deploy/hadoop/` | Apache configuration, and a copy of the Hadoop settings used |
| `deploy/tailwind/` | Source for rebuilding `web/dashboard/static/dashboard/tailwind.css` |
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

Both Django instances, the collector and the monitor use the same MongoDB, so no state lives inside one process. Sessions are stored in a shared SQLite file (`web/django.sqlite3`), so a user signed in on one instance is signed in on the other. Failed sign-in counts are in `login_failures`. The `locks` collection (`acquire_lock` in `web/earthscape/db.py`) makes sure only one job, retraining run or poll runs at a time. Each lock expires, so a crashed process can't hold it forever.

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

# 5. Web application

## 5.1 Pages and URLs

Each app has its own `urls.py`, `views.py`, templates and static files. Pages are rendered on the server, and forms post back and reload the page. Every dashboard page needs a signed-in user, and those marked Admin need the Admin role (`login_required` and `admin_required` in `web/accounts/auth.py`).

| Area | URLs |
| --- | --- |
| Website | `/`, `/about/`, `/services/`, `/pricing/`, `/blog/`, `/contact/`, `/newsletter/`, `/privacy-policy/`, `/changelog/`, `/licenses/` |
| Sign-in | `/login/`, `/signup/`, `/logout/` |
| Account | `/dashboard/settings/`, `/dashboard/users/` (Admin) |
| Climate data | `/dashboard/`, `overview/`, `analytics/`, `search/` |
| Live and alerts | `/dashboard/monitor/`, `monitor/poll/` (Admin), `alerts/`, alert rules (Admin) |
| Hadoop and data | `/dashboard/hadoop/`, `hadoop/jobs/<id>/`, `hadoop/run/<name>/` (Admin), `data/`, `data/upload/` (Admin) |
| Models | `/dashboard/ml/`, `ml/retrain/` (Admin) |
| Reports | `/dashboard/reports/`, `reports/download/` (CSV, JSON or GeoJSON) |
| Support | `/dashboard/support/`, `notifications/read/` |
| System | `/api/health` (public), `/dashboard/status/`, `status/maintenance/` (Admin), `architecture/` |

## 5.2 Data model

![Main MongoDB collections](docs/diagrams/data_model.png)

Indexes are created at startup by `ensure_indexes()` in `web/earthscape/db.py`, which also encrypts any older plain email or ticket fields. `health_checks` expire after 90 days, and `login_failures` expire when no longer needed. SQLite holds only Django's sessions.

## 5.3 Security

| Concern | How it's handled | File |
| --- | --- | --- |
| Passwords | bcrypt hashes | `accounts/auth.py` |
| Sessions | Django sessions, 8 hours, HTTP-only cookie, cleared on sign-out | `earthscape/settings.py` |
| Forms | Django CSRF protection on every form | `earthscape/settings.py` |
| Roles | `admin_required` checked on the server for each view | `accounts/auth.py` |
| Sensitive fields | Emails and ticket text encrypted with Fernet (AES) | `earthscape/crypto.py` |
| Finding a user by encrypted email | HMAC-SHA256 blind index | `earthscape/crypto.py` |
| Password guessing | 5 failures per account, 30 per address, in 15 minutes | `accounts/auth.py` |
| Transport | TLS 1.2 or newer, HTTP redirected to HTTPS | `httpd.conf` |
| Browser headers | `nosniff`, `DENY` framing, `same-origin` referrer | `earthscape/settings.py` |

Climate data, names and roles aren't encrypted. HSTS is left off because the certificate is self-signed for localhost.

## 5.4 Settings

Set in `web/.env` or as environment variables. `manage.py seed` generates the keys and the first users, and prints each new password once. `manage.py seed --reset-password admin` (or `analyst`) gives a seed account a new password and prints it once.

| Setting | Purpose |
| --- | --- |
| `SECRET_KEY`, `ENCRYPTION_KEY` | Django's signing key and the field encryption key. Keep a safe copy: backups can't be read without `ENCRYPTION_KEY` |
| `SESSION_HOURS` | How long a sign-in lasts (default 8) |
| `SEED_ADMIN_EMAIL`, `SEED_ANALYST_EMAIL` | First users' email addresses. Their passwords are printed once by `manage.py seed` and never saved |
| `MONGO_URI`, `MONGO_DB` | Database connection |
| `YARN_URL`, `NAMENODE_URL` | Hadoop web addresses |
| `ML_PYTHON` | Python used for training |
| `LIVE_POLL_MINUTES`, `LIVE_BATCH_MINUTES` | Collector timing |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TLS`, `ALERT_EMAIL_TO` | Alert emails |
| `BACKUP_DIR`, `BACKUP_KEEP`, `MONGO_TOOLS_DIR` | Backups |
| `MONITOR_TARGETS` | What the health monitor checks |

# 6. Templates and static files

Each page has its own template, which extends its app's base template: `website/base.html` for the public site, `accounts/base_auth.html` for sign-in, and `dashboard/base.html` for the dashboard, which adds the sidebar and header. To add a dashboard page, write a view in `dashboard/views.py`, add it to `dashboard/urls.py`, add a template that extends `dashboard/base.html`, and add a link to `_sidebar.html`.

JavaScript and CSS live in each app's `static/` folder, with shared libraries in `web/static/vendor/`, so the sign-in pages and dashboard work without internet. Waitress has no static file server, so Django serves them itself. Tailwind is built ahead of time, so after adding a new class, rebuild:

```
npx tailwindcss@3.4.16 -c deploy/tailwind/tailwind.config.js -i deploy/tailwind/input.css -o web/dashboard/static/dashboard/tailwind.css --minify
```

# 7. Operations

## 7.1 Starting and stopping

After a restart:

1. In a normal Command Prompt, run `C:\hadoop\hadoop-2.9.2\sbin\start-dfs.cmd`.
2. In a Command Prompt run as administrator, run `C:\hadoop\hadoop-2.9.2\sbin\start-yarn.cmd`. Without administrator rights, jobs fail with `CreateSymbolicLink error (1314)`.
3. In PowerShell, run `ops\start_all.ps1`. It starts both Django instances, the collector, the monitor and Apache, and skips anything already running.

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

Apache's `balancer://earthscape` sends requests in turn to ports 8000 and 8001, checks `/api/health` every 5 seconds, and retries a failed request on the other instance. To add an instance, start `web\serve.py --port 8002` and add a `BalancerMember` line. The `X-EarthScape-Instance` response header shows which instance answered.

For more data, HDFS and YARN scale by adding DataNodes and NodeManagers. This is standard Hadoop behaviour, but this project has only run it on one node.

# 8. Testing

Run the web tests with `web\.venv\Scripts\python.exe web\manage.py test`. Run `ml\test_train_models.py` with `pytest` using Anaconda's Python. Tests use a separate database (`earthscape_test`), so they don't touch real data.

# 9. Known limitations and next steps

- Polling, not streaming. Kafka or Spark Streaming could replace the collector.
- Uploaded files are stored, but aren't processed until a matching job is written.
- No satellite imagery is processed. NASA POWER provides satellite-derived values as tables.
- Impala is listed in the brief but isn't installed. Queries go through MongoDB.
- Everything runs on one machine, so it can't survive a hardware failure.
- The app has no password reset for other users.
- Rebuilding the pipeline requires downloading about 330 MB, which unpacks to about 2.6 GB.
