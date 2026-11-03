= EarthScape Climate Agency
=- ReadMe: submission contents, assumptions and quick start

# What's in this zip

| Item | Description |
| --- | --- |
| `docs\EarthScape_Project_Report.docx` | Problem definition, design, diagrams, results, test data and installation |
| `docs\EarthScape_User_Guide.docx` | User guide, tutorials and FAQs |
| `docs\EarthScape_Developer_Guide.docx` | Architecture, workflows, models and maintenance |
| `docs\EarthScape_Video_Script.docx` | Script for the demonstration video |
| `video` | The demonstration video |
| `backend`, `frontend`, `hadoop`, `ml`, `ops`, `deploy` | Source code and configuration |
| `data` | Download scripts and the small source files |
| `test_data` | Sample input, upload test cases and demo results |
| `tableau` | CSV files and export script for Tableau |

The source is also at https://github.com/Mujtaba19938/EarthScape

# Quick start (about 5 minutes)

You need Windows 10 or newer, Python 3.13, and MongoDB with its Database Tools. Unzip to a folder with no spaces in its path, then run these in PowerShell from that folder.

```
py -3.13 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
backend\.venv\Scripts\python.exe backend\seed.py
backend\.venv\Scripts\python.exe ops\load_demo_data.py
backend\.venv\Scripts\python.exe backend\serve.py --port 8000
```

Open http://localhost:8000 and choose **Dashboard**, which opens the sign-in page. The first step of setup generates the Admin and Analyst sign-in details, and saves them in `backend\.env`.

This shows real results from the pipeline without needing Hadoop. Section 7 of the Project Report covers HTTPS, load balancing, Hadoop and the full pipeline.

# Assumptions

- **EarthScape is a demonstration.** The agency in the brief is treated as fictional. Addresses such as `contact@earthscape.test` are placeholders.
- **The public website is still the starting template.** Its pages show the template's farming text and images, and load some of them from the internet. The sign-in page and dashboard are the EarthScape application, and work without internet.
- **Public data stands in for the agency's data.** NASA, NOAA, OpenAQ and Open-Meteo data replaces the agency's own satellite, station and sensor feeds.
- **Two years of station data are enough to demonstrate the pipeline.** GHCN-Daily 2020 and 2023 are used, not the full archive.
- **Polling counts as real-time for this project.** Live data arrives every 15 minutes, with no streaming system.
- **A single-machine Hadoop cluster demonstrates distributed processing.** Tasks run in parallel on one node.
- **Admin and Analyst are the two roles.** The brief gives these as examples.
- **Climate data doesn't need encrypting at rest,** because it's public. Emails and ticket text do, and are.

# Limits you should know about

- **99% uptime and horizontal scaling can't be proven on one computer.** The system measures availability, and load balancing and failover were tested with two backend instances on the same machine. Sustained uptime and scaling across machines haven't been shown.
- **Satellite imagery isn't processed.** Satellite-derived values come as tables from NASA POWER. Imagery files can be uploaded and stored only.
- **Impala isn't used.** MongoDB answers the dashboard's queries.
- **The R script hasn't been run,** because R wasn't installed. The same analysis runs in Python.
- **Email alerts have only been tested against a simulated mail server,** not a real mail provider.
- **The certificate is self-signed,** so browsers show a warning on first visit.
- **Compliance isn't certified.** The system follows common security practice, but hasn't been audited.
- **Four of nine forecasts didn't beat the simple baseline** on the final test years. The report gives the figures.

# Security note

`backend\.env`, certificates and backups aren't in this zip. Setup creates new passwords and keys on each machine. Change the generated passwords before sharing a running copy with anyone.
