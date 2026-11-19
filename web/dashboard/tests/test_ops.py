"""Locks, the health monitor and backups (ops/ scripts)."""
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path
from unittest import mock

from earthscape import config
from earthscape.db import acquire_lock, db, lock_held, release_lock
from earthscape.testing import MongoTestCase

from dashboard import cluster

sys.path.insert(0, str(config.ROOT_DIR / "ops"))
import backup  # noqa: E402
import health_monitor  # noqa: E402


#----------------------------shared locks--------------------------------------

class LockTests(MongoTestCase):
    with_users = False

    def test_lock_can_only_be_held_once_until_released(self):
        self.assertIs(acquire_lock("x", 60), True)
        self.assertIs(acquire_lock("x", 60), False)
        self.assertTrue(lock_held("x"))
        release_lock("x")
        self.assertIs(acquire_lock("x", 60), True)

    def test_lock_from_a_crashed_instance_expires(self):
        self.assertIs(acquire_lock("x", -1), True)
        self.assertFalse(lock_held("x"))
        self.assertIs(acquire_lock("x", 60), True)


#----------------------------health monitor--------------------------------------

class HealthMonitorTests(MongoTestCase):
    with_users = False

    def test_monitor_tells_people_only_when_a_target_changes(self):
        for ok in (True, True, False, False, True):
            health_monitor.record("site", {"ok": ok, "status": 200 if ok else None, "error": None, "ms": 1})
        texts = [row["text"] for row in db.notifications.find().sort("created_at", 1)]
        self.assertEqual(texts, ["site is down.", "site is back up."])
        self.assertEqual(db.health_checks.count_documents({}), 5)

    def test_monitor_records_a_refused_connection_as_down(self):
        with mock.patch.object(health_monitor.urllib.request, "urlopen", side_effect=urllib.error.URLError("refused")):
            result = health_monitor.check("http://127.0.0.1:9/api/health")
        self.assertEqual((result["ok"], result["error"]), (False, "URLError"))

    def test_monitor_records_an_error_status_as_down(self):
        error = urllib.error.HTTPError("http://x", 503, "unavailable", {}, None)
        with mock.patch.object(health_monitor.urllib.request, "urlopen", side_effect=error):
            result = health_monitor.check("http://x")
        self.assertEqual((result["ok"], result["status"]), (False, 503))

    def test_default_targets_are_the_two_instances_and_apache(self):
        self.assertIn("/api/health", config.MONITOR_TARGETS)
        self.assertEqual(len(health_monitor.targets()), 3)


#----------------------------backups--------------------------------------

class BackupTests(MongoTestCase):
    with_users = False

    def setUp(self):
        super().setUp()
        self.folder = Path(tempfile.mkdtemp())

    def test_prune_keeps_the_newest_and_never_touches_other_folders(self):
        for name in ("20260101-000000", "20260102-000000", "20260103-000000", "important", "2026"):
            (self.folder / name).mkdir()
        self.assertEqual(backup.prune(self.folder, 2), ["20260101-000000"])
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()),
                         ["2026", "20260102-000000", "20260103-000000", "important"])

    def test_restore_check_finds_missing_and_short_collections(self):
        self.assertEqual(backup.counts_match({"a": 100}, {"a": 100}), [])
        self.assertEqual(backup.counts_match({"a": 1000}, {"a": 995}), [])
        self.assertEqual(backup.counts_match({"a": 100}, {}), ["a is missing"])
        self.assertIn("a has 500 rows", backup.counts_match({"a": 1000}, {"a": 500})[0])

    def test_failed_backup_is_recorded_and_reported(self):
        with mock.patch.object(backup.config, "BACKUP_DIR", str(self.folder)), \
                mock.patch.object(backup, "dump_mongo", side_effect=RuntimeError("no space")):
            self.assertEqual(backup.main(), 1)
        row = db.backups.find_one()
        self.assertIs(row["ok"], False)
        self.assertIn("no space", row["error"])
        self.assertIn("Backup failed", db.notifications.find_one()["text"])

    def test_mongodb_is_backed_up_even_when_hdfs_is_down(self):
        with mock.patch.object(backup.config, "BACKUP_DIR", str(self.folder)), mock.patch.object(backup, "dump_mongo"), \
                mock.patch.object(backup, "verify_restore", return_value=10), \
                mock.patch.object(cluster.run_pipeline, "hdfs", side_effect=subprocess.CalledProcessError(1, "hdfs")):
            self.assertEqual(backup.main(), 0)
        row = db.backups.find_one()
        self.assertIs(row["ok"], True)
        self.assertEqual(row["hdfs_failed"], backup.HDFS_PATHS)
        self.assertIn("weren't copied", db.notifications.find_one()["text"])

    def test_hdfs_commands_use_the_launcher_that_reports_failures(self):
        pipeline = cluster.run_pipeline
        with mock.patch.object(pipeline.subprocess, "run") as run:
            pipeline.hdfs("-get", "/climate/processed", "target")
            self.assertTrue(run.call_args[0][0].startswith("cmd /c hadoop fs -get"))
            pipeline.read_job_output("data_quality")
            self.assertTrue(run.call_args[0][0].startswith("cmd /c hadoop fs -cat"))
