= EarthScape User Guide
=- For agency administrators and climate analysts

[[toc]]

# 1. Getting started

EarthScape is the EarthScape Climate Agency's climate data platform. It brings together historical records from NASA, NOAA and OpenAQ with live weather and air quality estimates, then shows the results in one dashboard.

## Opening the site

Open **https://localhost** in Chrome, Edge or Firefox. The site uses a self-signed certificate, so the first visit shows a warning. Choose **Advanced**, then **Proceed to localhost**. Your connection is still encrypted, but no outside authority has vouched for the certificate.

## Signing in

1. Choose **Dashboard** at the top of the home page. The sign-in page opens.
2. Enter your email address and password. The eye icon shows the password as you type.
3. Choose **Sign in**.

![The sign-in page](docs/screenshots/login.png)

Your administrator gives you your details. After five wrong passwords, the account is blocked for 15 minutes. Signing out, closing the tab, or leaving a session for 8 hours all end your session.

## Finding your way around

The dark panel on the left lists every page. The menu button at the top left hides or shows it. The bell shows your notifications. The round button at the top right holds your account settings and **Sign out**.

## What each role can do

| Task | Analyst | Admin |
| --- | --- | --- |
| View all charts, data, forecasts and system status | Yes | Yes |
| Download reports | Yes | Yes |
| Acknowledge and resolve alerts | Yes | Yes |
| Raise support tickets and see their own | Yes | Yes |
| Upload datasets and run MapReduce jobs | No | Yes |
| Retrain the models, and collect live data on demand | No | Yes |
| Create and delete alert rules | No | Yes |
| Add, change or deactivate users | No | Yes |
| Answer all support tickets, and set the maintenance notice | No | Yes |

# 2. Page by page

## Agency Landing

A summary of the latest global temperature anomaly, CO₂ level, unusual station readings and the number of datasets held.

![Agency Landing](docs/screenshots/landing.png)

## Executive Dashboard

The main overview. It shows the headline figures, the global temperature anomaly since 1880, the most unusual weather station readings and the latest MapReduce jobs. Point at the chart to read exact values.

![Executive Dashboard](docs/screenshots/dashboard.png)

## Climate Analytics

Choose a region and a variable to chart it over time. The variables are temperature anomaly, daily high and low, precipitation, solar radiation and surface temperature. The table underneath compares latitude zones. Zones with few readings are less reliable, and station coverage is thin in the far south.

![Climate Analytics](docs/screenshots/analytics.png)

## Sensor Monitor

Current weather and air quality for 12 cities, with a chart of the last 48 hours for any city and measurement. These are model estimates from Open-Meteo, not direct sensor readings. New values arrive every 15 minutes while the collector service runs. Admins can press **Check now** to collect them straight away.

Lower down, the OpenAQ cards show historical readings from real sensors in 2023. These don't update.

![Sensor Monitor](docs/screenshots/monitoring.png)

## Data Explorer & Upload

Lists the datasets held in HDFS and the quality of the weather station data. Admins can upload a new dataset of up to 1 GB in NetCDF, GeoTIFF, HDF5, Parquet, CSV or GRIB2 format. The file's contents are checked against its type, so a text file renamed `.nc` is refused.

Uploaded files are stored safely in HDFS, but they aren't processed automatically. The MapReduce jobs only read the agency's known datasets, and a new format needs a developer to add a job for it.

![Data Explorer](docs/screenshots/data.png)

## Hadoop & HDFS Cluster

Shows whether HDFS and YARN are online, the storage in use, recent jobs and how long each took. Choose a job to read its details. Admins can start any of the five jobs here, one at a time. If this page says Hadoop is offline, see the FAQ.

![Hadoop and HDFS Cluster](docs/screenshots/hadoop.png)

## ML Models & Forecasts

Shows the results of the latest model training:

- **Temperature forecast:** choose a region and a time span. The shaded band is the expected range. This extends past temperatures using statistics, and knows nothing about future emissions, so treat later years with caution.
- **How the methods compared:** how well each forecasting method did on data it had never seen, against simply repeating the last value.
- **Unusual air quality days:** days the Isolation Forest model flagged. A flag means unusual, not confirmed.
- **Correlations:** which measurements move together. This doesn't show that one causes the other.

Admins can press **Retrain models** to train again on the latest data. It takes about 15 seconds.

![ML Models and Forecasts](docs/screenshots/ml.png)

## Alert Management

Rules are checked each time live data arrives. When a value goes above a rule's limit, an alert opens and a notification appears under the bell. Alerts close by themselves once the value drops back under the limit.

Analysts and admins can acknowledge or resolve an alert. Admins can create or delete rules.

![Alert Management](docs/screenshots/alerts.png)

## Reports & Export

Choose the data and a format, then choose **Download**. All reports are available as CSV or JSON. Reports with locations can also be downloaded as GeoJSON for mapping tools.

![Reports and Export](docs/screenshots/reports.png)

## Users & Roles

Admins can add users with a temporary password, change a user's role, and deactivate an account. You can't deactivate your own account, so the system always keeps an administrator.

![Users and Roles](docs/screenshots/rbac.png)

## Feedback & Support

Pick a category, describe the problem or your feedback, and choose **Submit ticket**. The table shows your tickets and their status. Admins see every ticket and can update its status.

![Feedback and Support](docs/screenshots/support.png)

## System Status

Shows the health of each part of the system, measured availability against the 99% goal, recent backups and run times. Admins can also write a maintenance notice here, which appears as a banner to everyone, including on the sign-in page.

![System Status](docs/screenshots/status.png)

## System Architecture and Account Settings

**System Architecture** summarises how the parts fit together and links to the API reference. **Account Settings** lets you change your display name, title and password. New passwords need at least 10 characters.

# 3. Tutorials

## Tutorial 1: Compare warming between regions

1. Open **Climate Analytics**.
2. Set the variable to **Temperature anomaly**.
3. Choose **64N-90N** as the region and read the chart.
4. Choose **EQU-24N**, and compare how far each line has risen.
5. Check the latitude zones table to compare recent station averages side by side.

## Tutorial 2: Set an alert for extreme heat in the app

You need an Admin account for this.

1. Open **Alert Management**, then choose **Create alert rule**.
2. Enter a name, such as `Heat above 35`.
3. Set the metric to **Live temperature**, **Fire above** to `35`, and pick a severity.
4. Choose **Save rule**.
5. Open **Sensor Monitor** and choose **Check now**. If any city is above 35 °C, an alert opens and the bell count goes up.

## Tutorial 3: Download data for a report

1. Open **Reports & Export**.
2. Choose **Monthly air quality by sensor location**.
3. Choose **GeoJSON** to map it, or **CSV** for a spreadsheet.
4. Choose **Download**, then open the file.

## Tutorial 4: Report a problem

1. Open **Feedback & Support**.
2. Choose **Incorrect data** as the category.
3. Say what you saw, on which page, and what you expected.
4. Choose **Submit ticket**, and check back here for its status.

# 4. Tableau workbook

CSV files for Tableau are in the `tableau` folder. To refresh them with the latest data, run `tableau\export_for_tableau.py`.

| File | Use it for |
| --- | --- |
| `global_temperature_co2.csv` | Temperature anomaly and CO₂ by year |
| `zonal_temperature.csv` | Warming by latitude zone |
| `forecasts.csv` | History and forecasts, with the expected range |
| `regional_monthly.csv` | Weather station means by zone and month |
| `air_quality_monthly.csv` | Air quality by location, with coordinates for maps |
| `air_quality_anomalies.csv` | Days the model flagged as unusual |
| `live_readings.csv` | Recent weather and air quality for 12 cities |

To build the workbook in Tableau Public or Desktop:

1. Choose **Connect**, then **Text file**, and open `global_temperature_co2.csv`.
2. Add the other files as separate data sources in the same way.
3. **Temperature trend:** put `year` on Columns and `anomaly_c` on Rows, and set the mark to Line.
4. **Warming by zone:** put `year` on Columns, `zone` on Rows, and `anomaly_c` on Color, for a heat map.
5. **Air quality map:** put `lon` on Columns and `lat` on Rows as dimensions, filter `parameter` to `pm25`, and put `mean` on Size and Color.
6. **Forecast:** filter `series` to `Glob`, put `year` on Columns and `anomaly_c` on Rows, and put `kind` on Color.
7. Combine these sheets into a dashboard, and save it as `tableau\EarthScape.twbx`.

# 5. Frequently asked questions

## The browser says the connection isn't private. Is that a problem?

No. It's expected, because the certificate is self-signed for this computer. A public deployment would use a certificate from a recognised authority.

## I can't sign in.

Check for spaces when you paste your password. After five failures you need to wait 15 minutes. There is no password reset in the app yet. If you've forgotten yours, ask an administrator, who can arrange a reset with a developer or add a new account under another email address.

## Why does the Hadoop page say offline?

HDFS and YARN run separately and need to be started after each restart. Charts still work, because results are kept in MongoDB. An administrator should follow the startup steps in the Developer Guide.

## Why does the status page say the collector isn't running?

The collector service has stopped, so live readings aren't updating. An administrator can run `ops\start_all.ps1` to start it.

## Are the live readings from real sensors?

No. They are Open-Meteo model estimates, and the dashboard says so. The OpenAQ readings are from real sensors, but they are from 2023.

## Should I trust the forecasts?

Treat them as a statistical extension of past temperatures, not a climate prediction. The ML page shows how each one scored on recent years it hadn't seen, and in some regions the method didn't beat simply repeating the last value.

## Why did I receive no alert email?

Emails only go out once an administrator has entered mail server settings. Alerts still appear under the bell without them.

## How do I report a bug or send feedback?

Use **Feedback & Support**.
