"""The seed script's password reset, run against the test database and a throwaway .env file."""
import os
import re

os.environ["MONGO_DB"] = "earthscape_test"
os.environ["JWT_SECRET"] = "test-secret-only-used-by-the-test-suite-0123456789"

import pytest  # noqa: E402

import seed  # noqa: E402
from app import config  # noqa: E402
from app.db import client as mongo_client  # noqa: E402
from app.db import db  # noqa: E402
from app.security import verify_password  # noqa: E402


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    assert db.name == "earthscape_test"
    mongo_client.drop_database("earthscape_test")
    path = tmp_path / ".env"
    path.write_text("JWT_SECRET=%s\nENCRYPTION_KEY=%s\n" % (config.JWT_SECRET, config.ENCRYPTION_KEY), encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", path)
    # seed.main copies these from the file; restore them for the other tests afterwards.
    monkeypatch.setattr(config, "JWT_SECRET", config.JWT_SECRET)
    monkeypatch.setattr(config, "ENCRYPTION_KEY", config.ENCRYPTION_KEY)
    return path


def admin():
    return db.users.find_one({"role": "Admin"})


def test_reset_sets_a_new_password_and_prints_it_once(env_file, capsys):
    seed.main([])
    first = re.search(r"admin@earthscape\.test with password (\S+)", capsys.readouterr().out).group(1)
    seed.main(["--reset-password", "admin"])
    output = capsys.readouterr().out
    second = re.search(r"New password for admin@earthscape\.test .*:\n(\S+)\n", output).group(1)
    assert second != first
    assert verify_password(second, admin()["password_hash"]) and not verify_password(first, admin()["password_hash"])
    assert "PASSWORD" not in env_file.read_text(encoding="utf-8")


def test_reset_before_setup_says_to_run_the_seed(env_file):
    with pytest.raises(SystemExit, match="Run python seed.py first"):
        seed.main(["--reset-password", "admin"])


def test_reset_rejects_other_arguments(env_file):
    with pytest.raises(SystemExit, match="Usage"):
        seed.main(["--reset-password", "root"])
