"""Hadoop (HDFS and YARN) status, jobs and uploads, and ML retraining."""
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from earthscape import config
from earthscape.db import acquire_lock, db, lock_held, notify, release_lock

sys.path.insert(0, str(config.ROOT_DIR / "hadoop"))
import run_pipeline  # noqa: E402

JOB_LOCK = "hadoop_job"
JOB_LOCK_SECONDS = 3 * 3600
ML_DIR = config.ROOT_DIR / "ml"
TRAINING_TIMEOUT_SECONDS = 1800
ML_LOCK = "ml_training"


# Hadoop status

def _get_json(url):
    """None when offline."""
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def cluster_status():
    """HDFS and YARN."""
    state = _get_json(config.NAMENODE_URL + "/jmx?qry=Hadoop:service=NameNode,name=FSNamesystemState")
    metrics = _get_json(config.YARN_URL + "/ws/v1/cluster/metrics")
    result = {"hdfs_online": bool(state and state.get("beans")), "yarn_online": bool(metrics)}
    if result["hdfs_online"]:
        bean = state["beans"][0]
        result.update(
            capacity_bytes=bean["CapacityTotal"], used_bytes=bean["CapacityUsed"],
            live_datanodes=bean["NumLiveDataNodes"], dead_datanodes=bean["NumDeadDataNodes"],
            files=bean["FilesTotal"], blocks=bean["BlocksTotal"])
        # Used share
        result["used_percent"] = round(100 * bean["CapacityUsed"] / bean["CapacityTotal"], 1) if bean["CapacityTotal"] else 0
    if metrics:
        cluster = metrics["clusterMetrics"]
        result.update(
            active_nodes=cluster["activeNodes"], containers_allocated=cluster["containersAllocated"],
            apps_running=cluster["appsRunning"], apps_completed=cluster["appsCompleted"],
            apps_failed=cluster["appsFailed"], memory_total_mb=cluster["totalMB"],
            memory_used_mb=cluster["allocatedMB"])
    return result


# YARN jobs

def job_state(state):
    """Display group."""
    if state in ("FAILED", "KILLED"):
        return "failed"
    if state in ("RUNNING", "ACCEPTED"):
        return "running"
    return "done"


def list_jobs():
    """Newest first."""
    # YARN forgets jobs when it restarts
    data = _get_json(config.YARN_URL + "/ws/v1/cluster/apps")
    if data is None:
        return None
    apps = (data.get("apps") or {}).get("app") or []
    jobs = [{
        "id": app["id"],
        "name": app["name"].replace("earthscape_", ""),
        "state": app["state"],
        "group": job_state(app["state"]),
        "final_status": app["finalStatus"],
        "progress": round(app["progress"]),
        "started_at": app["startedTime"],
        "elapsed_seconds": round(app["elapsedTime"] / 1000),
        "diagnostics": app.get("diagnostics") or "",
    } for app in apps if app["name"].startswith("earthscape_")]
    return sorted(jobs, key=lambda job: job["started_at"], reverse=True)


def get_job(application_id):
    quoted = urllib.parse.quote(application_id, safe="")
    data = _get_json(config.YARN_URL + "/ws/v1/cluster/apps/" + quoted)
    return data.get("app") if data else None


def job_spec(name):
    return next((spec for spec in run_pipeline.JOB_SPECS if spec[0] == name), None)


def runnable_jobs():
    return [spec[0] for spec in run_pipeline.JOB_SPECS]


def job_running():
    return lock_held(JOB_LOCK)


def _run_job_and_reload(spec, username):
    """Runs, then loads."""
    name = spec[0]
    try:
        seconds = run_pipeline.run_job(name, spec[1], spec[2], spec[3])
        run_pipeline.load_job_output(db, spec)
        run_pipeline.record_timings(db, [run_pipeline.timing(name, seconds)])
        notify("Job %s finished in %.0f s (started by %s)." % (name, seconds, username))
    except Exception as error:
        notify("Job %s failed: %s" % (name, error))
    finally:
        release_lock(JOB_LOCK)


def start_job(spec, username):
    """False if busy."""
    if not acquire_lock(JOB_LOCK, JOB_LOCK_SECONDS):
        return False
    threading.Thread(target=_run_job_and_reload, args=(spec, username), daemon=True).start()
    return True


# HDFS files

def hdfs_size(path):
    query = "?op=GETCONTENTSUMMARY&user.name=hadoop"
    data = _get_json(config.NAMENODE_URL + "/webhdfs/v1" + urllib.parse.quote(path) + query)
    return data["ContentSummary"]["length"] if data and "ContentSummary" in data else None


def put_file(local_path, target_dir):
    run_pipeline.put(str(local_path), target_dir)


# ML training runs in Anaconda's Python, which has the ML libraries

def training_running():
    return lock_held(ML_LOCK)


def _ml_environment():
    python_dir = Path(config.ML_PYTHON).parent
    paths = [python_dir, python_dir / "Library" / "bin", python_dir / "Scripts"]
    return dict(os.environ, PATH=os.pathsep.join([str(path) for path in paths] + [os.environ.get("PATH", "")]),
                MONGO_URI=config.MONGO_URI, MONGO_DB=config.MONGO_DB)


def _run_training(username):
    command = [config.ML_PYTHON, "-W", "ignore", str(ML_DIR / "train_models.py"), "--triggered-by", username]
    try:
        result = subprocess.run(command, cwd=str(ML_DIR), env=_ml_environment(), capture_output=True, text=True,
                                errors="replace", timeout=TRAINING_TIMEOUT_SECONDS)
        if result.returncode == 0:
            notify("Models retrained (started by %s)." % username)
        else:
            lines = result.stderr.strip().splitlines()
            notify("Model training failed: %s" % (lines[-1] if lines else "no error message"))
    except (OSError, subprocess.SubprocessError) as error:
        notify("Model training failed: %s" % error)
    finally:
        release_lock(ML_LOCK)


def start_training(username):
    """False if busy."""
    if not acquire_lock(ML_LOCK, TRAINING_TIMEOUT_SECONDS + 60):
        return False
    threading.Thread(target=_run_training, args=(username,), daemon=True).start()
    return True
