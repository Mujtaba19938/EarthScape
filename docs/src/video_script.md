= EarthScape Video Script
=- A demonstration of about 6 minutes

# Before recording

1. Start HDFS, and start YARN from an administrator prompt.
2. Run `ops\start_all.ps1`, and open `https://localhost`.
3. Accept the certificate warning once, so it isn't in the recording.
4. Open two tabs: one signed in as Admin, and one private window signed in as Analyst.
5. Close anything showing personal details. Never show `backend\.env` or passwords on screen.
6. Record with the **Xbox Game Bar** (press Windows + G) or OBS Studio, at 1080p.

# Script

| Time | Show | Say |
| --- | --- | --- |
| 0:00 | Sign-in page | "This is EarthScape, a big data platform for a climate agency. It stores, processes and presents climate records, and adds live data and machine learning." |
| 0:20 | Sign-in page | "All the data is public: NASA, NOAA, OpenAQ and Open-Meteo." |
| 0:35 | Sign-in page, wrong password, then correct | "Sign-in is secure. A wrong password is refused, and repeated failures are blocked." |
| 0:55 | Executive Dashboard, hover over the chart | "The dashboard shows global temperature since 1880, the most unusual station readings, and the latest Hadoop jobs." |
| 1:15 | Climate Analytics, change region and variable | "Analysts can explore any region and variable. Every value comes from the pipeline." |
| 1:35 | Hadoop page | "2.5 gigabytes of station records are stored in HDFS. Here are the five MapReduce jobs running on YARN." |
| 1:50 | Start a short job (`air_quality_monthly`), open YARN at port 8088 | "An admin can start a job from here. YARN runs it, and the results go to MongoDB." |
| 2:30 | Data Explorer, upload `valid_readings.csv`, then `invalid_not_really.nc` | "Uploads go to HDFS. A file is checked against its type, so this fake one is refused." |
| 3:00 | Sensor Monitor, Check now, change the city | "Live data for 12 cities arrives every 15 minutes, and these are clearly labelled as estimates." |
| 3:20 | Alerts, create a rule with a low limit, Check now, bell | "Rules are configurable. When a value crosses a limit, an alert opens and a notification appears." |
| 3:50 | ML page, forecast, comparison table, anomalies, correlations | "Models predict temperature, flag unusual air quality and measure correlation. They're scored honestly against a simple baseline, and don't always win." |
| 4:25 | Retrain models, then training history | "Models can be retrained on the latest data, and every run is recorded." |
| 4:45 | Reports, download a GeoJSON file | "Any data can be exported as CSV, JSON or GeoJSON." |
| 5:00 | Analyst window: hidden admin controls, submit a ticket | "An analyst has fewer controls, enforced by the server. They can raise a support ticket here." |
| 5:20 | Admin window: ticket visible, update status | "An admin can read the ticket and update it." |
| 5:30 | System Status, set a maintenance notice, show banner, turn off | "The status page shows each component's health, availability, backups and run times, and admins can announce maintenance." |
| 5:50 | Terminal: stop one backend, refresh the status page | "Apache balances two backends. With one stopped, the site keeps working." |
| 6:10 | Tableau workbook, if built | "The same data can be explored in Tableau." |
| 6:20 | Agency Landing | "That's EarthScape. Thank you for watching." |
