"""Sign-in, sign-up, limits, encryption, users and the seed command."""
import datetime
import io
import re
import tempfile
from pathlib import Path
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.test import Client

from earthscape import config
from earthscape.crypto import decrypt, email_lookup, encrypt
from earthscape.db import db, encrypt_existing_fields
from earthscape.testing import ADMIN, ANALYST, MongoTestCase, add_user, password_hash

from . import auth

NEW = {"name": "Sara Khan", "title": "Researcher", "email": "Sara@Test.example",
       "password": "a-long-password", "confirm": "a-long-password"}


def errors_of(response):
    return response.context["form_errors"]


#----------------------------sign in--------------------------------------

class SignInTests(MongoTestCase):

    def test_wrong_password_and_unknown_email_look_the_same(self):
        wrong = self.login(ADMIN[0], "nope", "Admin")
        unknown = self.login("who@test.example", "nope", "Admin")
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(unknown.status_code, 401)
        self.assertEqual(errors_of(wrong), errors_of(unknown))

    def test_sign_in_page_never_shows_the_password_hash(self):
        response = self.login(ADMIN[0], "nope", "Admin")
        self.assertNotIn("password_hash", response.content.decode())
        self.assertNotIn("$2b$", response.content.decode())

    def test_pages_need_a_login(self):
        for path in ["/dashboard/", "/dashboard/overview/", "/dashboard/users/", "/dashboard/hadoop/",
                     "/dashboard/data/", "/dashboard/alerts/", "/dashboard/support/", "/dashboard/status/",
                     "/dashboard/reports/download/?report=co2", "/dashboard/settings/", "/dashboard/ml/"]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302, path)
            self.assertTrue(response["Location"].startswith("/login/?next="), path)

    def test_sign_in_goes_to_the_page_asked_for_but_never_off_site(self):
        response = self.client.post("/login/", {"email": ANALYST[0], "password": ANALYST[1], "role": "Analyst",
                                                "next": "/dashboard/alerts/"})
        self.assertEqual(response["Location"], "/dashboard/alerts/")
        self.client.post("/logout/")
        response = self.client.post("/login/", {"email": ANALYST[0], "password": ANALYST[1], "role": "Analyst",
                                                "next": "https://evil.example/"})
        self.assertEqual(response["Location"], "/dashboard/")

    def test_sign_out_ends_the_session(self):
        self.sign_in(ANALYST)
        self.assertEqual(self.client.get("/dashboard/").status_code, 200)
        self.assertEqual(self.client.post("/logout/").status_code, 302)
        self.assertEqual(self.client.get("/dashboard/").status_code, 302)

    def test_sign_out_needs_a_post(self):
        self.sign_in(ANALYST)
        self.assertEqual(self.client.get("/logout/").status_code, 405)

    def test_forms_need_the_csrf_token(self):
        strict = Client(enforce_csrf_checks=True)
        response = strict.post("/login/", {"email": ANALYST[0], "password": ANALYST[1], "role": "Analyst"})
        self.assertEqual(response.status_code, 403)

    def test_each_tab_only_lets_its_own_role_in(self):
        self.assertEqual(self.login(ADMIN[0], ADMIN[1], "Admin").status_code, 302)
        self.client.post("/logout/")
        analyst_on_admin = self.login(ANALYST[0], ANALYST[1], "Admin")
        admin_on_analyst = self.login(ADMIN[0], ADMIN[1], "Analyst")
        wrong_on_admin = self.login(ANALYST[0], "nope", "Admin")
        self.assertIn("Use the Analyst sign-in", errors_of(analyst_on_admin)[0])
        self.assertIn("Use the Admin sign-in", errors_of(admin_on_analyst)[0])
        self.assertNotIn("Analyst", errors_of(wrong_on_admin)[0])
        self.assertEqual(self.client.get("/dashboard/").status_code, 302)

    def test_the_admin_tab_link_shows_the_admin_form(self):
        self.assertContains(self.client.get("/login/?role=admin"), "Sign in as Admin")
        self.assertContains(self.client.get("/login/"), "Sign in as Analyst")


#----------------------------sign-in limits--------------------------------------

class LimitTests(MongoTestCase):

    def test_account_is_blocked_after_repeated_failures_even_with_the_right_password(self):
        for _ in range(auth.MAX_FAILURES_PER_ACCOUNT):
            self.assertEqual(self.login(ANALYST[0], "wrong").status_code, 401)
        blocked = self.login(*ANALYST)
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked["Retry-After"], str(auth.WINDOW_MINUTES * 60))

    def test_unknown_emails_are_limited_the_same_way(self):
        for _ in range(auth.MAX_FAILURES_PER_ACCOUNT):
            self.assertEqual(self.login("who@test.example", "wrong").status_code, 401)
        self.assertEqual(self.login("who@test.example", "wrong").status_code, 429)

    def test_one_person_being_guessed_at_does_not_block_someone_else(self):
        for _ in range(auth.MAX_FAILURES_PER_ACCOUNT):
            self.login(ANALYST[0], "wrong")
        self.assertEqual(self.login(ADMIN[0], ADMIN[1], "Admin").status_code, 302)

    def test_same_email_from_another_address_is_not_blocked(self):
        for _ in range(auth.MAX_FAILURES_PER_ACCOUNT):
            auth.record_failure(ANALYST[0], "10.0.0.1")
        self.assertTrue(auth.login_blocked(ANALYST[0], "10.0.0.1"))
        self.assertFalse(auth.login_blocked(ANALYST[0], "10.0.0.2"))

    def test_one_address_trying_many_accounts_is_blocked(self):
        for number in range(auth.MAX_FAILURES_PER_ADDRESS):
            auth.record_failure("person%d@test.example" % number, "10.0.0.9")
        self.assertTrue(auth.login_blocked("new@test.example", "10.0.0.9"))

    def test_successful_sign_in_resets_the_count(self):
        for _ in range(auth.MAX_FAILURES_PER_ACCOUNT - 1):
            self.login(ANALYST[0], "wrong")
        self.assertEqual(self.login(*ANALYST).status_code, 302)
        self.client.post("/logout/")
        self.assertEqual(self.login(ANALYST[0], "wrong").status_code, 401)
        self.assertEqual(self.login(*ANALYST).status_code, 302)

    def test_block_ends_when_the_window_ends(self):
        for _ in range(auth.MAX_FAILURES_PER_ACCOUNT):
            self.login(ANALYST[0], "wrong")
        db.login_failures.update_many({}, {"$set": {"expires_at": datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)}})
        self.assertEqual(self.login(*ANALYST).status_code, 302)

    def test_apache_can_name_the_visitor_but_nobody_else_can(self):
        for _ in range(auth.MAX_FAILURES_PER_ACCOUNT):
            self.login(ANALYST[0], "wrong", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="10.1.1.1")
        # Another visitor through Apache
        self.assertEqual(self.login(*ANALYST, REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="10.1.1.2").status_code, 302)
        self.assertTrue(auth.login_blocked(ANALYST[0], "10.1.1.1"))
        # Forged header ignored
        self.client.post("/logout/")
        for _ in range(auth.MAX_FAILURES_PER_ACCOUNT):
            self.login(ADMIN[0], "wrong", "Admin", REMOTE_ADDR="10.5.5.5", HTTP_X_FORWARDED_FOR="10.9.9.9")
        self.assertTrue(auth.login_blocked(ADMIN[0], "10.5.5.5"))


#----------------------------sign up--------------------------------------

class SignUpTests(MongoTestCase):

    def test_a_new_account_waits_for_approval_and_tells_the_admin(self):
        response = self.client.post("/signup/", NEW)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Admin will review")
        user = db.users.find_one({"name": "Sara Khan"})
        self.assertEqual((user["role"], user["active"], user["pending"]), ("Analyst", False, True))
        self.assertNotEqual(user["password_hash"], NEW["password"])
        self.assertEqual(decrypt(user["email_enc"]), "sara@test.example")
        note = db.notifications.find_one({"user_id": str(self.admin_id)})
        self.assertTrue(note["text"].startswith("Sara Khan asked"))

    def test_a_waiting_account_cant_sign_in_but_hears_why(self):
        self.client.post("/signup/", NEW)
        waiting = self.login("sara@test.example", NEW["password"])
        self.assertEqual(waiting.status_code, 401)
        self.assertIn("waiting for an Admin", errors_of(waiting)[0])
        wrong = self.login("sara@test.example", "not-the-password")
        self.assertNotIn("waiting", errors_of(wrong)[0])

    def test_an_admin_approves_it_by_turning_it_on(self):
        self.client.post("/signup/", NEW)
        self.sign_in(ADMIN)
        users = self.client.get("/dashboard/users/").context["users"]
        waiting = next(user for user in users if user["name"] == "Sara Khan")
        self.assertTrue(waiting["pending"])
        # Waiting requests first
        self.assertEqual(users[0]["name"], "Sara Khan")
        self.client.post("/dashboard/users/%s/" % waiting["id"], {"action": "enable"})
        self.assertFalse(db.users.find_one({"name": "Sara Khan"})["pending"])
        self.client.post("/logout/")
        self.assertEqual(self.login("sara@test.example", NEW["password"]).status_code, 302)

    def test_a_taken_email_gets_the_same_answer_and_changes_nothing(self):
        taken = self.client.post("/signup/", dict(NEW, email=ADMIN[0], name="Someone"))
        fresh = self.client.post("/signup/", NEW)
        self.assertEqual(taken.context["msg"], fresh.context["msg"])
        admin = db.users.find_one({"_id": self.admin_id})
        self.assertEqual((admin["name"], admin["active"]), ("Admin", True))
        self.assertEqual(self.login(ADMIN[0], ADMIN[1], "Admin").status_code, 302)

    def test_bad_requests_are_refused(self):
        for changes in ({"email": "not-an-email"}, {"password": "short", "confirm": "short"},
                        {"name": ""}, {"confirm": "something-else"}):
            response = self.client.post("/signup/", dict(NEW, **changes))
            self.assertTrue(errors_of(response), changes)
            # Typed values kept
            self.assertEqual(response.context["form_data"]["title"], "Researcher")
        self.assertIsNone(db.users.find_one({"name": "Sara Khan"}))

    def test_the_role_cant_be_chosen(self):
        self.client.post("/signup/", dict(NEW, role="Admin"))
        self.assertEqual(db.users.find_one({"name": "Sara Khan"})["role"], "Analyst")

    def test_one_address_can_only_ask_a_few_times_an_hour(self):
        for number in range(auth.MAX_SIGNUPS_PER_ADDRESS):
            response = self.client.post("/signup/", dict(NEW, email="person%d@test.example" % number))
            self.assertTrue(response.context["done"])
        self.assertEqual(self.client.post("/signup/", dict(NEW, email="one-more@test.example")).status_code, 429)


#----------------------------users and settings--------------------------------------

class UserTests(MongoTestCase):

    def test_analyst_is_refused_admin_actions(self):
        self.sign_in(ANALYST)
        zero = "000000000000000000000000"
        actions = [
            ("/dashboard/users/new/", {"name": "X", "email": "x@test.example", "role": "Admin", "password": "long-enough-pass"}),
            ("/dashboard/users/%s/" % zero, {"action": "Admin"}),
            ("/dashboard/alerts/rules/new/", {"name": "X", "metric": "co2", "threshold": "1", "severity": "Low"}),
            ("/dashboard/alerts/rules/%s/delete/" % zero, {}),
            ("/dashboard/hadoop/run/data_quality/", {}),
            ("/dashboard/support/%s/" % zero, {"status": "Closed"}),
            ("/dashboard/monitor/poll/", {}),
            ("/dashboard/ml/retrain/", {}),
            ("/dashboard/status/maintenance/", {"active": "on", "message": "x"}),
            ("/dashboard/data/upload/", {"file": io.BytesIO(b"a,b\n1,2\n")}),
        ]
        with mock.patch("dashboard.cluster.start_job") as start_job, mock.patch("dashboard.cluster.start_training") as train:
            for path, body in actions:
                self.assertEqual(self.client.post(path, body).status_code, 403, path)
        start_job.assert_not_called()
        train.assert_not_called()
        self.assertEqual(db.users.count_documents({}), 2)
        self.assertEqual(db.alert_rules.count_documents({}), 0)

    def test_disabled_user_loses_access_immediately(self):
        self.sign_in(ADMIN)
        self.client.post("/dashboard/users/new/", {"name": "Temp", "email": "Temp@Test.example", "role": "Analyst",
                                                   "password": "temp-password-1"})
        temp = db.users.find_one({"name": "Temp"})
        self.assertEqual(decrypt(temp["email_enc"]), "temp@test.example")

        other = Client()
        self.assertEqual(other.post("/login/", {"email": "temp@test.example", "password": "temp-password-1",
                                                "role": "Analyst"}).status_code, 302)
        self.client.post("/dashboard/users/%s/" % temp["_id"], {"action": "disable"})
        self.assertEqual(other.get("/dashboard/").status_code, 302)
        refused = other.post("/login/", {"email": "temp@test.example", "password": "temp-password-1", "role": "Analyst"})
        self.assertEqual(refused.status_code, 401)

    def test_role_change_takes_effect_immediately(self):
        other = Client()
        other.post("/login/", {"email": ANALYST[0], "password": ANALYST[1], "role": "Analyst"})
        self.assertEqual(other.post("/dashboard/status/maintenance/", {"message": "x"}).status_code, 403)
        self.sign_in(ADMIN)
        self.client.post("/dashboard/users/%s/" % self.analyst_id, {"action": "Admin"})
        self.assertEqual(other.post("/dashboard/status/maintenance/", {"message": "x"}).status_code, 302)

    def test_duplicate_email_is_refused(self):
        self.sign_in(ADMIN)
        response = self.client.post("/dashboard/users/new/", {"name": "Dup", "email": ANALYST[0], "role": "Analyst",
                                                              "password": "long-enough-pass"})
        self.assertIn("already exists", self.follow_messages(response)[0])
        self.assertEqual(db.users.count_documents({}), 2)

    def test_admin_cannot_change_their_own_account(self):
        self.sign_in(ADMIN)
        response = self.client.post("/dashboard/users/%s/" % self.admin_id, {"action": "Analyst"})
        self.assertIn("can't change your own", self.follow_messages(response)[0])
        self.assertEqual(db.users.find_one({"_id": self.admin_id})["role"], "Admin")

    def test_password_change_needs_the_current_password(self):
        self.sign_in(ANALYST)
        response = self.client.post("/dashboard/settings/", {"current_password": "wrong", "new_password": "a-new-long-password"})
        self.assertIn("incorrect", self.follow_messages(response)[0])
        self.client.post("/dashboard/settings/", {"current_password": ANALYST[1], "new_password": "a-new-long-password"})
        self.assertTrue(auth.verify_password("a-new-long-password", db.users.find_one({"_id": self.analyst_id})["password_hash"]))

    def test_profile_changes_are_saved(self):
        self.sign_in(ANALYST)
        self.client.post("/dashboard/settings/", {"form": "profile", "name": "Renamed", "title": "Lead"})
        user = db.users.find_one({"_id": self.analyst_id})
        self.assertEqual((user["name"], user["title"]), ("Renamed", "Lead"))
        self.assertContains(self.client.get("/dashboard/settings/"), "Renamed")


#----------------------------encryption--------------------------------------

class EncryptionTests(MongoTestCase):

    def test_emails_and_tickets_are_unreadable_in_the_database(self):
        self.sign_in(ANALYST)
        self.client.post("/dashboard/support/", {"category": "Feedback", "description": "Private note"})
        self.assertNotIn("Private note", str(db.tickets.find_one()))
        self.assertEqual(self.client.get("/dashboard/support/").context["tickets"][0]["description"], "Private note")
        stored = db.users.find_one({"email_lookup": email_lookup(ANALYST[0])})
        self.assertNotIn(ANALYST[0], str(stored))

    def test_encrypting_the_same_text_twice_gives_different_results(self):
        self.assertNotEqual(encrypt("same"), encrypt("same"))
        self.assertEqual(decrypt(encrypt("same")), "same")

    def test_existing_plain_records_are_converted_and_conversion_is_repeatable(self):
        user_id = db.users.insert_one({"name": "Old", "email": "old@test.example", "role": "Analyst", "active": True,
                                       "password_hash": password_hash("old-password-1")}).inserted_id
        ticket_id = db.tickets.insert_one({"category": "Feedback", "description": "Old note", "created_by": "x"}).inserted_id
        encrypt_existing_fields()
        encrypt_existing_fields()
        user = db.users.find_one({"_id": user_id})
        self.assertNotIn("email", user)
        self.assertEqual(decrypt(user["email_enc"]), "old@test.example")
        ticket = db.tickets.find_one({"_id": ticket_id})
        self.assertNotIn("description", ticket)
        self.assertEqual(decrypt(ticket["description_enc"]), "Old note")
        self.assertEqual(self.login("old@test.example", "old-password-1").status_code, 302)


#----------------------------seed command--------------------------------------

class SeedTests(MongoTestCase):
    with_users = False

    def setUp(self):
        super().setUp()
        folder = Path(tempfile.mkdtemp())
        self.env_file = folder / ".env"
        self.env_file.write_text("SECRET_KEY=test\nENCRYPTION_KEY=%s\n" % config.ENCRYPTION_KEY, encoding="utf-8")
        # Throwaway .env, keys restored
        for name, value in (("ENV_FILE", self.env_file), ("SECRET_KEY", config.SECRET_KEY),
                            ("ENCRYPTION_KEY", config.ENCRYPTION_KEY)):
            patcher = mock.patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def seed(self, *args):
        output = io.StringIO()
        call_command("seed", *args, stdout=output)
        return output.getvalue()

    def admin(self):
        return db.users.find_one({"role": "Admin"})

    def test_seed_creates_both_accounts_and_the_starter_rules_once(self):
        self.seed()
        self.assertEqual(db.users.count_documents({}), 2)
        self.assertEqual(db.alert_rules.count_documents({}), 4)
        self.assertIn("Already exists", self.seed())
        self.assertEqual(db.users.count_documents({}), 2)
        self.assertEqual(db.alert_rules.count_documents({}), 4)

    def test_reset_sets_a_new_password_and_prints_it_once(self):
        first = re.search(r"admin@earthscape\.test with password (\S+)", self.seed()).group(1)
        output = self.seed("--reset-password", "admin")
        second = re.search(r"New password for admin@earthscape\.test .*:\n(\S+)\n", output).group(1)
        self.assertNotEqual(first, second)
        self.assertTrue(auth.verify_password(second, self.admin()["password_hash"]))
        self.assertFalse(auth.verify_password(first, self.admin()["password_hash"]))
        self.assertNotIn("PASSWORD", self.env_file.read_text(encoding="utf-8"))

    def test_reset_before_setup_says_to_run_the_seed(self):
        with self.assertRaisesMessage(CommandError, "Run python manage.py seed first"):
            self.seed("--reset-password", "admin")

    def test_reset_rejects_other_arguments(self):
        with self.assertRaises(CommandError):
            self.seed("--reset-password", "root")

    def test_passwords_in_the_env_file_are_dropped(self):
        self.env_file.write_text(self.env_file.read_text(encoding="utf-8") + "SEED_ADMIN_PASSWORD=plain\n", encoding="utf-8")
        self.seed()
        self.assertNotIn("plain", self.env_file.read_text(encoding="utf-8"))
