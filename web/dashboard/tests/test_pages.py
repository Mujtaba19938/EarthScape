"""Dashboard pages: overview, reports, tickets, uploads, Hadoop, status and health."""
import datetime
import json
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from pymongo.errors import PyMongoError

from earthscape.db import acquire_lock, db
from earthscape.testing import ADMIN, ANALYST, MongoTestCase

from dashboard import cluster

UTC = datetime.timezone.utc
ONLINE = {"hdfs_online": True, "yarn_online": True, "live_datanodes": 1, "active_nodes": 1,
          "used_bytes": 1024, "capacity_bytes": 4096, "used_percent": 25.0}


def add_climate_data():
    db.gistemp_global.insert_many([{"Year": 2023, "J-D": 1.17}, {"Year": 2026, "J-D": None}])
    db.co2_annual.insert_one({"year": 2023, "mean": 421.0, "unc": 0.1})
    sensor = {"location_id": "1", "location": "A", "lat": 1.0, "lon": 2.0, "parameter": "pm25", "units": "x", "rejected": 0}
    db.air_quality_monthly.insert_many([
        dict(sensor, year=2023, month=12, mean=5.0, max=9.0, readings=10),
        dict(sensor, year=2024, month=1, mean=99.0, max=99.0, readings=1),
    ])


#----------------------------overview and reports--------------------------------------

class OverviewTests(MongoTestCase):

    def setUp(self):
        super().setUp()
        add_climate_data()
        self.sign_in(ANALYST)

    def test_overview_skips_the_incomplete_year(self):
        stats = self.client.get("/dashboard/overview/").context["stats"]
        self.assertEqual((stats[0]["value"], stats[0]["note"]), ("+1.17 °C", "2023"))
        self.assertEqual(stats[1]["value"], "421.0 ppm")
        self.assertEqual(stats[4]["value"], "Offline")

    def test_home_names_the_sources(self):
        stats = self.client.get("/dashboard/").context["stats"]
        self.assertEqual(stats[0]["note"], "NASA GISTEMP, 2023")

    def test_cluster_online_shows_in_the_sidebar(self):
        with mock.patch.object(cluster, "cluster_status", return_value=ONLINE):
            page = self.client.get("/dashboard/overview/")
        self.assertEqual(page.context["sidebar"]["nodes"], "1 DataNode online")
        self.assertEqual(page.context["stats"][4]["value"], "Online")

    def test_air_quality_ignores_the_2024_spillover(self):
        sensors = self.client.get("/dashboard/monitor/").context["sensors"]
        self.assertEqual(sensors[0]["pollutants"][0]["value"], "5 x")
        self.assertEqual(sensors[0]["pollutants"][0]["month"], "Dec")

    def test_analytics_unknown_choice_resets_to_global(self):
        page = self.client.get("/dashboard/analytics/?zone=Mars&variable=x")
        self.assertEqual((page.context["zone"], page.context["variable"]), ("Glob", "anomaly"))

    def test_report_downloads_real_csv(self):
        response = self.client.get("/dashboard/reports/download/?report=co2&format=csv")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode().splitlines(), ["year,mean,unc", "2023,421.0,0.1"])
        self.assertIn("attachment", response["Content-Disposition"])

    def test_json_report_matches_the_data(self):
        response = self.client.get("/dashboard/reports/download/?report=co2&format=json")
        self.assertEqual(json.loads(response.content), [{"year": 2023, "mean": 421.0, "unc": 0.1}])

    def test_geojson_only_for_reports_with_coordinates(self):
        refused = self.client.get("/dashboard/reports/download/?report=co2&format=geojson")
        self.assertIn("GeoJSON is only for data with map points", self.follow_messages(refused)[0])
        body = json.loads(self.client.get("/dashboard/reports/download/?report=air_quality&format=geojson").content)
        self.assertEqual(body["features"][0]["geometry"]["coordinates"], [2.0, 1.0])
        self.assertEqual(len(body["features"]), 1)

    def test_unknown_report_is_refused(self):
        self.assertEqual(self.client.get("/dashboard/reports/download/?report=secrets").status_code, 302)

    def test_search_finds_cities_and_rules(self):
        db.alert_rules.insert_one({"name": "Karachi heat", "metric": "live_temperature", "threshold": 40, "severity": "High"})
        results = self.client.get("/dashboard/search/?q=kara").context["results"]
        self.assertEqual({row["group"] for row in results}, {"Live cities", "Alert rules"})
        self.assertEqual(self.client.get("/dashboard/search/?q=k").context["results"], [])


#----------------------------support tickets--------------------------------------

class TicketTests(MongoTestCase):

    def test_analyst_sees_only_their_own_tickets_and_admin_sees_all(self):
        self.sign_in(ADMIN)
        self.client.post("/dashboard/support/", {"category": "Feedback", "description": "admin's"})
        self.client.post("/logout/")
        self.sign_in(ANALYST)
        self.client.post("/dashboard/support/", {"category": "Feedback", "description": "mine"})
        seen = self.client.get("/dashboard/support/").context["tickets"]
        self.assertEqual([ticket["description"] for ticket in seen], ["mine"])
        self.client.post("/logout/")
        self.sign_in(ADMIN)
        self.assertEqual(len(self.client.get("/dashboard/support/").context["tickets"]), 2)

    def test_closing_a_ticket_notifies_only_its_owner(self):
        self.sign_in(ANALYST)
        self.client.post("/dashboard/support/", {"category": "Feedback", "description": "mine"})
        ticket_id = db.tickets.find_one()["_id"]
        self.client.post("/logout/")
        self.sign_in(ADMIN)
        self.client.post("/dashboard/support/%s/" % ticket_id, {"status": "Closed"})
        self.assertEqual(db.tickets.find_one()["status"], "Closed")
        admin_notes = [note["text"] for note in self.client.get("/dashboard/").context["notifications"]]
        self.assertFalse(any("Closed" in text for text in admin_notes))
        self.client.post("/logout/")
        self.sign_in(ANALYST)
        notes = [note["text"] for note in self.client.get("/dashboard/").context["notifications"]]
        self.assertTrue(any("Closed" in text for text in notes))

    def test_bad_ticket_changes_are_refused(self):
        self.sign_in(ADMIN)
        self.assertEqual(self.client.post("/dashboard/support/000000000000000000000000/", {"status": "Closed"}).status_code, 404)
        self.assertEqual(self.client.post("/dashboard/support/000000000000000000000000/", {"status": "Gone"}).status_code, 400)
        self.client.post("/dashboard/support/", {"category": "Gossip", "description": "x"})
        self.client.post("/dashboard/support/", {"category": "Feedback", "description": "   "})
        self.assertEqual(db.tickets.count_documents({}), 0)

    def test_reading_notifications_marks_them_for_this_person_only(self):
        db.notifications.insert_one({"text": "Hello", "user_id": None, "read_by": [], "created_at": datetime.datetime.now(UTC)})
        self.sign_in(ANALYST)
        self.assertEqual(self.client.get("/dashboard/").context["unread"], 1)
        self.client.post("/dashboard/notifications/read/", {"next": "/dashboard/"})
        self.assertEqual(self.client.get("/dashboard/").context["unread"], 0)
        self.client.post("/logout/")
        self.sign_in(ADMIN)
        self.assertEqual(self.client.get("/dashboard/").context["unread"], 1)


#----------------------------uploads and hadoop--------------------------------------

class UploadTests(MongoTestCase):

    def upload(self, name, content):
        return self.client.post("/dashboard/data/upload/", {"file": SimpleUploadedFile(name, content)})

    def test_bad_uploads_are_refused(self):
        self.sign_in(ADMIN)
        with mock.patch.object(cluster, "put_file") as put:
            for name, content, message in (("data.exe", b"MZ", "Unsupported file type"), ("empty.csv", b"", "empty"),
                                           ("binary.csv", b"\x00\x01\x02", "CSV file"), ("fake.nc", b"this is not netcdf", "don't match")):
                self.assertIn(message, self.follow_messages(self.upload(name, content))[0], name)
        put.assert_not_called()
        self.assertEqual(db.datasets.count_documents({}), 0)

    def test_good_upload_is_stored_under_a_safe_name(self):
        self.sign_in(ADMIN)
        with mock.patch.object(cluster, "put_file") as put:
            shown = self.follow_messages(self.upload("../../evil name.csv", b"a,b\n1,2\n"))
        self.assertIn("evil_name.csv stored in HDFS", shown[0])
        self.assertEqual(put.call_args[0][1], "/climate/raw/uploads")
        stored = db.datasets.find_one()
        self.assertEqual((stored["name"], stored["path"]), ("evil_name.csv", "/climate/raw/uploads/evil_name.csv"))
        names = [row["name"] for row in self.client.get("/dashboard/data/").context["datasets"]]
        self.assertEqual(names[0], "evil_name.csv")

    def test_upload_says_so_when_hdfs_is_down(self):
        self.sign_in(ADMIN)
        with mock.patch.object(cluster, "put_file", side_effect=OSError("down")):
            self.assertIn("HDFS couldn't store", self.follow_messages(self.upload("a.csv", b"a,b\n1,2\n"))[0])
        self.assertEqual(db.datasets.count_documents({}), 0)


class HadoopTests(MongoTestCase):

    def test_unknown_job_id_is_not_passed_to_yarn(self):
        self.sign_in(ANALYST)
        with mock.patch.object(cluster, "get_job") as get_job:
            self.assertEqual(self.client.get("/dashboard/hadoop/jobs/secret/").status_code, 404)
        get_job.assert_not_called()

    def test_known_job_id_shows_the_yarn_record(self):
        self.sign_in(ANALYST)
        app = {"name": "earthscape_data_quality", "id": "application_1_0001", "state": "FINISHED",
               "finalStatus": "SUCCEEDED", "progress": 100, "startedTime": 0, "elapsedTime": 5000}
        with mock.patch.object(cluster, "get_job", return_value=app):
            page = self.client.get("/dashboard/hadoop/jobs/application_1_0001/")
        self.assertIn("State: FINISHED (SUCCEEDED)", page.context["job"]["lines"])

    def test_hadoop_job_refused_while_another_instance_runs_one(self):
        acquire_lock(cluster.JOB_LOCK, 60)
        self.sign_in(ADMIN)
        name = cluster.runnable_jobs()[0]
        with mock.patch.object(cluster, "_run_job_and_reload") as run:
            self.assertIn("already running", self.follow_messages(self.client.post("/dashboard/hadoop/run/%s/" % name))[0])
        run.assert_not_called()

    def test_admin_starts_a_known_job_only(self):
        self.sign_in(ADMIN)
        self.assertEqual(self.client.post("/dashboard/hadoop/run/rm-rf/").status_code, 404)
        name = cluster.runnable_jobs()[0]
        with mock.patch.object(cluster, "_run_job_and_reload") as run:
            self.client.post("/dashboard/hadoop/run/%s/" % name)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[1], "Admin")

    def test_running_job_refreshes_the_page(self):
        self.sign_in(ANALYST)
        job = {"id": "application_1_0001", "name": "data_quality", "state": "RUNNING", "group": "running",
               "final_status": "UNDEFINED", "progress": 40, "started_at": 0, "elapsed_seconds": 3, "diagnostics": ""}
        with mock.patch.object(cluster, "list_jobs", return_value=[job]):
            self.assertEqual(self.client.get("/dashboard/hadoop/").context["refresh_seconds"], 5)


#----------------------------status and health--------------------------------------

class StatusTests(MongoTestCase):

    def components(self):
        return {item["name"]: item["ok"] for item in self.client.get("/dashboard/status/").context["status"]["components"]}

    def test_status_needs_a_login_and_is_honest_when_nothing_has_run(self):
        self.assertEqual(self.client.get("/dashboard/status/").status_code, 302)
        self.sign_in(ANALYST)
        states = self.components()
        for name in ("HDFS", "Backups", "Health monitor", "Live data collector"):
            self.assertIs(states[name], False, name)
        self.assertEqual(self.client.get("/dashboard/status/").context["status"]["targets"], [])

    def test_a_manual_check_does_not_make_the_collector_look_alive(self):
        moment = datetime.datetime.now(UTC)
        self.sign_in(ANALYST)
        db.live_polls.insert_one({"started_at": moment, "ok": True, "triggered_by": "Admin", "seconds": 1})
        self.assertIs(self.components()["Live data collector"], False)
        db.live_polls.insert_one({"started_at": moment, "ok": True, "triggered_by": "collector", "seconds": 1})
        self.assertIs(self.components()["Live data collector"], True)

    def test_status_calculates_uptime_from_recorded_checks(self):
        moment = datetime.datetime.now(UTC)
        db.health_checks.insert_many(
            [{"target": "site", "ok": True, "ms": 5, "at": moment - datetime.timedelta(minutes=minute)} for minute in range(1, 4)]
            + [{"target": "site", "ok": False, "ms": 5, "at": moment}])
        self.sign_in(ANALYST)
        target = self.client.get("/dashboard/status/").context["status"]["targets"][0]
        self.assertEqual(target["day"], "75.0% (4 checks)")
        self.assertIs(target["latest"]["ok"], False)
        self.assertIs(self.components()["Health monitor"], True)

    def test_only_admin_sets_the_banner_and_everyone_sees_it(self):
        self.assertNotContains(self.client.get("/login/"), 'id="maintenance"')
        self.sign_in(ADMIN)
        self.client.post("/dashboard/status/maintenance/", {"active": "on", "message": "  Down at 6pm  "})
        self.assertEqual(db.settings.find_one({"_id": "maintenance"})["message"], "Down at 6pm")
        self.client.post("/logout/")
        self.assertContains(self.client.get("/login/"), "Down at 6pm")

    def test_banner_message_length_is_limited(self):
        self.sign_in(ADMIN)
        self.client.post("/dashboard/status/maintenance/", {"active": "on", "message": "x" * 301})
        self.assertEqual(len(db.settings.find_one({"_id": "maintenance"})["message"]), 300)

    def test_health_is_public_and_names_the_instance(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response["X-EarthScape-Instance"], response.json()["instance"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["X-Frame-Options"], "DENY")

    def test_health_fails_when_the_database_is_unreachable(self):
        with mock.patch.object(db, "command", side_effect=PyMongoError("down")):
            self.assertEqual(self.client.get("/api/health").status_code, 503)
