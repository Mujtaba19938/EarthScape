"""Live data and alert tests against a separate database. Open-Meteo and HDFS are replaced by stand-ins."""
import datetime
import json
import os
import urllib.error
from unittest import mock

os.environ["MONGO_DB"] = "earthscape_test"
os.environ["JWT_SECRET"] = "test-secret-only-used-by-the-test-suite-0123456789"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import alert_checks, config, emailer, hadoop_client, live  # noqa: E402
from app.db import client as mongo_client  # noqa: E402
from app.db import db  # noqa: E402
from app.field_crypto import email_fields  # noqa: E402
from app.main import app  # noqa: E402
from app.security import hash_password  # noqa: E402

ADMIN = ("admin@test.example", "admin-password-1")
ANALYST = ("analyst@test.example", "analyst-password-1")


@pytest.fixture(scope="module")
def client():
    assert db.name == "earthscape_test"
    mongo_client.drop_database("earthscape_test")
    db.users.insert_many([
        {"name": "Admin", **email_fields(ADMIN[0]), "role": "Admin", "active": True,
         "password_hash": hash_password(ADMIN[1])},
        {"name": "Analyst", **email_fields(ANALYST[0]), "role": "Analyst", "active": True,
         "password_hash": hash_password(ANALYST[1])},
    ])
    with TestClient(app) as test_client:
        yield test_client
    mongo_client.drop_database("earthscape_test")


@pytest.fixture(autouse=True)
def clean(client):
    for name in ("live_readings", "live_polls", "live_batches", "alerts", "alert_rules", "notifications"):
        db[name].delete_many({})


def sign_in(client, credentials):
    response = client.post("/api/auth/login", json={"email": credentials[0], "password": credentials[1]})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["token"]}


def reading(location="Delhi", pm25=10.0, time=None, **values):
    observed = time or datetime.datetime(2026, 1, 1, 12, tzinfo=datetime.timezone.utc)
    return dict({"location": location, "lat": 1.0, "lon": 2.0, "observed_at": observed, "air_observed_at": observed,
                 "temperature_c": 20.0, "humidity_pct": 50, "precipitation_mm": 0.0, "wind_kmh": 5.0,
                 "pm25": pm25, "pm10": 20.0, "no2": 5.0, "o3": 5.0, "us_aqi": 40}, **values)


def add_rule(threshold=50, metric="air_pm25", name="Dirty air"):
    return db.alert_rules.insert_one({"name": name, "metric": metric, "threshold": threshold, "severity": "High"}).inserted_id


def poll_returning(*readings):
    with mock.patch.object(live, "fetch_current", return_value=list(readings)):
        return live.poll()


class FakeResponse:
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


def test_fetch_keeps_each_location_in_order_and_missing_values_as_none():
    with mock.patch.object(live.urllib.request, "urlopen", fake_open_meteo):
        rows = live.fetch_current()
    assert [row["location"] for row in rows] == live.LOCATION_NAMES
    assert rows[0]["pm25"] == 9.5 and rows[0]["temperature_c"] == 21.5
    assert rows[0]["no2"] is None
    assert rows[0]["observed_at"].tzinfo is not None


def test_fetch_rejects_a_reply_with_the_wrong_number_of_locations():
    with mock.patch.object(live.urllib.request, "urlopen", lambda url, timeout: FakeResponse([{"current": {}}])):
        with pytest.raises(ValueError):
            live.fetch_current()


def test_polling_twice_in_one_interval_keeps_one_reading():
    poll_returning(reading())
    poll_returning(reading(pm25=11.0))
    rows = list(db.live_readings.find())
    assert len(rows) == 1
    assert rows[0]["pm25"] == 11.0
    assert rows[0]["archived"] is False


def test_value_above_the_limit_fires_one_alert_and_tells_everyone():
    add_rule()
    assert poll_returning(reading(pm25=60))["alerts_fired"] == 1
    alert = db.alerts.find_one()
    assert alert["status"] == "Active"
    assert alert["subject"] == "Delhi"
    assert "60" in alert["value"] and "50" in alert["value"]
    assert "Dirty air: Delhi" in db.notifications.find_one()["text"]


def test_value_at_the_limit_does_not_fire():
    add_rule()
    assert poll_returning(reading(pm25=50))["alerts_fired"] == 0


def test_alert_does_not_repeat_while_the_value_stays_high_but_updates():
    add_rule()
    poll_returning(reading(pm25=60))
    second = poll_returning(reading(pm25=70, time=datetime.datetime(2026, 1, 1, 13, tzinfo=datetime.timezone.utc)))
    assert second["alerts_fired"] == 0
    assert db.alerts.count_documents({}) == 1
    assert db.alerts.find_one()["measured"] == 70


def test_each_location_gets_its_own_alert():
    add_rule()
    assert poll_returning(reading(pm25=60), reading("Tokyo", pm25=60))["alerts_fired"] == 2


def test_alert_resolves_itself_when_the_value_drops_then_can_fire_again():
    add_rule()
    poll_returning(reading(pm25=60))
    later = datetime.datetime(2026, 1, 1, 13, tzinfo=datetime.timezone.utc)
    assert poll_returning(reading(pm25=10, time=later))["alerts_cleared"] == 1
    assert db.alerts.find_one()["status"] == "Resolved"
    latest = datetime.datetime(2026, 1, 1, 14, tzinfo=datetime.timezone.utc)
    assert poll_returning(reading(pm25=80, time=latest))["alerts_fired"] == 1
    assert db.alerts.count_documents({"status": "Active"}) == 1


def test_resolving_by_hand_does_not_refire_until_the_value_has_dropped(client):
    add_rule()
    poll_returning(reading(pm25=60))
    alert_id = str(db.alerts.find_one()["_id"])
    response = client.patch("/api/alerts/" + alert_id, json={"status": "Resolved"}, headers=sign_in(client, ANALYST))
    assert response.status_code == 200
    assert poll_returning(reading(pm25=60))["alerts_fired"] == 0
    assert db.alerts.find_one()["status"] == "Resolved"


def test_deleting_a_rule_closes_its_alerts():
    rule_id = add_rule()
    poll_returning(reading(pm25=60))
    db.alert_rules.delete_one({"_id": rule_id})
    poll_returning(reading(pm25=60))
    alert = db.alerts.find_one()
    assert alert["status"] == "Resolved" and alert["updated_by"] == "Rule deleted"


def test_missing_value_neither_fires_nor_clears():
    add_rule()
    poll_returning(reading(pm25=60))
    assert poll_returning(reading(pm25=None, time=datetime.datetime(2026, 1, 1, 13, tzinfo=datetime.timezone.utc)))["alerts_cleared"] == 0
    assert db.alerts.find_one()["status"] == "Active"


def test_only_the_newest_reading_for_a_location_is_checked():
    add_rule()
    poll_returning(reading(pm25=10, time=datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)))
    assert poll_returning(reading(pm25=99, time=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)))["alerts_fired"] == 0


def test_rule_on_stored_data_uses_the_latest_year():
    db.co2_annual.insert_many([{"year": 2020, "mean": 500.0}, {"year": 2025, "mean": 400.0}])
    add_rule(450, "co2", "CO2 limit")
    assert poll_returning(reading())["alerts_fired"] == 0
    db.co2_annual.delete_many({})


def test_failed_fetch_is_recorded_notifies_once_then_reports_recovery():
    add_rule()
    with mock.patch.object(live, "fetch_current", side_effect=urllib.error.URLError("down")):
        assert live.poll()["ok"] is False
        assert live.poll()["ok"] is False
    assert db.notifications.count_documents({"text": {"$regex": "failed"}}) == 1
    poll_returning(reading())
    assert db.notifications.count_documents({"text": {"$regex": "working again"}}) == 1
    assert db.live_polls.count_documents({"ok": False}) == 2


def test_email_goes_out_once_with_the_details():
    add_rule()
    with mock.patch.object(emailer, "is_configured", return_value=True), mock.patch.object(emailer, "send_alert_email") as send:
        assert poll_returning(reading(pm25=60))["email"] == "sent"
        poll_returning(reading(pm25=60))
    send.assert_called_once()
    assert db.alerts.find_one()["email_status"] == "sent"


def test_failed_email_keeps_the_alert_and_says_so():
    add_rule()
    with mock.patch.object(emailer, "is_configured", return_value=True), \
            mock.patch.object(emailer, "send_alert_email", side_effect=OSError("mail server down")):
        assert poll_returning(reading(pm25=60))["email"] == "failed"
    assert db.alerts.count_documents({"email_status": "failed"}) == 1
    assert db.notifications.count_documents({"text": {"$regex": "email failed"}}) == 1


def test_email_is_marked_not_set_up_without_settings():
    add_rule()
    with mock.patch.object(config, "SMTP_HOST", None):
        assert poll_returning(reading(pm25=60))["email"] == "not set up"


def test_email_message_is_addressed_and_uses_the_login():
    fake = mock.MagicMock()
    fake.__enter__.return_value = fake
    alert = {"severity": "High", "title": "Dirty air: Delhi", "value": "60 µg/m³ (limit 50)"}
    with mock.patch.object(config, "SMTP_HOST", "mail.example"), mock.patch.object(config, "SMTP_PORT", 587), \
            mock.patch.object(config, "SMTP_TLS", True), mock.patch.object(config, "SMTP_USER", "me"), \
            mock.patch.object(config, "SMTP_PASSWORD", "pw"), mock.patch.object(config, "SMTP_FROM", "from@example.org"), \
            mock.patch.object(config, "ALERT_EMAIL_TO", "a@example.org, b@example.org"), \
            mock.patch.object(emailer.smtplib, "SMTP", return_value=fake):
        emailer.send_alert_email([alert])
    fake.starttls.assert_called_once()
    fake.login.assert_called_once_with("me", "pw")
    message = fake.send_message.call_args.args[0]
    assert message["To"] == "a@example.org, b@example.org"
    assert "Dirty air: Delhi" in message.get_content()


def test_archive_writes_new_readings_once():
    poll_returning(reading())
    uploaded = []

    def fake_put(path, target):
        with open(path, encoding="utf-8") as source:
            uploaded.append((target, source.read()))

    with mock.patch.object(hadoop_client, "put_file", fake_put):
        batch = live.archive_readings()
        assert live.archive_readings() is None
    assert batch["ok"] is True and batch["rows"] == 1
    assert uploaded[0][0] == "/climate/raw/live"
    assert uploaded[0][1].startswith("location,lat,lon,observed_at")
    assert "Delhi" in uploaded[0][1]
    assert db.live_readings.count_documents({"archived": True}) == 1


def test_readings_wait_when_hdfs_is_down_then_archive_later():
    poll_returning(reading())
    with mock.patch.object(hadoop_client, "put_file", side_effect=OSError("down")):
        assert live.archive_readings()["ok"] is False
    assert db.live_readings.count_documents({"archived": False}) == 1
    with mock.patch.object(hadoop_client, "put_file"):
        assert live.archive_readings()["ok"] is True
    assert db.live_readings.count_documents({"archived": False}) == 0


def test_live_data_needs_a_login(client):
    assert client.get("/api/live/latest").status_code == 401
    assert client.post("/api/live/poll").status_code == 401


def test_latest_shows_one_reading_per_location_without_internal_fields(client):
    poll_returning(reading(time=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)))
    poll_returning(reading(pm25=33.0, time=datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)))
    body = client.get("/api/live/latest", headers=sign_in(client, ANALYST)).json()
    assert len(body["readings"]) == 1
    assert body["readings"][0]["pm25"] == 33.0
    assert "archived" not in body["readings"][0] and "_id" not in body["readings"][0]
    assert body["status"]["waiting_for_hdfs"] == 2


def test_status_is_stale_when_the_collector_has_stopped(client):
    now = datetime.datetime.now(datetime.timezone.utc)
    db.live_polls.insert_one({"started_at": now - datetime.timedelta(hours=5), "ok": True})
    assert live.status()["stale"] is True
    db.live_polls.insert_one({"started_at": now, "ok": True})
    assert live.status()["stale"] is False


def test_history_only_serves_known_locations(client):
    headers = sign_in(client, ANALYST)
    assert client.get("/api/live/history?location=Atlantis", headers=headers).status_code == 404
    assert client.get("/api/live/history?location=Delhi", headers=headers).json() == []


def test_analyst_cannot_trigger_a_check(client):
    assert client.post("/api/live/poll", headers=sign_in(client, ANALYST)).status_code == 403


def test_admin_check_runs_and_explains_a_failure(client):
    headers = sign_in(client, ADMIN)
    with mock.patch.object(live, "fetch_current", return_value=[reading()]):
        response = client.post("/api/live/poll", headers=headers)
    assert response.status_code == 200
    assert response.json()["triggered_by"] == "Admin"
    with mock.patch.object(live, "fetch_current", side_effect=urllib.error.URLError("secret detail")):
        response = client.post("/api/live/poll", headers=headers)
    assert response.status_code == 502
    assert "secret detail" not in response.text


@pytest.mark.parametrize("format", ["csv", "json", "geojson"])
def test_live_report_downloads_in_every_format(client, format):
    poll_returning(reading())
    response = client.get("/api/reports/live_readings?format=" + format, headers=sign_in(client, ANALYST))
    assert response.status_code == 200
    assert "2026-01-01T12:00:00" in response.text


def test_new_metrics_can_be_used_in_rules(client):
    headers = sign_in(client, ADMIN)
    body = {"name": "Heat", "metric": "live_temperature", "threshold": 40, "severity": "Critical"}
    assert client.post("/api/alert-rules", json=body, headers=headers).status_code == 201
    assert "live_temperature" in client.get("/api/alert-metrics", headers=headers).json()["metrics"]
    assert set(alert_checks.ALERT_METRICS) == set(alert_checks.METRICS)
