"""Shared test setup. Every test starts on an empty earthscape_test database."""
import functools
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from accounts.auth import hash_password
from dashboard import cluster
from earthscape.crypto import email_fields
from earthscape.db import client, db, ensure_indexes

ADMIN = ("admin@test.example", "admin-password-1")
ANALYST = ("analyst@test.example", "analyst-password-1")
OFFLINE = {"hdfs_online": False, "yarn_online": False}


@functools.lru_cache(maxsize=None)
def password_hash(password):
    """Hash once, reuse."""
    return hash_password(password)


def add_user(name, credentials, role, **fields):
    document = {"name": name, **email_fields(credentials[0]), "role": role, "active": True,
                "password_hash": password_hash(credentials[1])}
    document.update(fields)
    return db.users.insert_one(document).inserted_id


class MongoTestCase(TestCase):
    """Clean database, Hadoop offline."""
    with_users = True

    def setUp(self):
        # Never the real data
        assert db.name == "earthscape_test"
        client.drop_database("earthscape_test")
        cache.clear()
        ensure_indexes()
        # No real Hadoop calls
        for name, value in (("cluster_status", OFFLINE), ("list_jobs", None), ("hdfs_size", None)):
            patcher = mock.patch.object(cluster, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        if self.with_users:
            self.admin_id = add_user("Admin", ADMIN, "Admin")
            self.analyst_id = add_user("Analyst", ANALYST, "Analyst")

    @classmethod
    def tearDownClass(cls):
        client.drop_database("earthscape_test")
        super().tearDownClass()

    # Sign-in helpers

    def login(self, email, password, role="Analyst", **extra):
        return self.client.post("/login/", {"email": email, "password": password, "role": role}, **extra)

    def sign_in(self, credentials):
        """Signed in, or fails."""
        role = "Admin" if credentials == ADMIN else "Analyst"
        response = self.login(credentials[0], credentials[1], role)
        self.assertEqual(response.status_code, 302, "sign-in failed for %s" % credentials[0])
        return response

    def messages_in(self, response):
        return [str(message) for message in response.context["messages"]] if response.context else []

    def follow_messages(self, response):
        """Messages after redirect."""
        self.assertEqual(response.status_code, 302)
        return self.messages_in(self.client.get(response["Location"]))
