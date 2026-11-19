"""ML page and retraining. Training itself is tested in ml/test_train_models.py."""
import datetime
import subprocess
from unittest import mock

from earthscape.db import acquire_lock, db, release_lock
from earthscape.testing import ADMIN, ANALYST, MongoTestCase

from dashboard import cluster


def run_document(version, day):
    comparison = [{"method": "persistence", "test_rmse": 0.3}, {"method": "holt", "test_rmse": 0.2}]
    return {
        "version": version, "trained_at": datetime.datetime(2026, 1, day), "triggered_by": "Admin",
        "forecast_scores": [{"series": "Glob", "chosen_method": "holt", "comparison": comparison,
                             "beats_baseline": True, "test_coverage": 0.9, "test_period": "2016-2025"}],
        "anomaly": {"false_alarm_rate": 0.01, "recall_by_spike_size": {"10": 0.9, "6": 0.7, "3": 0.2}},
    }


def forecast_document():
    method = {"label": "Holt trend", "method": "holt", "backtest_rmse": 0.15, "test_rmse": 0.2, "test_bias": 0.01}
    return {
        "series": "Glob", "chosen_method": "holt", "chosen_label": "Holt trend", "test_period": "2016-2025",
        "beats_baseline": True, "test_rmse": 0.2, "baseline_test_rmse": 0.3, "test_coverage": 0.9,
        "history": [{"year": year, "value": 0.02 * (year - 1950)} for year in range(1940, 2026)],
        "forecast": [{"year": year, "forecast": 1.5, "lower": 1.0, "upper": 2.0} for year in range(2026, 2051)],
        "comparison": [method],
    }


def finished_training(returncode, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout="", stderr=stderr)


class MLPageTests(MongoTestCase):

    def setUp(self):
        super().setUp()
        db.ml_runs.insert_many([run_document("old", 1), run_document("new", 2)])
        db.ml_forecasts.insert_one(forecast_document())
        db.ml_anomalies.insert_many([{"date": "low", "score": 0.1}, {"date": "high", "score": 0.9}])
        db.ml_correlations.insert_one({"name": "co2_levels", "pearson": 0.9, "pearson_p": 0.001})

    def test_results_need_a_login(self):
        self.assertEqual(self.client.get("/dashboard/ml/").status_code, 302)

    def test_summary_shows_the_newest_run_and_scores_each_run(self):
        self.sign_in(ANALYST)
        summary = self.client.get("/dashboard/ml/").context["summary"]
        self.assertEqual(summary["latest"]["version"], "new")
        self.assertEqual([row["version"] for row in summary["history"]], ["new", "old"])
        self.assertEqual(summary["history"][0]["global_test_rmse"], 0.2)
        self.assertEqual(summary["history"][0]["global_baseline_rmse"], 0.3)
        self.assertEqual(summary["history"][0]["beating"], "1 of 1")
        self.assertEqual(summary["latest"]["trained_at"].tzinfo, datetime.timezone.utc)

    def test_forecast_starts_at_the_last_measured_year_and_hides_old_years(self):
        self.sign_in(ANALYST)
        forecast = self.client.get("/dashboard/ml/?series=Glob&horizon=2030").context["forecast"]
        labels = forecast["chart"]["labels"]
        self.assertEqual((labels[0], labels[-1]), (1950, 2030))
        self.assertEqual([row["year"] for row in forecast["table"]], [2030, 2040, 2050])
        self.assertIn("beat", forecast["verdict"])

    def test_unknown_series_or_horizon_falls_back(self):
        self.sign_in(ANALYST)
        page = self.client.get("/dashboard/ml/?series=Mars&horizon=1999")
        self.assertEqual((page.context["series"], page.context["horizon"]), ("Glob", 2050))
        self.assertEqual(self.client.get("/dashboard/ml/?horizon=soon").context["horizon"], 2050)

    def test_anomalies_come_back_worst_first(self):
        self.sign_in(ANALYST)
        rows = self.client.get("/dashboard/ml/").context["anomalies"]
        self.assertEqual([row["date"] for row in rows], ["high", "low"])

    def test_analyst_cannot_retrain(self):
        self.sign_in(ANALYST)
        with mock.patch.object(cluster, "start_training") as start:
            self.assertEqual(self.client.post("/dashboard/ml/retrain/").status_code, 403)
        start.assert_not_called()

    def test_admin_retrain_starts_once_and_a_second_is_refused(self):
        self.sign_in(ADMIN)
        run = mock.Mock()
        with mock.patch.object(cluster, "_run_training", run):
            first = self.client.post("/dashboard/ml/retrain/")
            self.assertIn("Training started", self.follow_messages(first)[0])
            second = self.client.post("/dashboard/ml/retrain/")
            self.assertIn("already running", self.follow_messages(second)[0])
            page = self.client.get("/dashboard/ml/")
            self.assertIs(page.context["summary"]["retraining"], True)
            # Page refreshes itself
            self.assertEqual(page.context["refresh_seconds"], 5)
        release_lock(cluster.ML_LOCK)
        run.assert_called_once_with("Admin")


class TrainingTests(MongoTestCase):
    with_users = False

    def test_training_uses_this_database_and_reports_success(self):
        acquire_lock(cluster.ML_LOCK, 60)
        with mock.patch.object(cluster.subprocess, "run", return_value=finished_training(0)) as run, \
                mock.patch.object(cluster, "notify") as notify:
            cluster._run_training("Admin")
        self.assertEqual(run.call_args.kwargs["env"]["MONGO_DB"], "earthscape_test")
        self.assertIn("Admin", notify.call_args.args[0])
        self.assertFalse(cluster.training_running())

    def test_failed_training_reports_the_error_and_frees_the_lock(self):
        acquire_lock(cluster.ML_LOCK, 60)
        with mock.patch.object(cluster.subprocess, "run", return_value=finished_training(1, "Traceback\nValueError: bad")), \
                mock.patch.object(cluster, "notify") as notify:
            cluster._run_training("Admin")
        self.assertIn("ValueError: bad", notify.call_args.args[0])
        self.assertFalse(cluster.training_running())

    def test_missing_python_reports_the_error_and_frees_the_lock(self):
        acquire_lock(cluster.ML_LOCK, 60)
        with mock.patch.object(cluster.subprocess, "run", side_effect=FileNotFoundError("no python")), \
                mock.patch.object(cluster, "notify") as notify:
            cluster._run_training("Admin")
        self.assertIn("no python", notify.call_args.args[0])
        self.assertFalse(cluster.training_running())
