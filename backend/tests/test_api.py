"""API tests against a separate database, so they never touch real data."""
import io
import os
from unittest import mock

os.environ["MONGO_DB"] = "earthscape_test"
os.environ["JWT_SECRET"] = "test-secret-only-used-by-the-test-suite-0123456789"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import hadoop_client  # noqa: E402
from app.db import client as mongo_client  # noqa: E402
from app.db import db  # noqa: E402
from app.main import app  # noqa: E402
from app.security import hash_password  # noqa: E402

ADMIN = ("admin@test.example", "admin-password-1")
ANALYST = ("analyst@test.example", "analyst-password-1")


@pytest.fixture(scope="module")
def client():
    assert db.name == "earthscape_test"
    mongo_client.drop_database("earthscape_test")
    db.users.insert_many([
        {"name": "Admin", "email": ADMIN[0], "role": "Admin", "active": True,
         "password_hash": hash_password(ADMIN[1])},
        {"name": "Analyst", "email": ANALYST[0], "role": "Analyst", "active": True,
         "password_hash": hash_password(ANALYST[1])},
    ])
    db.gistemp_global.insert_many([{"Year": 2023, "J-D": 1.17}, {"Year": 2026, "J-D": None}])
    db.co2_annual.insert_one({"year": 2023, "mean": 421.0, "unc": 0.1})
    db.air_quality_monthly.insert_many([
        {"location_id": "1", "location": "A", "lat": 1.0, "lon": 2.0, "parameter": "pm25", "units": "x",
         "year": 2023, "month": 12, "mean": 5.0, "max": 9.0, "readings": 10, "rejected": 0},
        {"location_id": "1", "location": "A", "lat": 1.0, "lon": 2.0, "parameter": "pm25", "units": "x",
         "year": 2024, "month": 1, "mean": 99.0, "max": 99.0, "readings": 1, "rejected": 0},
    ])
    with TestClient(app) as test_client:
        yield test_client
    mongo_client.drop_database("earthscape_test")


def sign_in(client, credentials):
    response = client.post("/api/auth/login", json={"email": credentials[0], "password": credentials[1]})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["token"]}


def test_wrong_password_and_unknown_email_look_the_same(client):
    wrong = client.post("/api/auth/login", json={"email": ADMIN[0], "password": "nope"})
    unknown = client.post("/api/auth/login", json={"email": "who@test.example", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_login_never_returns_the_password_hash(client):
    response = client.post("/api/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]})
    assert "password_hash" not in response.text


@pytest.mark.parametrize("path", [
    "/api/overview", "/api/users", "/api/jobs", "/api/datasets", "/api/alerts", "/api/tickets",
    "/api/reports/co2", "/api/auth/me", "/api/notifications",
])
def test_data_needs_a_login(client, path):
    assert client.get(path).status_code == 401


def test_forged_token_is_rejected(client):
    response = client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.token"})
    assert response.status_code == 401


def test_sign_out_kills_the_token(client):
    headers = sign_in(client, ANALYST)
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401


@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/users", {"name": "X", "email": "x@test.example", "role": "Admin", "password": "long-enough-pass"}),
    ("post", "/api/alert-rules", {"name": "X", "metric": "co2", "threshold": 1, "severity": "Low"}),
    ("post", "/api/jobs/data_quality/run", None),
    ("patch", "/api/tickets/000000000000000000000000", {"status": "Closed"}),
    ("delete", "/api/alert-rules/000000000000000000000000", None),
    ("patch", "/api/users/000000000000000000000000", {"role": "Admin"}),
])
def test_analyst_is_refused_admin_actions(client, method, path, body):
    headers = sign_in(client, ANALYST)
    kwargs = {"json": body} if body is not None else {}
    assert getattr(client, method)(path, headers=headers, **kwargs).status_code == 403


def test_analyst_cannot_upload(client):
    headers = sign_in(client, ANALYST)
    files = {"file": ("a.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")}
    assert client.post("/api/datasets", headers=headers, files=files).status_code == 403


def test_disabled_user_loses_access_immediately(client):
    admin = sign_in(client, ADMIN)
    created = client.post("/api/users", headers=admin, json={
        "name": "Temp", "email": "Temp@Test.example", "role": "Analyst", "password": "temp-password-1"})
    assert created.status_code == 201
    assert created.json()["email"] == "temp@test.example"
    temp = sign_in(client, ("temp@test.example", "temp-password-1"))
    assert client.patch("/api/users/" + created.json()["id"], headers=admin, json={"active": False}).status_code == 200
    assert client.get("/api/auth/me", headers=temp).status_code == 401
    refused = client.post("/api/auth/login", json={"email": "temp@test.example", "password": "temp-password-1"})
    assert refused.status_code == 401


def test_duplicate_email_is_refused(client):
    admin = sign_in(client, ADMIN)
    response = client.post("/api/users", headers=admin, json={
        "name": "Dup", "email": ADMIN[0], "role": "Analyst", "password": "long-enough-pass"})
    assert response.status_code == 409


def test_admin_cannot_lock_themselves_out(client):
    admin = sign_in(client, ADMIN)
    me = client.get("/api/auth/me", headers=admin).json()
    response = client.patch("/api/users/" + me["id"], headers=admin, json={"role": "Analyst"})
    assert response.status_code == 400


def test_password_change_needs_the_current_password(client):
    headers = sign_in(client, ANALYST)
    refused = client.post("/api/auth/password", headers=headers, json={
        "current_password": "wrong", "new_password": "a-new-long-password"})
    assert refused.status_code == 400


def test_profile_changes_are_saved(client):
    headers = sign_in(client, ANALYST)
    client.patch("/api/auth/me", headers=headers, json={"name": "Renamed", "title": "Lead"})
    assert client.get("/api/auth/me", headers=headers).json()["name"] == "Renamed"


def test_overview_skips_the_incomplete_year(client):
    with mock.patch.object(hadoop_client, "cluster_status", return_value={}):
        body = client.get("/api/overview", headers=sign_in(client, ANALYST)).json()
    assert body["temperature"]["Year"] == 2023


def test_air_quality_ignores_the_2024_spillover(client):
    body = client.get("/api/air-quality", headers=sign_in(client, ANALYST)).json()
    assert body[0]["pollutants"]["pm25"]["mean"] == 5.0


def test_report_downloads_real_csv(client):
    response = client.get("/api/reports/co2?format=csv", headers=sign_in(client, ANALYST))
    assert response.status_code == 200
    assert response.text.splitlines() == ["year,mean,unc", "2023,421.0,0.1"]
    assert "attachment" in response.headers["content-disposition"]


def test_geojson_only_for_reports_with_coordinates(client):
    headers = sign_in(client, ANALYST)
    assert client.get("/api/reports/co2?format=geojson", headers=headers).status_code == 422
    body = client.get("/api/reports/air_quality?format=geojson", headers=headers).json()
    assert body["features"][0]["geometry"]["coordinates"] == [2.0, 1.0]
    assert len(body["features"]) == 1


def test_analyst_sees_only_their_own_tickets(client):
    analyst, admin = sign_in(client, ANALYST), sign_in(client, ADMIN)
    client.post("/api/tickets", headers=admin, json={"category": "Feedback", "description": "admin's"})
    mine = client.post("/api/tickets", headers=analyst, json={"category": "Feedback", "description": "mine"})
    assert mine.status_code == 201
    seen = client.get("/api/tickets", headers=analyst).json()
    assert [ticket["description"] for ticket in seen] == ["mine"]
    assert len(client.get("/api/tickets", headers=admin).json()) == 2


def test_closing_a_ticket_notifies_only_its_owner(client):
    analyst, admin = sign_in(client, ANALYST), sign_in(client, ADMIN)
    ticket = client.get("/api/tickets", headers=analyst).json()[0]
    assert client.patch("/api/tickets/" + ticket["id"], headers=admin, json={"status": "Closed"}).status_code == 200
    assert any("Closed" in n["text"] for n in client.get("/api/notifications", headers=analyst).json())
    assert not any("Closed" in n["text"] for n in client.get("/api/notifications", headers=admin).json())


def test_alert_rule_does_not_invent_an_alert(client):
    admin = sign_in(client, ADMIN)
    response = client.post("/api/alert-rules", headers=admin, json={
        "name": "High CO2", "metric": "co2", "threshold": 430, "severity": "High"})
    assert response.status_code == 201
    assert client.get("/api/alerts", headers=admin).json() == []


@pytest.mark.parametrize("filename,content,status", [
    ("data.exe", b"MZ", 422),
    ("empty.csv", b"", 422),
    ("binary.csv", b"\x00\x01\x02", 422),
    ("fake.nc", b"this is not netcdf", 422),
])
def test_bad_uploads_are_refused(client, filename, content, status):
    files = {"file": (filename, io.BytesIO(content), "application/octet-stream")}
    assert client.post("/api/datasets", headers=sign_in(client, ADMIN), files=files).status_code == status


def test_good_upload_is_stored_under_a_safe_name(client):
    files = {"file": ("../../evil name.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")}
    with mock.patch.object(hadoop_client, "put_file") as put:
        response = client.post("/api/datasets", headers=sign_in(client, ADMIN), files=files)
    assert response.status_code == 201
    assert response.json()["name"] == "evil_name.csv"
    assert put.call_args[0][1] == "/climate/raw/uploads"


def test_unknown_job_id_is_not_passed_to_yarn(client):
    with mock.patch.object(hadoop_client, "get_job") as get_job:
        response = client.get("/api/jobs/../../secret", headers=sign_in(client, ANALYST))
    assert response.status_code == 404
    get_job.assert_not_called()
