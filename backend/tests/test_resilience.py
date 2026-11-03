"""Login limits, encryption, shared locks, health, status and backups, against a separate database."""
import datetime
import os
import subprocess
import sys
import urllib.error
from pathlib import Path
from unittest import mock

os.environ["MONGO_DB"] = "earthscape_test"
os.environ["JWT_SECRET"] = "test-secret-only-used-by-the-test-suite-0123456789"

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ops"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pymongo.errors import PyMongoError  # noqa: E402

import backup  # noqa: E402
import health_monitor  # noqa: E402
from app import hadoop_client, locks, login_limit, main  # noqa: E402
from app.db import client as mongo_client  # noqa: E402
from app.db import db, encrypt_existing_fields  # noqa: E402
from app.field_crypto import decrypt, email_fields, email_lookup, encrypt  # noqa: E402
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
    for name in ("login_failures", "locks", "health_checks", "backups", "notifications", "settings", "tickets"):
        db[name].delete_many({})


def login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def sign_in(client, credentials):
    response = login(client, *credentials)
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["token"]}


# --- Login limit ---

def test_account_is_blocked_after_repeated_failures_even_with_the_right_password(client):
    for _ in range(login_limit.MAX_FAILURES_PER_ACCOUNT):
        assert login(client, ANALYST[0], "wrong").status_code == 401
    blocked = login(client, ANALYST[0], ANALYST[1])
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == str(login_limit.RETRY_AFTER_SECONDS)


def test_unknown_emails_are_limited_the_same_way(client):
    for _ in range(login_limit.MAX_FAILURES_PER_ACCOUNT):
        assert login(client, "who@test.example", "wrong").status_code == 401
    assert login(client, "who@test.example", "wrong").status_code == 429


def test_one_person_being_guessed_at_does_not_block_someone_else(client):
    for _ in range(login_limit.MAX_FAILURES_PER_ACCOUNT):
        login(client, ANALYST[0], "wrong")
    assert login(client, ADMIN[0], ADMIN[1]).status_code == 200


def test_same_email_from_another_address_is_not_blocked(client):
    for _ in range(login_limit.MAX_FAILURES_PER_ACCOUNT):
        login_limit.record_failure(ANALYST[0], "10.0.0.1")
    assert login_limit.is_blocked(ANALYST[0], "10.0.0.1")
    assert not login_limit.is_blocked(ANALYST[0], "10.0.0.2")


def test_one_address_trying_many_accounts_is_blocked(client):
    for number in range(login_limit.MAX_FAILURES_PER_ADDRESS):
        login_limit.record_failure("person%d@test.example" % number, "10.0.0.9")
    assert login_limit.is_blocked("new@test.example", "10.0.0.9")


def test_successful_sign_in_resets_the_count(client):
    for _ in range(login_limit.MAX_FAILURES_PER_ACCOUNT - 1):
        login(client, ANALYST[0], "wrong")
    assert login(client, ANALYST[0], ANALYST[1]).status_code == 200
    assert login(client, ANALYST[0], "wrong").status_code == 401
    assert login(client, ANALYST[0], ANALYST[1]).status_code == 200


def test_block_ends_when_the_window_ends(client):
    for _ in range(login_limit.MAX_FAILURES_PER_ACCOUNT):
        login(client, ANALYST[0], "wrong")
    db.login_failures.update_many({}, {"$set": {"expires_at": datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)}})
    assert login(client, ANALYST[0], ANALYST[1]).status_code == 200


# --- Encryption ---

def test_emails_and_tickets_are_unreadable_in_the_database_but_readable_through_the_api(client):
    headers = sign_in(client, ANALYST)
    created = client.post("/api/tickets", json={"category": "Feedback", "description": "Private note"}, headers=headers)
    assert created.status_code == 201
    assert created.json()["description"] == "Private note"
    assert client.get("/api/tickets", headers=headers).json()[0]["description"] == "Private note"
    assert "Private note" not in str(db.tickets.find_one())
    stored = db.users.find_one({"email_lookup": email_lookup(ANALYST[0])})
    assert ANALYST[0] not in str(stored)
    assert client.get("/api/auth/me", headers=headers).json()["email"] == ANALYST[0]


def test_encrypting_the_same_text_twice_gives_different_results():
    assert encrypt("same") != encrypt("same")
    assert decrypt(encrypt("same")) == "same"


def test_existing_plain_records_are_converted_and_conversion_is_repeatable(client):
    plain_user = db.users.insert_one({"name": "Old", "email": "old@test.example", "role": "Analyst", "active": True,
                                      "password_hash": hash_password("old-password-1")}).inserted_id
    plain_ticket = db.tickets.insert_one({"category": "Feedback", "description": "Old note", "created_by": "x"}).inserted_id
    encrypt_existing_fields()
    encrypt_existing_fields()
    user = db.users.find_one({"_id": plain_user})
    assert "email" not in user and decrypt(user["email_enc"]) == "old@test.example"
    ticket = db.tickets.find_one({"_id": plain_ticket})
    assert "description" not in ticket and decrypt(ticket["description_enc"]) == "Old note"
    assert login(client, "old@test.example", "old-password-1").status_code == 200
    db.users.delete_one({"_id": plain_user})


def test_duplicate_email_is_still_refused(client):
    response = client.post("/api/users", headers=sign_in(client, ADMIN), json={
        "name": "Dup", "email": ANALYST[0], "role": "Analyst", "password": "long-enough-pass"})
    assert response.status_code == 409


# --- Shared locks ---

def test_lock_can_only_be_held_once_until_released():
    assert locks.acquire("x", 60) is True
    assert locks.acquire("x", 60) is False
    assert locks.is_held("x")
    locks.release("x")
    assert locks.acquire("x", 60) is True


def test_lock_from_a_crashed_instance_expires():
    assert locks.acquire("x", -1) is True
    assert not locks.is_held("x")
    assert locks.acquire("x", 60) is True


def test_hadoop_job_refused_while_another_instance_runs_one(client):
    locks.acquire(hadoop_client.JOB_LOCK, 60)
    assert client.post("/api/jobs/data_quality/run", headers=sign_in(client, ADMIN)).status_code == 409


def test_second_check_refused_while_another_instance_is_checking(client):
    locks.acquire("live_poll", 60)
    assert client.post("/api/live/poll", headers=sign_in(client, ADMIN)).status_code == 409


# --- Health and headers ---

def test_health_is_public_and_names_the_instance(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["X-EarthScape-Instance"] == response.json()["instance"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_health_fails_when_the_database_is_unreachable(client):
    with mock.patch.object(main.db, "command", side_effect=PyMongoError("down")):
        assert client.get("/api/health").status_code == 503


# --- Status and maintenance ---

def test_status_needs_a_login_and_is_honest_when_nothing_has_run(client):
    assert client.get("/api/status").status_code == 401
    with mock.patch.object(hadoop_client, "cluster_status", return_value={"hdfs_online": False, "yarn_online": False}):
        body = client.get("/api/status", headers=sign_in(client, ANALYST)).json()
    states = {component["name"]: component["ok"] for component in body["components"]}
    assert states["HDFS"] is False
    assert states["Backups"] is False
    assert states["Health monitor"] is False
    assert body["targets"] == []


def test_a_manual_check_does_not_make_the_collector_look_alive(client):
    now = datetime.datetime.now(datetime.timezone.utc)
    db.live_polls.delete_many({})
    db.live_polls.insert_one({"started_at": now, "ok": True, "triggered_by": "Admin"})
    with mock.patch.object(hadoop_client, "cluster_status", return_value={"hdfs_online": True, "yarn_online": True}):
        body = client.get("/api/status", headers=sign_in(client, ANALYST)).json()
    assert {c["name"]: c["ok"] for c in body["components"]}["Live data collector"] is False
    db.live_polls.insert_one({"started_at": now, "ok": True, "triggered_by": "collector"})
    with mock.patch.object(hadoop_client, "cluster_status", return_value={"hdfs_online": True, "yarn_online": True}):
        body = client.get("/api/status", headers=sign_in(client, ANALYST)).json()
    assert {c["name"]: c["ok"] for c in body["components"]}["Live data collector"] is True
    db.live_polls.delete_many({})


def test_status_calculates_uptime_from_recorded_checks(client):
    now = datetime.datetime.now(datetime.timezone.utc)
    db.health_checks.insert_many(
        [{"target": "site", "ok": True, "ms": 5, "at": now - datetime.timedelta(minutes=minute)} for minute in range(1, 4)]
        + [{"target": "site", "ok": False, "ms": 5, "at": now}])
    with mock.patch.object(hadoop_client, "cluster_status", return_value={"hdfs_online": True, "yarn_online": True}):
        body = client.get("/api/status", headers=sign_in(client, ANALYST)).json()
    assert body["targets"][0]["day"] == {"percent": 75.0, "checks": 4}
    assert body["targets"][0]["latest"]["ok"] is False


def test_only_admin_sets_the_banner_and_anyone_can_read_it(client):
    body = {"active": True, "message": "  Down at 6pm  "}
    assert client.put("/api/maintenance", json=body).status_code == 401
    assert client.put("/api/maintenance", json=body, headers=sign_in(client, ANALYST)).status_code == 403
    assert client.get("/api/maintenance").json() == {"active": False, "message": ""}
    assert client.put("/api/maintenance", json=body, headers=sign_in(client, ADMIN)).status_code == 200
    assert client.get("/api/maintenance").json() == {"active": True, "message": "Down at 6pm"}


def test_banner_message_length_is_limited(client):
    response = client.put("/api/maintenance", json={"active": True, "message": "x" * 301}, headers=sign_in(client, ADMIN))
    assert response.status_code == 422


# --- Health monitor ---

def test_monitor_tells_people_only_when_a_target_changes(client):
    for ok in (True, True, False, False, True):
        health_monitor.record("site", {"ok": ok, "status": 200 if ok else None, "error": None, "ms": 1})
    assert [row["text"] for row in db.notifications.find().sort("created_at", 1)] == ["site is down.", "site is back up."]
    assert db.health_checks.count_documents({}) == 5


def test_monitor_records_a_refused_connection_as_down():
    with mock.patch.object(health_monitor.urllib.request, "urlopen", side_effect=urllib.error.URLError("refused")):
        result = health_monitor.check("http://127.0.0.1:9/api/health")
    assert result["ok"] is False and result["error"] == "URLError"


def test_monitor_records_an_error_status_as_down():
    error = urllib.error.HTTPError("http://x", 503, "unavailable", {}, None)
    with mock.patch.object(health_monitor.urllib.request, "urlopen", side_effect=error):
        result = health_monitor.check("http://x")
    assert result["ok"] is False and result["status"] == 503


# --- Backups ---

def test_prune_keeps_the_newest_and_never_touches_other_folders(tmp_path):
    for name in ("20260101-000000", "20260102-000000", "20260103-000000", "important", "2026"):
        (tmp_path / name).mkdir()
    assert backup.prune(tmp_path, 2) == ["20260101-000000"]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["2026", "20260102-000000", "20260103-000000", "important"]


def test_restore_check_finds_missing_and_short_collections():
    assert backup.counts_match({"a": 100}, {"a": 100}) == []
    assert backup.counts_match({"a": 1000}, {"a": 995}) == []
    assert backup.counts_match({"a": 100}, {}) == ["a is missing"]
    assert "a has 500 rows" in backup.counts_match({"a": 1000}, {"a": 500})[0]


def test_failed_backup_is_recorded_and_reported(client, tmp_path):
    with mock.patch.object(backup.config, "BACKUP_DIR", str(tmp_path)), \
            mock.patch.object(backup, "dump_mongo", side_effect=RuntimeError("no space")):
        assert backup.main() == 1
    row = db.backups.find_one()
    assert row["ok"] is False and "no space" in row["error"]
    assert "Backup failed" in db.notifications.find_one()["text"]


def test_mongodb_is_backed_up_even_when_hdfs_is_down(client, tmp_path):
    with mock.patch.object(backup.config, "BACKUP_DIR", str(tmp_path)), mock.patch.object(backup, "dump_mongo"), \
            mock.patch.object(backup, "verify_restore", return_value=10), \
            mock.patch.object(hadoop_client.run_pipeline, "hdfs", side_effect=subprocess.CalledProcessError(1, "hdfs")):
        assert backup.main() == 0
    row = db.backups.find_one()
    assert row["ok"] is True and row["hdfs_failed"] == backup.HDFS_PATHS
    assert "weren't copied" in db.notifications.find_one()["text"]
