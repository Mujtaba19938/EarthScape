"""Reads live status from HDFS and YARN, and runs jobs and uploads on the cluster."""
import json
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

from . import config, locks
from .db import db
from .notifications import notify

sys.path.insert(0, str(config.ROOT_DIR / "hadoop"))
import run_pipeline  # noqa: E402

JOB_LOCK = "hadoop_job"
JOB_LOCK_SECONDS = 3 * 3600


def _get_json(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def cluster_status():
    state = _get_json(config.NAMENODE_URL + "/jmx?qry=Hadoop:service=NameNode,name=FSNamesystemState")
    metrics = _get_json(config.YARN_URL + "/ws/v1/cluster/metrics")
    result = {"hdfs_online": bool(state and state.get("beans")), "yarn_online": bool(metrics)}
    if result["hdfs_online"]:
        bean = state["beans"][0]
        result.update(
            capacity_bytes=bean["CapacityTotal"], used_bytes=bean["CapacityUsed"],
            live_datanodes=bean["NumLiveDataNodes"], dead_datanodes=bean["NumDeadDataNodes"],
            files=bean["FilesTotal"], blocks=bean["BlocksTotal"])
    if metrics:
        cluster = metrics["clusterMetrics"]
        result.update(
            active_nodes=cluster["activeNodes"], containers_allocated=cluster["containersAllocated"],
            apps_running=cluster["appsRunning"], apps_completed=cluster["appsCompleted"],
            apps_failed=cluster["appsFailed"], memory_total_mb=cluster["totalMB"],
            memory_used_mb=cluster["allocatedMB"])
    return result


def list_jobs():
    """Jobs known to YARN, newest first. YARN forgets them when it restarts."""
    data = _get_json(config.YARN_URL + "/ws/v1/cluster/apps")
    if data is None:
        return None
    apps = (data.get("apps") or {}).get("app") or []
    jobs = [{
        "id": app["id"],
        "name": app["name"].replace("earthscape_", ""),
        "state": app["state"],
        "final_status": app["finalStatus"],
        "progress": app["progress"],
        "started_at": app["startedTime"],
        "elapsed_ms": app["elapsedTime"],
        "diagnostics": app.get("diagnostics") or "",
    } for app in apps if app["name"].startswith("earthscape_")]
    return sorted(jobs, key=lambda job: job["started_at"], reverse=True)


def get_job(application_id):
    quoted = urllib.parse.quote(application_id, safe="")
    data = _get_json(config.YARN_URL + "/ws/v1/cluster/apps/" + quoted)
    return data.get("app") if data else None


def job_spec(name):
    return next((spec for spec in run_pipeline.JOB_SPECS if spec[0] == name), None)


def _run_job_and_reload(spec, username):
    name = spec[0]
    try:
        seconds = run_pipeline.run_job(name, spec[1], spec[2], spec[3])
        run_pipeline.load_job_output(db, spec)
        run_pipeline.record_timings(db, [run_pipeline.timing(name, seconds)])
        notify("Job %s finished in %.0f s (started by %s)." % (name, seconds, username))
    except Exception as error:
        notify("Job %s failed: %s" % (name, error))
    finally:
        locks.release(JOB_LOCK)


def start_job(spec, username):
    """Starts a job in the background. Returns False if one is already running."""
    if not locks.acquire(JOB_LOCK, JOB_LOCK_SECONDS):
        return False
    threading.Thread(target=_run_job_and_reload, args=(spec, username), daemon=True).start()
    return True


def hdfs_size(path):
    query = "?op=GETCONTENTSUMMARY&user.name=hadoop"
    data = _get_json(config.NAMENODE_URL + "/webhdfs/v1" + urllib.parse.quote(path) + query)
    return data["ContentSummary"]["length"] if data and "ContentSummary" in data else None


def put_file(local_path, target_dir):
    run_pipeline.put(str(local_path), target_dir)
