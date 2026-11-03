= EarthScape Climate Agency
=- Big data climate analysis platform: eProject report

[[toc]]

# 1. Problem definition

Climate change is a global challenge. Rising greenhouse gas emissions, deforestation and changes in land use are shifting climate patterns and making severe weather more frequent.

The EarthScape Climate Agency monitors these changes. It collects large amounts of data from satellites, weather stations and environmental sensors, but this data is too large and too varied to study by hand. The agency needs a system to store, process, analyse and present it, so that staff can make informed decisions.

## 1.1 Objectives

- Store large climate datasets reliably in Hadoop HDFS.
- Process them in parallel with MapReduce.
- Combine historical records with live data.
- Predict trends, and detect anomalies and correlations with machine learning.
- Present results in interactive dashboards.
- Alert people when readings cross configured limits.
- Protect the system with sign-in, roles and encryption.

## 1.2 Users

| User | Needs |
| --- | --- |
| Administrator | Manage users, data, jobs, models, alert rules and support |
| Climate analyst | Explore data, read forecasts, respond to alerts, download reports, ask for help |

# 2. Requirements and how they were met

Status key: **Met** means it was built and tested. **Partly** means it works within a stated limit. **Not met** means it wasn't built.

## 2.1 Functional requirements

| Requirement | Status | How it was met |
| --- | --- | --- |
| Authentication and roles | Met | Sign-in with signed tokens. Admin and Analyst roles are enforced on the server |
| Ingest diverse datasets | Partly | Station, sensor, gridded satellite-derived and tabular data. **Satellite imagery isn't processed**; imagery files can be uploaded and stored only |
| Historical and real-time sources | Partly | Historical files, plus live data polled every 15 minutes |
| Common climate formats | Partly | Uploads accept NetCDF, GeoTIFF, HDF5, Parquet, CSV and GRIB2 after a content check. Only CSV and JSON are processed |
| HDFS storage | Met | 2.5 GB of station data plus other sources, partitioned by source and year |
| MapReduce processing | Met | Five jobs on YARN. Run on one node, so parallel across tasks rather than across machines |
| Patterns, anomalies, correlations | Met | Zonal and monthly patterns, 48,715 flagged station readings, 12 correlation pairs |
| Missing or incomplete data | Met | Bad rows are skipped and counted, and shown on the data quality table |
| Real-time processing | Partly | Scheduled polling, not a streaming system. Hourly batches join live data to HDFS |
| ML models | Met | Forecasting, anomaly detection and correlation, retrained on demand |
| Interactive dashboards | Met | 14 pages, with region, variable, city and time span choices, and exports |
| Notifications and alerts | Met | Configurable rules, in-app notifications. Email is built, but only tested against a simulated mail server |
| Feedback and support | Met | Tickets with categories and status |

## 2.2 Non-functional requirements

| Requirement | Status | How it was met |
| --- | --- | --- |
| Performance monitoring | Met | Status page, job and training times, health checks |
| Optimisation | Partly | Database indexes, and results computed ahead of time so pages load fast. No formal load test |
| Encryption | Met | HTTPS with TLS 1.2 or newer. Passwords hashed. Emails and tickets encrypted. Climate data isn't encrypted, as it's public |
| Data protection standards | Partly | Follows common practice. Not audited or certified |
| 99% uptime | Partly | Availability is measured and maintenance notices exist. **One computer can't prove this** |
| Automated backups | Partly | Backup script with a restore check works. The daily schedule is installed separately from an administrator prompt |
| Horizontal scaling and load balancing | Partly | Two backends behind Apache, tested with failover. **Real multi-machine scaling hasn't been tested** |
| Environmental data standards | Partly | ISO 8601 dates and GeoJSON exports. No formal compliance claimed |
| Documentation | Met | User guide, developer guide, this report and a video script |

## 2.3 Software listed in the brief

| Software | Used? | Notes |
| --- | --- | --- |
| Jupyter (Anaconda) | Yes | `ml/climate_models.ipynb` |
| RStudio | Script only | `ml/correlation_analysis.R` is written but hasn't been run |
| VS Code or PyCharm | Yes | Development |
| MongoDB Compass and Shell | Yes | Results database |
| Hadoop, HDFS, Apache | Yes | Hadoop 2.9.2, Apache 2.4.69 |
| Tableau | Data ready | CSV exports and build steps are ready. The workbook is built in Tableau itself |
| Impala | No | Not installed. Queries are answered through MongoDB |

# 3. Design specifications

## 3.1 Architecture

The system has three layers. Storage and processing are Hadoop. Results and application data are in MongoDB. The presentation layer is a FastAPI backend and a browser dashboard behind Apache.

![System architecture](docs/diagrams/architecture.png)

## 3.2 Key design decisions

| Decision | Reason |
| --- | --- |
| Hadoop Streaming with Python | The same language as the rest of the project, and each job can be tested without a cluster |
| Copy results to MongoDB | Dashboard pages need answers in milliseconds, while MapReduce takes minutes |
| Store state only in MongoDB | Any backend instance can answer any request, which makes load balancing possible |
| Compare forecasts against a baseline | A model is only useful if it beats simply repeating the last value |
| Check backups by restoring them | A backup that has never been restored isn't proven |
| Label estimates and limits on screen | People should know how far to trust what they see |

## 3.3 Data sources

| Source | Provides | Format | Size |
| --- | --- | --- | --- |
| NOAA GHCN-Daily, 2020 and 2023 | Weather station records | CSV (gzip) | 2.6 GB unpacked |
| NASA GISTEMP v4 | Temperature anomalies since 1880 | CSV | Small |
| NOAA Mauna Loa | Yearly CO₂ since 1959 | CSV | Small |
| NASA POWER | Satellite-derived solar radiation, surface temperature | JSON API, stored as CSV | Small |
| OpenAQ, 2023 | Air quality sensor readings | CSV (gzip) | 15 MB |
| Open-Meteo | Live weather and air quality estimates for 12 cities | JSON API | Grows over time |

## 3.4 Data model

MongoDB holds the results. Collections are listed by purpose below, and the Developer Guide describes each in more depth.

![Main MongoDB collections](docs/diagrams/data_model.png)

## 3.5 User interface

The public website is the template the project started from, and its Dashboard button leads to sign-in. The dashboard has a side menu with 14 pages. Green and gold are the agency's colours. Colour never carries meaning alone: every status has a text label. Screens adapt down to phone width.

![Executive Dashboard](docs/screenshots/dashboard.png)

[[pagebreak]]

# 4. Diagrams

## 4.1 Data flow diagrams

![Level 0: the system and the people and services around it](docs/diagrams/dfd_level0.png)

![Level 1: the main processes and data stores](docs/diagrams/dfd_level1.png)

## 4.2 Flowcharts

![Signing in](docs/diagrams/flow_sign_in.png)

![Batch pipeline](docs/diagrams/flow_pipeline.png)

![Live collection and alerts](docs/diagrams/flow_live.png)

![Model training](docs/diagrams/flow_training.png)

# 5. Results

All figures below come from running the system on the project computer.

## 5.1 MapReduce

| Measure | Result |
| --- | --- |
| Station data in HDFS | 2.5 GB |
| Flagged unusual station readings | 48,715 |
| Longest job in the latest run (`station_anomalies`) | About 97 seconds |
| Shortest job (`satellite_zonal`) | About 26 seconds |

These flagged readings use a short baseline of only two years, which the dashboard states.

## 5.2 Trend prediction

Each method was chosen on data before 2016, then scored once on 2016-2025. RMSE is the typical error in °C, and lower is better. "Baseline" means repeating the last known value.

| Series | Method chosen | RMSE | Baseline RMSE | Beats baseline | Range coverage |
| --- | --- | --- | --- | --- | --- |
| Global | Linear, 30 years | 0.189 | 0.188 | No | 80% |
| 64N-90N | Holt | 0.654 | 0.726 | Yes | 90% |
| 44N-64N | Linear, 30 years | 0.316 | 0.298 | No | 100% |
| 24N-44N | Linear, 30 years | 0.297 | 0.337 | Yes | 100% |
| EQU-24N | Linear, 30 years | 0.213 | 0.188 | No | 90% |
| 24S-EQU | Linear, 30 years | 0.238 | 0.232 | No | 80% |
| 44S-24S | Linear, 50 years | 0.094 | 0.114 | Yes | 100% |
| 64S-44S | Holt | 0.222 | 0.231 | Yes | 90% |
| 90S-64S | Holt | 0.369 | 1.182 | Yes | 100% |

The chosen method beat the baseline in five of nine series. In the other four, including the global series, it did slightly worse. Recent warming was unusually fast and sudden, and a 10-year test contains few data points, so this shows the limit of a purely statistical forecast. The models were also adjusted during development after seeing these test results, so the test years aren't perfectly independent.

## 5.3 Anomaly detection

| Measure | Result |
| --- | --- |
| Days scored, across 24 sensors | 6,872 |
| Days flagged | 69 |
| Normal test days wrongly flagged | 0.59% |
| Artificial spikes found: 3 times normal size | 1% |
| Artificial spikes found: 6 times normal size | 35% |
| Artificial spikes found: 10 times normal size | 100% |

The model reliably finds large spikes, and misses small ones. Artificial spikes only estimate real performance, because nobody has labelled which days were truly abnormal.

## 5.4 Correlation

| Pair | Compared as | Pearson r |
| --- | --- | --- |
| CO₂ and global temperature anomaly | Yearly values | 0.967 |
| CO₂ and global temperature anomaly | Year-to-year changes | 0.316 |
| Station daily high and satellite-model surface temperature, 44N-64N | Monthly values | 0.990 |
| Solar radiation and surface temperature, EQU-24N | Monthly values | 0.032 |

The first two rows show why both are compared: two rising series will correlate strongly, whether or not they're linked. Correlation doesn't show cause.

## 5.5 Reliability and load balancing

| Test | Result |
| --- | --- |
| Requests spread across two instances | 10 and 10 of 20 |
| Requests after stopping one instance during traffic | 92 sent, 0 failed |
| Stopped instance after restarting | Back to receiving requests, 10 and 10 of 20 |
| Sign-in token from one instance used on the other | Accepted |
| Failed sign-ins alternating between instances | Blocked on the 6th attempt |
| Second retrain request while one is running | Refused (409) |
| Backup | 10.5 seconds, 3.3 MB |
| Restore check | 50,713 rows restored and matched |

These show the mechanisms work. They don't show 99% uptime over time, or that the design scales across machines, as everything ran on one computer.

# 6. Test data and testing

## 6.1 Test data used

| Location | Contents |
| --- | --- |
| `test_data/samples/` | The first 2,000 rows of each station and sensor file, plus the full GISTEMP and CO₂ files |
| `test_data/upload_cases/` | A valid CSV, and a text file named `.nc` that must be refused |
| `test_data/demo_results.archive.gz` | Pipeline and model results, with no user accounts |
| `data/raw/` in the zip | Small source files: GISTEMP, CO₂, NASA POWER, OpenAQ |
| Fixtures in `backend/tests/` | Generated test users, readings and rules in a separate test database |

The full GHCN-Daily files are too large for the zip, and `data/download_data.sh` downloads them.

## 6.2 Automated tests

| Suite | Covers | Result |
| --- | --- | --- |
| `backend/tests/test_api.py` | Sign-in, roles, data routes, reports | All pass |
| `backend/tests/test_live.py` | Collector, alert rules, email sending (simulated mail server) | All pass |
| `backend/tests/test_ml.py` | Model routes, retraining | All pass |
| `backend/tests/test_resilience.py` | Encryption, locks, sign-in limits, backups, monitoring, status | All pass |
| `ml/test_train_models.py` | Forecast methods, anomaly detection, correlation | All pass |

In total, 109 backend tests and 14 model tests pass.

## 6.3 Test cases

| No. | Test | Steps | Expected | Result |
| --- | --- | --- | --- | --- |
| 1 | Correct sign-in | Sign in as Analyst | Dashboard opens | Pass |
| 2 | Wrong password | Enter a wrong password | "Incorrect email or password" | Pass |
| 3 | Sign-in limit | 6 failed attempts on one account | Blocked on the 6th (429) | Pass |
| 4 | Role limit | As Analyst, change maintenance notice through the API | Refused (403) | Pass |
| 5 | Admin-only controls | Open System Status as Analyst | Maintenance form hidden | Pass |
| 6 | Run a job | Start a MapReduce job as Admin | Job appears, and results update | Pass |
| 7 | Upload valid file | Upload `valid_readings.csv` | Listed in HDFS datasets | Pass |
| 8 | Upload false file | Upload `invalid_not_really.nc` | Refused | Pass |
| 9 | Live poll | Press Check now | Readings update | Pass |
| 10 | Alert opens and closes | Reading crosses a rule, then falls | Alert opens, then closes itself | Pass |
| 11 | Retrain | Press Retrain models | New version appears in history | Pass |
| 12 | Report download | Download CSV, JSON and GeoJSON | Files download correctly | Pass |
| 13 | Support ticket | Submit a ticket | Stored encrypted, Admin can read it | Pass |
| 14 | HTTPS | Open `http://localhost` | Redirects to HTTPS | Pass |
| 15 | Failover | Stop one backend during traffic | No failed requests | Pass |
| 16 | Backup | Run `ops\backup.py` | Backup restored and matched | Pass |
| 17 | Offline use | Block all outside addresses and open the sign-in page and every dashboard page | Pages load with no errors | Pass |
| 18 | Phone width | Open sign-in and status pages at 375 px | No sideways scrolling | Pass |

# 7. Installation

See `ReadMe.doc` for the shortest route. The full steps are below.

## 7.1 Software needed

| Software | Version used | Needed for |
| --- | --- | --- |
| Windows | 11 (10 or newer) | Everything |
| Python | 3.13 | Backend |
| MongoDB and Database Tools | Service, Tools 100 | Database, backup |
| Anaconda | Python 3.7 | Models, notebook, diagrams |
| Java JDK | 1.8.0_202 | Hadoop |
| Hadoop | 2.9.2, with Windows native binaries | Pipeline, jobs page |
| Apache httpd (Apache Lounge) | 2.4.69, Win64 | HTTPS, load balancing |
| Visual C++ Redistributable | Recent x64 | Apache |
| Tableau Public, RStudio | Latest | Optional |

## 7.2 Website and database

Run these in PowerShell, from the project folder. Use a folder path without spaces.

```
py -3.13 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
backend\.venv\Scripts\python.exe backend\seed.py
backend\.venv\Scripts\python.exe ops\load_demo_data.py
backend\.venv\Scripts\python.exe backend\serve.py --port 8000
```

Open `http://localhost:8000`. The sign-in details are in `backend\.env`.

## 7.3 HTTPS and load balancing

1. Install the Visual C++ Redistributable.
2. Unzip Apache so that `C:\Apache24\bin\httpd.exe` exists.
3. Run `ops\make_certificate.ps1`, then `ops\start_all.ps1`.
4. Open `https://localhost`, and accept the certificate warning.
5. From an administrator PowerShell, run `ops\install_scheduled_tasks.ps1` once for daily backups and automatic startup.

## 7.4 Hadoop and the full pipeline

These steps aren't needed to see results, as the demo data covers them.

1. Install Java 8, and Hadoop at `C:\hadoop\hadoop-2.9.2`, with its Windows `winutils.exe` and `hadoop.dll` in `bin`.
2. Copy the files from `deploy\hadoop` into Hadoop's `etc\hadoop`, and change the folder paths if needed.
3. Run `hdfs namenode -format` once.
4. Start HDFS in a normal Command Prompt with `sbin\start-dfs.cmd`.
5. Start YARN in an administrator Command Prompt with `sbin\start-yarn.cmd`.
6. Download the data with `bash data/download_data.sh` and `python data/fetch_api_data.py`.
7. Set `STREAMING_PYTHON` to a Python path without spaces, then run `hadoop\run_pipeline.py` with Anaconda's Python.
8. Run `ml\train_models.py` with Anaconda's Python, or press **Retrain models**.

# 8. Conclusion and future work

The platform stores and processes real climate data with Hadoop, adds live data, predicts trends, detects anomalies and presents everything in a secure, role-based dashboard with alerts and support.

Its main limits are that it runs on one computer, polls live data rather than streaming it, and doesn't process satellite imagery. Next steps would be a real multi-node cluster, Kafka for streaming, imagery processing with Spark, and an Impala query layer.

# 9. Source code

The source is in this zip and at https://github.com/Mujtaba19938/EarthScape. The Developer Guide explains its structure.
