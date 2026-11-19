"""Live data, alerts, email and HDFS archive. Open-Meteo and HDFS are stand-ins."""
import datetime
import json
import urllib.error
from unittest import mock

from earthscape import config
from earthscape.db import acquire_lock, db
from earthscape.testing import ADMIN, ANALYST, MongoTestCase

from dashboard import cluster, live

UTC = datetime.timezone.utc


def at(day=1, hour=12):
    return datetime.datetime(2026, 1, day, hour, tzinfo=UTC)


def reading(location="Lahore", pm25=10.0, time=None, **values):
    observed = time or at()
    row = {"location": location, "lat": 1.0, "lon": 2.0, "observed_at": observed, "air_observed_at": observed,
           "temperature_c": 20.0, "humidity_pct": 50, "precipitation_mm": 0.0, "wind_kmh": 5.0,
           "pm25": pm25, "pm10": 20.0, "no2": 5.0, "o3": 5.0, "us_aqi": 40}
    row.update(values)
    return row


def add_rule(threshold=50, metric="air_pm25", name="Dirty air"):
    return db.alert_rules.insert_one({"name": name, "metric": metric, "threshold": threshold, "severity": "High"}).inserted_id


def poll_returning(*readings, by="collector"):
    with mock.patch.object(live, "fetch_current", return_value=list(readings)):
        return live.poll(by)


class FakeResponse:
    """Open-Meteo reply."""

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.body).encode("utf-8")


def fake_open_meteo(url, timeout):
    time = "2026-01-01T12:00"
    if "air-quality" in url:
        row = {"current": {"time": time, "pm2_5": 9.5, "pm10": 12, "nitrogen_dioxide": None, "ozone": 30, "us_aqi": 40}}
    else:
        row = {"current": {"time": time, "temperature_2m": 21.5, "relative_humidity_2m": 40, "precipitation": 0, "wind_speed_10m": 7}}
    return FakeResponse([row] * len(live.LOCATIONS))


#----------------------------fetching--------------------------------------

class FetchTests(MongoTestCase):
    with_users = False

    def test_fetch_keeps_each_location_in_order_and_missing_values_as_none(self):
        with mock.patch.object(live.urllib.request, "urlopen", fake_open_meteo):
            rows = live.fetch_current()
        self.assertEqual([row["location"] for row in rows], live.LOCATION_NAMES)
        self.assertEqual((rows[0]["pm25"], rows[0]["temperature_c"]), (9.5, 21.5))
        self.assertIsNone(rows[0]["no2"])
        self.assertIsNotNone(rows[0]["observed_at"].tzinfo)

    def test_fetch_rejects_a_reply_with_the_wrong_number_of_locations(self):
        with mock.patch.object(live.urllib.request, "urlopen", lambda url, timeout: FakeResponse([{"current": {}}])):
            with self.assertRaises(ValueError):
                live.fetch_current()

    def test_polling_twice_in_one_interval_keeps_one_reading(self):
        poll_returning(reading())
        poll_returning(reading(pm25=11.0))
        rows = list(db.live_readings.find())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pm25"], 11.0)
        self.assertIs(rows[0]["archived"], False)


#----------------------------alert checks--------------------------------------

class AlertTests(MongoTestCase):

    def test_value_above_the_limit_fires_one_alert_and_tells_everyone(self):
        add_rule()
        self.assertEqual(poll_returning(reading(pm25=60))["alerts_fired"], 1)
        alert = db.alerts.find_one()
        self.assertEqual((alert["status"], alert["subject"]), ("Active", "Lahore"))
        self.assertIn("60", alert["value"])
        self.assertIn("50", alert["value"])
        self.assertIn("Dirty air: Lahore", db.notifications.find_one()["text"])

    def test_value_at_the_limit_does_not_fire(self):
        add_rule()
        self.assertEqual(poll_returning(reading(pm25=50))["alerts_fired"], 0)

    def test_alert_does_not_repeat_while_the_value_stays_high_but_updates(self):
        add_rule()
        poll_returning(reading(pm25=60))
        self.assertEqual(poll_returning(reading(pm25=70, time=at(hour=13)))["alerts_fired"], 0)
        self.assertEqual(db.alerts.count_documents({}), 1)
        self.assertEqual(db.alerts.find_one()["measured"], 70)

    def test_each_location_gets_its_own_alert(self):
        add_rule()
        self.assertEqual(poll_returning(reading(pm25=60), reading("Karachi", pm25=60))["alerts_fired"], 2)

    def test_alert_resolves_itself_when_the_value_drops_then_can_fire_again(self):
        add_rule()
        poll_returning(reading(pm25=60))
        self.assertEqual(poll_returning(reading(pm25=10, time=at(hour=13)))["alerts_cleared"], 1)
        self.assertEqual(db.alerts.find_one()["status"], "Resolved")
        self.assertEqual(poll_returning(reading(pm25=80, time=at(hour=14)))["alerts_fired"], 1)
        self.assertEqual(db.alerts.count_documents({"status": "Active"}), 1)

    def test_resolving_by_hand_does_not_refire_until_the_value_has_dropped(self):
        add_rule()
        poll_returning(reading(pm25=60))
        alert_id = db.alerts.find_one()["_id"]
        self.sign_in(ANALYST)
        self.assertEqual(self.client.post("/dashboard/alerts/%s/" % alert_id, {"status": "Resolved"}).status_code, 302)
        self.assertEqual(db.alerts.find_one()["updated_by"], "Analyst")
        self.assertEqual(poll_returning(reading(pm25=60))["alerts_fired"], 0)
        self.assertEqual(db.alerts.find_one()["status"], "Resolved")

    def test_an_unknown_alert_status_is_refused(self):
        add_rule()
        poll_returning(reading(pm25=60))
        self.sign_in(ANALYST)
        response = self.client.post("/dashboard/alerts/%s/" % db.alerts.find_one()["_id"], {"status": "Gone"})
        self.assertEqual(response.status_code, 400)

    def test_deleting_a_rule_closes_its_alerts(self):
        rule_id = add_rule()
        poll_returning(reading(pm25=60))
        self.sign_in(ADMIN)
        self.client.post("/dashboard/alerts/rules/%s/delete/" % rule_id)
        self.assertEqual(db.alert_rules.count_documents({}), 0)
        poll_returning(reading(pm25=60))
        alert = db.alerts.find_one()
        self.assertEqual((alert["status"], alert["updated_by"]), ("Resolved", "Rule deleted"))

    def test_missing_value_neither_fires_nor_clears(self):
        add_rule()
        poll_returning(reading(pm25=60))
        self.assertEqual(poll_returning(reading(pm25=None, time=at(hour=13)))["alerts_cleared"], 0)
        self.assertEqual(db.alerts.find_one()["status"], "Active")

    def test_only_the_newest_reading_for_a_location_is_checked(self):
        add_rule()
        poll_returning(reading(pm25=10, time=at(day=2)))
        self.assertEqual(poll_returning(reading(pm25=99, time=at(day=1)))["alerts_fired"], 0)

    def test_rule_on_stored_data_uses_the_latest_year(self):
        db.co2_annual.insert_many([{"year": 2020, "mean": 500.0}, {"year": 2025, "mean": 400.0}])
        add_rule(450, "co2", "CO2 limit")
        self.assertEqual(poll_returning(reading())["alerts_fired"], 0)

    def test_a_city_no_longer_monitored_leaves_the_monitor_and_clears_its_alerts(self):
        rule_id = add_rule()
        db.live_readings.insert_one(dict(reading("Atlantis", pm25=60), archived=True))
        db.alerts.insert_one({"rule_id": str(rule_id), "metric": "air_pm25", "subject": "Atlantis", "status": "Active", "cleared": False})
        self.assertEqual(poll_returning(reading(pm25=10))["alerts_cleared"], 1)
        self.assertEqual(db.alerts.find_one({"subject": "Atlantis"})["status"], "Resolved")
        self.assertEqual([row["location"] for row in live.latest_readings()], ["Lahore"])
        # History kept
        self.assertEqual(db.live_readings.count_documents({"location": "Atlantis"}), 1)

    def test_failed_fetch_is_recorded_notifies_once_then_reports_recovery(self):
        add_rule()
        with mock.patch.object(live, "fetch_current", side_effect=urllib.error.URLError("down")):
            self.assertIs(live.poll()["ok"], False)
            self.assertIs(live.poll()["ok"], False)
        self.assertEqual(db.notifications.count_documents({"text": {"$regex": "failed"}}), 1)
        poll_returning(reading())
        self.assertEqual(db.notifications.count_documents({"text": {"$regex": "working again"}}), 1)
        self.assertEqual(db.live_polls.count_documents({"ok": False}), 2)


#----------------------------rules page--------------------------------------

class RuleTests(MongoTestCase):

    def test_admin_adds_a_rule_on_any_metric_without_inventing_an_alert(self):
        self.sign_in(ADMIN)
        self.client.post("/dashboard/alerts/rules/new/", {"name": "Heat", "metric": "live_temperature",
                                                          "threshold": "40", "severity": "Critical"})
        rule = db.alert_rules.find_one()
        self.assertEqual((rule["name"], rule["threshold"], rule["created_by"]), ("Heat", 40.0, "Admin"))
        self.assertEqual(db.alerts.count_documents({}), 0)
        page = self.client.get("/dashboard/alerts/")
        self.assertIn("live_temperature", page.context["metrics"])
        self.assertEqual(page.context["alerts"], [])
        self.assertEqual(set(live.ALERT_METRICS), set(live.METRICS))

    def test_bad_rules_are_refused(self):
        self.sign_in(ADMIN)
        for body in ({"name": "", "metric": "co2", "threshold": "1", "severity": "Low"},
                     {"name": "X", "metric": "co2", "threshold": "many", "severity": "Low"},
                     {"name": "X", "metric": "mars", "threshold": "1", "severity": "Low"},
                     {"name": "X", "metric": "co2", "threshold": "1", "severity": "Huge"}):
            self.client.post("/dashboard/alerts/rules/new/", body)
        self.assertEqual(db.alert_rules.count_documents({}), 0)


#----------------------------alert email--------------------------------------

class EmailTests(MongoTestCase):
    with_users = False

    def test_email_goes_out_once_with_the_details(self):
        add_rule()
        with mock.patch.object(live, "email_configured", return_value=True), mock.patch.object(live, "send_alert_email") as send:
            self.assertEqual(poll_returning(reading(pm25=60))["email"], "sent")
            poll_returning(reading(pm25=60))
        send.assert_called_once()
        self.assertEqual(db.alerts.find_one()["email_status"], "sent")

    def test_failed_email_keeps_the_alert_and_says_so(self):
        add_rule()
        with mock.patch.object(live, "email_configured", return_value=True), \
                mock.patch.object(live, "send_alert_email", side_effect=OSError("mail server down")):
            self.assertEqual(poll_returning(reading(pm25=60))["email"], "failed")
        self.assertEqual(db.alerts.count_documents({"email_status": "failed"}), 1)
        self.assertEqual(db.notifications.count_documents({"text": {"$regex": "email failed"}}), 1)

    def test_email_is_marked_not_set_up_without_settings(self):
        add_rule()
        with mock.patch.object(config, "SMTP_HOST", None):
            self.assertEqual(poll_returning(reading(pm25=60))["email"], "not set up")

    def test_email_message_is_addressed_and_uses_the_login(self):
        fake = mock.MagicMock()
        fake.__enter__.return_value = fake
        alert = {"severity": "High", "title": "Dirty air: Lahore", "value": "60 µg/m³ (limit 50)"}
        settings = {"SMTP_HOST": "mail.example", "SMTP_PORT": 587, "SMTP_TLS": True, "SMTP_USER": "me",
                    "SMTP_PASSWORD": "pw", "SMTP_FROM": "from@example.org", "ALERT_EMAIL_TO": "a@example.org, b@example.org"}
        with mock.patch.multiple(config, **settings), mock.patch.object(live.smtplib, "SMTP", return_value=fake):
            live.send_alert_email([alert])
        fake.starttls.assert_called_once()
        fake.login.assert_called_once_with("me", "pw")
        message = fake.send_message.call_args.args[0]
        self.assertEqual(message["To"], "a@example.org, b@example.org")
        self.assertIn("Dirty air: Lahore", message.get_content())


#----------------------------hdfs archive--------------------------------------

class ArchiveTests(MongoTestCase):
    with_users = False

    def test_archive_writes_new_readings_once(self):
        poll_returning(reading())
        uploaded = []

        def fake_put(path, target):
            with open(path, encoding="utf-8") as source:
                uploaded.append((target, source.read()))

        with mock.patch.object(cluster, "put_file", fake_put):
            batch = live.archive_readings()
            self.assertIsNone(live.archive_readings())
        self.assertEqual((batch["ok"], batch["rows"]), (True, 1))
        self.assertEqual(uploaded[0][0], "/climate/raw/live")
        self.assertTrue(uploaded[0][1].startswith("location,lat,lon,observed_at"))
        self.assertIn("Lahore", uploaded[0][1])
        self.assertEqual(db.live_readings.count_documents({"archived": True}), 1)

    def test_readings_wait_when_hdfs_is_down_then_archive_later(self):
        poll_returning(reading())
        with mock.patch.object(cluster, "put_file", side_effect=OSError("down")):
            self.assertIs(live.archive_readings()["ok"], False)
        self.assertEqual(db.live_readings.count_documents({"archived": False}), 1)
        with mock.patch.object(cluster, "put_file"):
            self.assertIs(live.archive_readings()["ok"], True)
        self.assertEqual(db.live_readings.count_documents({"archived": False}), 0)


#----------------------------monitor page--------------------------------------

class MonitorPageTests(MongoTestCase):

    def test_monitor_shows_one_card_per_city_and_the_hdfs_backlog(self):
        poll_returning(reading(time=at(day=1)))
        poll_returning(reading(pm25=33.0, time=at(day=2)))
        self.sign_in(ANALYST)
        page = self.client.get("/dashboard/monitor/")
        self.assertEqual(len(page.context["cards"]), 1)
        self.assertIn(("PM2.5", "33.0 µg/m³"), page.context["cards"][0]["values"])
        self.assertEqual(page.context["status"]["waiting_for_hdfs"], 2)
        self.assertIn("2 readings waiting", page.context["batch_text"])

    def test_status_is_stale_when_the_collector_has_stopped(self):
        moment = datetime.datetime.now(UTC)
        db.live_polls.insert_one({"started_at": moment - datetime.timedelta(hours=5), "ok": True})
        self.assertIs(live.status()["stale"], True)
        db.live_polls.insert_one({"started_at": moment, "ok": True})
        self.assertIs(live.status()["stale"], False)

    def test_unknown_city_or_metric_falls_back_to_the_first(self):
        self.sign_in(ANALYST)
        page = self.client.get("/dashboard/monitor/?location=Atlantis&metric=pm25")
        self.assertEqual(page.context["location"], config.LIVE_LOCATION_NAMES[0])
        self.assertEqual(page.context["chart"]["labels"], [])

    def test_admin_check_runs_and_explains_a_failure_without_details(self):
        self.sign_in(ADMIN)
        with mock.patch.object(live, "fetch_current", return_value=[reading()]):
            response = self.client.post("/dashboard/monitor/poll/")
        self.assertIn("Checked 1 cities", self.follow_messages(response)[0])
        self.assertEqual(db.live_polls.find_one()["triggered_by"], "Admin")
        with mock.patch.object(live, "fetch_current", side_effect=urllib.error.URLError("secret detail")):
            response = self.client.post("/dashboard/monitor/poll/")
        shown = self.follow_messages(response)[0]
        self.assertIn("Couldn't reach Open-Meteo", shown)
        self.assertNotIn("secret detail", shown)

    def test_second_check_refused_while_another_instance_is_checking(self):
        acquire_lock(live.POLL_LOCK, 60)
        self.sign_in(ADMIN)
        with mock.patch.object(live, "fetch_current") as fetch:
            response = self.client.post("/dashboard/monitor/poll/")
        self.assertIn("already running", self.follow_messages(response)[0])
        fetch.assert_not_called()

    def test_live_report_downloads_in_every_format(self):
        poll_returning(reading())
        self.sign_in(ANALYST)
        for file_format in ("csv", "json", "geojson"):
            response = self.client.get("/dashboard/reports/download/?report=live_readings&format=" + file_format)
            self.assertEqual(response.status_code, 200, file_format)
            self.assertIn("2026-01-01T12:00:00", response.content.decode())
