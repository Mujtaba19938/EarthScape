"""System health for people and for the load balancer, and the maintenance banner."""
import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from . import config, hadoop_client, live
from .db import db
from .security import current_user, require_admin

router = APIRouter(prefix="/api")

UPTIME_GOAL_PERCENT = 99
SITE_TARGET = "site"
MONITOR_STALE_MINUTES = 15
BACKUP_STALE_HOURS = 26


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


class Maintenance(BaseModel):
    active: bool
    message: str = Field(default="", max_length=300)


def _uptime(target, hours):
    since = _now() - datetime.timedelta(hours=hours)
    rows = list(db.health_checks.aggregate([
        {"$match": {"target": target, "at": {"$gte": since}}},
        {"$group": {"_id": None, "checks": {"$sum": 1}, "ok": {"$sum": {"$cond": ["$ok", 1, 0]}}}},
    ]))
    if not rows:
        return None
    return {"percent": round(100 * rows[0]["ok"] / rows[0]["checks"], 2), "checks": rows[0]["checks"]}


def _targets():
    result = []
    for target in sorted(db.health_checks.distinct("target")):
        latest = db.health_checks.find_one({"target": target}, sort=[("at", -1)], projection={"_id": 0})
        result.append({"target": target, "latest": latest, "day": _uptime(target, 24), "week": _uptime(target, 24 * 7)})
    return result


def _is_recent(moment, limit):
    return moment is not None and _now() - moment <= limit


def _collector_component():
    # A person pressing Check now doesn't show that the service itself is running.
    last_run = db.live_polls.find_one({"triggered_by": "collector", "ok": True}, sort=[("started_at", -1)])
    limit = datetime.timedelta(minutes=config.LIVE_POLL_MINUTES * live.STALE_AFTER_POLLS)
    ok = _is_recent(last_run["started_at"] if last_run else None, limit)
    return {"name": "Live data collector", "ok": ok, "detail": "Collecting on schedule" if ok else "Not running on schedule"}


def _components(cluster, last_check, last_backup):
    monitor_ok = _is_recent(last_check["at"] if last_check else None, datetime.timedelta(minutes=MONITOR_STALE_MINUTES))
    backup_ok = _is_recent(last_backup["finished_at"] if last_backup else None, datetime.timedelta(hours=BACKUP_STALE_HOURS))
    return [
        {"name": "MongoDB", "ok": True, "detail": "Answering this page"},
        {"name": "HDFS", "ok": cluster["hdfs_online"], "detail": "%s DataNode live" % cluster.get("live_datanodes", 0)},
        {"name": "YARN", "ok": cluster["yarn_online"], "detail": "%s node active" % cluster.get("active_nodes", 0)},
        _collector_component(),
        {"name": "Health monitor", "ok": monitor_ok, "detail": "Checking on schedule" if monitor_ok else "Not running on schedule"},
        {"name": "Backups", "ok": backup_ok, "detail": "Successful backup in the last day" if backup_ok else "No recent successful backup"},
    ]


@router.get("/status")
def status(_user=Depends(current_user)):
    db.command("ping")
    cluster = hadoop_client.cluster_status()
    collector = live.status()
    last_check = db.health_checks.find_one(sort=[("at", -1)])
    last_backup = db.backups.find_one({"ok": True}, sort=[("finished_at", -1)])
    ml_runs = db.ml_runs.find({}, {"_id": 0, "version": 1, "trained_at": 1, "seconds": 1}).sort("trained_at", -1).limit(5)
    return {
        "instance": config.INSTANCE_NAME,
        "goal_percent": UPTIME_GOAL_PERCENT,
        "components": _components(cluster, last_check, last_backup),
        "targets": _targets(),
        "site_target": SITE_TARGET,
        "backups": list(db.backups.find({}, {"_id": 0}).sort("finished_at", -1).limit(5)),
        "pipeline_runs": list(db.pipeline_runs.find({}, {"_id": 0}).sort("finished_at", -1).limit(5)),
        "ml_runs": list(ml_runs),
        "last_poll": collector["last_poll"],
    }


@router.get("/maintenance")
def maintenance():
    """Public, so the sign-in page can show it too."""
    row = db.settings.find_one({"_id": "maintenance"}) or {}
    return {"active": row.get("active", False), "message": row.get("message", "")}


@router.put("/maintenance")
def set_maintenance(body: Maintenance, admin=Depends(require_admin)):
    db.settings.update_one(
        {"_id": "maintenance"},
        {"$set": {"active": body.active, "message": body.message.strip(), "updated_by": admin["name"], "updated_at": _now()}},
        upsert=True)
    return maintenance()
