"""Sign-up: a request for an Analyst account that an Admin has to approve."""
import os

os.environ["MONGO_DB"] = "earthscape_test"
os.environ["JWT_SECRET"] = "test-secret-only-used-by-the-test-suite-0123456789"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import login_limit  # noqa: E402
from app.db import client as mongo_client  # noqa: E402
from app.db import db  # noqa: E402
from app.field_crypto import email_fields  # noqa: E402
from app.main import app  # noqa: E402
from app.security import hash_password  # noqa: E402

ADMIN = ("admin@test.example", "admin-password-1")
NEW = {"name": "Sara Khan", "title": "Researcher", "email": "Sara@Test.example", "password": "a-long-password"}


@pytest.fixture()
def client():
    assert db.name == "earthscape_test"
    mongo_client.drop_database("earthscape_test")
    db.users.insert_one({"name": "Admin", **email_fields(ADMIN[0]), "role": "Admin", "active": True, "password_hash": hash_password(ADMIN[1])})
    with TestClient(app) as test_client:
        yield test_client
    mongo_client.drop_database("earthscape_test")


def sign_in(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_a_new_account_waits_for_approval_and_tells_the_admin(client):
    response = client.post("/api/auth/signup", json=NEW)
    assert response.status_code == 202 and "Admin will review" in response.json()["message"]
    user = db.users.find_one({"name": "Sara Khan"})
    assert user["role"] == "Analyst" and user["active"] is False and user["pending"] is True
    assert user["password_hash"] != NEW["password"]
    admin = db.users.find_one({"role": "Admin"})
    assert db.notifications.find_one({"user_id": str(admin["_id"])})["text"].startswith("Sara Khan asked")


def test_a_waiting_account_cant_sign_in_but_hears_why(client):
    client.post("/api/auth/signup", json=NEW)
    waiting = sign_in(client, "sara@test.example", NEW["password"])
    assert waiting.status_code == 403 and "waiting for an Admin" in waiting.json()["detail"]
    wrong = sign_in(client, "sara@test.example", "not-the-password")
    assert wrong.status_code == 401 and "waiting" not in wrong.json()["detail"]


def test_an_admin_approves_it_by_turning_it_on(client):
    client.post("/api/auth/signup", json=NEW)
    token = sign_in(client, *ADMIN).json()["token"]
    headers = {"Authorization": "Bearer " + token}
    waiting = next(user for user in client.get("/api/users", headers=headers).json() if user["name"] == "Sara Khan")
    assert waiting["pending"] is True
    assert client.patch("/api/users/" + waiting["id"], json={"active": True}, headers=headers).json()["pending"] is False
    approved = sign_in(client, "sara@test.example", NEW["password"])
    assert approved.status_code == 200 and approved.json()["user"]["role"] == "Analyst"


def test_a_taken_email_gets_the_same_answer_and_changes_nothing(client):
    taken = client.post("/api/auth/signup", json=dict(NEW, email=ADMIN[0], name="Someone"))
    assert taken.status_code == 202 and taken.json() == client.post("/api/auth/signup", json=NEW).json()
    admin = db.users.find_one({"role": "Admin"})
    assert admin["name"] == "Admin" and admin["active"] is True
    assert sign_in(client, *ADMIN).status_code == 200


@pytest.mark.parametrize("changes", [{"email": "not-an-email"}, {"password": "short"}, {"name": ""}, {"role": "Admin"}])
def test_bad_requests_are_refused_or_cant_choose_a_role(client, changes):
    response = client.post("/api/auth/signup", json=dict(NEW, **changes))
    if "role" in changes:
        assert db.users.find_one({"name": "Sara Khan"})["role"] == "Analyst"
    else:
        assert response.status_code == 422


def test_one_address_can_only_ask_a_few_times_an_hour(client):
    for number in range(login_limit.MAX_SIGNUPS_PER_ADDRESS):
        assert client.post("/api/auth/signup", json=dict(NEW, email="person%d@test.example" % number)).status_code == 202
    assert client.post("/api/auth/signup", json=dict(NEW, email="one-more@test.example")).status_code == 429


def test_the_admin_tab_only_lets_admins_in_and_the_analyst_tab_only_analysts(client):
    db.users.insert_one({"name": "Ana", **email_fields("ana@test.example"), "role": "Analyst", "active": True, "password_hash": hash_password("analyst-password-1")})
    admin_on_admin = client.post("/api/auth/login", json={"email": ADMIN[0], "password": ADMIN[1], "role": "Admin"})
    analyst_on_admin = client.post("/api/auth/login", json={"email": "ana@test.example", "password": "analyst-password-1", "role": "Admin"})
    admin_on_analyst = client.post("/api/auth/login", json={"email": ADMIN[0], "password": ADMIN[1], "role": "Analyst"})
    wrong_on_admin = client.post("/api/auth/login", json={"email": "ana@test.example", "password": "nope", "role": "Admin"})
    assert admin_on_admin.status_code == 200
    assert analyst_on_admin.status_code == 403 and "Use the Analyst sign-in" in analyst_on_admin.json()["detail"]
    assert admin_on_analyst.status_code == 403 and "Use the Admin sign-in" in admin_on_analyst.json()["detail"]
    assert wrong_on_admin.status_code == 401 and "Analyst" not in wrong_on_admin.json()["detail"]
