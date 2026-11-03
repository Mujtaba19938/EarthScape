"""ML API tests against a separate database. Training itself is tested in ml/test_train_models.py."""
import datetime
import os
import subprocess
from unittest import mock

os.environ["MONGO_DB"] = "earthscape_test"
os.environ["JWT_SECRET"] = "test-secret-only-used-by-the-test-suite-0123456789"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import locks, ml_client  # noqa: E402
from app.db import client as mongo_client  # noqa: E402
from app.db import db  # noqa: E402
from app.field_crypto import email_fields  # noqa: E402
from app.main import app  # noqa: E402
from app.security import hash_password  # noqa: E402

ADMIN = ("admin@test.example", "admin-password-1")
ANALYST = ("analyst@test.example", "analyst-password-1")


def run_document(version, day):
    comparison = [
        {"method": "persistence", "test_rmse": 0.3},
        {"method": "holt", "test_rmse": 0.2},
    ]
    return {
        "version": version, "trained_at": datetime.datetime(2026, 1, day), "triggered_by": "Admin",
        "forecast_scores": [{"series": "Glob", "chosen_method": "holt", "comparison": comparison}],
        "anomaly": {"false_alarm_rate": 0.01, "recall_by_spike_size": {"10": 0.9}},
    }


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
    db.ml_runs.insert_many([run_document("old", 1), run_document("new", 2)])
    db.ml_forecasts.insert_one({"series": "Glob", "forecast": [{"year": 2026, "forecast": 1.0}]})
    db.ml_anomalies.insert_many([{"date": "low", "score": 0.1}, {"date": "high", "score": 0.9}])
    db.ml_correlations.insert_one({"name": "co2_levels", "pearson": 0.9})
    with TestClient(app) as test_client:
        yield test_client
    mongo_client.drop_database("earthscape_test")


def sign_in(client, credentials):
    response = client.post("/api/auth/login", json={"email": credentials[0], "password": credentials[1]})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["token"]}


@pytest.mark.parametrize("path", ["/api/ml/summary", "/api/ml/forecast", "/api/ml/anomalies", "/api/ml/correlations"])
def test_results_need_a_login(client, path):
    assert client.get(path).status_code == 401


def test_summary_shows_the_newest_run_and_scores_each_run(client):
    body = client.get("/api/ml/summary", headers=sign_in(client, ANALYST)).json()
    assert body["latest"]["version"] == "new"
    assert [row["version"] for row in body["history"]] == ["new", "old"]
    assert body["history"][0]["global_test_rmse"] == 0.2
    assert body["history"][0]["global_baseline_rmse"] == 0.3
    assert body["history"][0]["series_beating_baseline"] == 1
    assert body["latest"]["trained_at"].endswith("Z") or body["latest"]["trained_at"].endswith("+00:00")


def test_forecast_for_an_unknown_series_is_not_found(client):
    headers = sign_in(client, ANALYST)
    assert client.get("/api/ml/forecast?series=Glob", headers=headers).json()["series"] == "Glob"
    assert client.get("/api/ml/forecast?series=Mars", headers=headers).status_code == 404


def test_anomalies_come_back_worst_first_and_limited(client):
    rows = client.get("/api/ml/anomalies?limit=1", headers=sign_in(client, ANALYST)).json()
    assert [row["date"] for row in rows] == ["high"]


def test_analyst_cannot_retrain(client):
    with mock.patch.object(ml_client, "start_training") as start:
        response = client.post("/api/ml/retrain", headers=sign_in(client, ANALYST))
    assert response.status_code == 403
    start.assert_not_called()


def test_admin_retrain_starts_once_and_a_second_is_refused(client):
    headers = sign_in(client, ADMIN)
    release = mock.Mock(side_effect=lambda username: None)
    with mock.patch.object(ml_client, "_run_training", release):
        assert client.post("/api/ml/retrain", headers=headers).status_code == 202
        assert client.post("/api/ml/retrain", headers=headers).status_code == 409
        assert client.get("/api/ml/summary", headers=headers).json()["retraining"] is True
    locks.release(ml_client.LOCK)
    release.assert_called_once_with("Admin")


def finished_training(returncode, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout="", stderr=stderr)


def test_training_uses_this_database_and_reports_success(client):
    locks.acquire(ml_client.LOCK, 60)
    with mock.patch.object(ml_client.subprocess, "run", return_value=finished_training(0)) as run, \
            mock.patch.object(ml_client, "notify") as notify:
        ml_client._run_training("Admin")
    assert run.call_args.kwargs["env"]["MONGO_DB"] == "earthscape_test"
    assert "Admin" in notify.call_args.args[0]
    assert not ml_client.is_running()


def test_failed_training_reports_the_error_and_frees_the_lock(client):
    locks.acquire(ml_client.LOCK, 60)
    with mock.patch.object(ml_client.subprocess, "run", return_value=finished_training(1, "Traceback\nValueError: bad")), \
            mock.patch.object(ml_client, "notify") as notify:
        ml_client._run_training("Admin")
    assert "ValueError: bad" in notify.call_args.args[0]
    assert not ml_client.is_running()


def test_missing_python_reports_the_error_and_frees_the_lock(client):
    locks.acquire(ml_client.LOCK, 60)
    with mock.patch.object(ml_client.subprocess, "run", side_effect=FileNotFoundError("no python")), \
            mock.patch.object(ml_client, "notify") as notify:
        ml_client._run_training("Admin")
    assert "no python" in notify.call_args.args[0]
    assert not ml_client.is_running()
