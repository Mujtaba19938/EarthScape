"""Cluster status, jobs, dataset uploads, alert rules, tickets and notifications."""
import datetime
import os
import re
import tempfile

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from . import config, hadoop_client
from .catalogue import DATASETS, UPLOAD_SIGNATURES
from .db import db
from .notifications import notify
from .security import current_user, require_admin

router = APIRouter(prefix="/api")

ALERT_METRICS = {
    "station_temperature_z": "Station temperature z-score",
    "air_pm25": "Air quality PM2.5 (µg/m³)",
    "air_pm10": "Air quality PM10 (µg/m³)",
    "global_anomaly": "Global temperature anomaly (°C)",
    "co2": "Atmospheric CO2 (ppm)",
}
SEVERITIES = ("Critical", "High", "Medium", "Low")
ALERT_STATUSES = ("Acknowledged", "Resolved")
TICKET_CATEGORIES = ("Data pipeline problem", "Incorrect data", "Website or dashboard bug", "Feedback")
TICKET_STATUSES = ("Open", "In progress", "Closed")


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _object_id(value):
    try:
        return ObjectId(value)
    except InvalidId:
        raise HTTPException(status_code=404, detail="Not found.")


def _public(document):
    result = dict(document)
    result["id"] = str(result.pop("_id"))
    return result


@router.get("/cluster")
def cluster(_user=Depends(current_user)):
    return hadoop_client.cluster_status()


@router.get("/jobs")
def jobs(_user=Depends(current_user)):
    yarn_jobs = hadoop_client.list_jobs()
    timings = db.pipeline_runs.find({}, {"_id": 0}).sort("finished_at", -1).limit(20)
    return {
        "yarn_online": yarn_jobs is not None,
        "jobs": yarn_jobs or [],
        "runnable": [spec[0] for spec in hadoop_client.run_pipeline.JOB_SPECS],
        "recent_runs": list(timings),
    }


@router.get("/jobs/{application_id}")
def job_detail(application_id: str, _user=Depends(current_user)):
    if not re.fullmatch(r"application_\d+_\d+", application_id):
        raise HTTPException(status_code=404, detail="Job not found.")
    app = hadoop_client.get_job(application_id)
    if not app:
        raise HTTPException(status_code=404, detail="YARN has no record of this job.")
    return {key: app.get(key) for key in (
        "id", "name", "state", "finalStatus", "progress", "startedTime", "finishedTime",
        "elapsedTime", "diagnostics", "memorySeconds", "vcoreSeconds", "trackingUrl")}


@router.post("/jobs/{name}/run", status_code=202)
def run_job(name: str, admin=Depends(require_admin)):
    spec = hadoop_client.job_spec(name)
    if not spec:
        raise HTTPException(status_code=404, detail="Unknown job.")
    if not hadoop_client.start_job(spec, admin["name"]):
        raise HTTPException(status_code=409, detail="A job started from here is already running.")
    return {"started": name}


@router.get("/datasets")
def datasets(_user=Depends(current_user)):
    catalogue = [dict(entry, size_bytes=hadoop_client.hdfs_size(entry["path"]), uploaded=False)
                 for entry in DATASETS]
    uploads = [dict(_public(row), uploaded=True) for row in db.datasets.find().sort("ingested_at", -1)]
    return uploads + catalogue


def _clean_filename(filename):
    name = os.path.basename((filename or "").replace("\\", "/"))
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def _check_contents(path, extension):
    expected = UPLOAD_SIGNATURES[extension]
    with open(path, "rb") as source:
        start = source.read(4096)
    if expected is None:
        if b"\x00" in start or b"," not in start.split(b"\n")[0]:
            raise HTTPException(status_code=422, detail="This doesn't look like a CSV file with a header row.")
        return
    if not any(start.startswith(signature) for signature in expected):
        raise HTTPException(status_code=422, detail="The file's contents don't match its %s extension." % extension)


@router.post("/datasets", status_code=201)
def upload_dataset(file: UploadFile = File(...), admin=Depends(require_admin)):
    filename = _clean_filename(file.filename)
    extension = os.path.splitext(filename)[1].lower()
    if extension not in UPLOAD_SIGNATURES:
        allowed = ", ".join(sorted(UPLOAD_SIGNATURES))
        raise HTTPException(status_code=422, detail="Unsupported file type. Allowed: " + allowed)
    if file.size is not None and file.size > config.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="The file is larger than the upload limit.")
    with tempfile.TemporaryDirectory() as folder:
        local_path = os.path.join(folder, filename)
        size = 0
        with open(local_path, "wb") as target:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="The file is larger than the upload limit.")
                target.write(chunk)
        if size == 0:
            raise HTTPException(status_code=422, detail="The file is empty.")
        _check_contents(local_path, extension)
        target_dir = "/climate/raw/uploads"
        try:
            hadoop_client.put_file(local_path, target_dir)
        except Exception:
            raise HTTPException(status_code=503, detail="HDFS couldn't store the file. Is it running?")
    document = {
        "name": filename, "format": extension.lstrip(".").upper(), "source": "Upload by " + admin["name"],
        "path": target_dir + "/" + filename, "size_bytes": size, "ingested_at": _now(),
        "uploaded_by": str(admin["_id"]),
    }
    db.datasets.update_one({"path": document["path"]}, {"$set": document}, upsert=True)
    notify("%s uploaded dataset %s." % (admin["name"], filename))
    return _public(db.datasets.find_one({"path": document["path"]}))


class AlertRule(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    metric: str
    threshold: float
    severity: str


class AlertUpdate(BaseModel):
    status: str


@router.get("/alert-metrics")
def alert_metrics(_user=Depends(current_user)):
    return {"metrics": ALERT_METRICS, "severities": SEVERITIES}


@router.get("/alert-rules")
def alert_rules(_user=Depends(current_user)):
    return [_public(rule) for rule in db.alert_rules.find().sort("created_at", -1)]


@router.post("/alert-rules", status_code=201)
def create_alert_rule(body: AlertRule, admin=Depends(require_admin)):
    if body.metric not in ALERT_METRICS:
        raise HTTPException(status_code=422, detail="Unknown metric.")
    if body.severity not in SEVERITIES:
        raise HTTPException(status_code=422, detail="Unknown severity.")
    document = body.model_dump()
    document.update(name=body.name.strip(), created_by=admin["name"], created_at=_now())
    db.alert_rules.insert_one(document)
    return _public(document)


@router.delete("/alert-rules/{rule_id}")
def delete_alert_rule(rule_id: str, _admin=Depends(require_admin)):
    result = db.alert_rules.delete_one({"_id": _object_id(rule_id)})
    if not result.deleted_count:
        raise HTTPException(status_code=404, detail="Rule not found.")
    return {"ok": True}


@router.get("/alerts")
def alerts(_user=Depends(current_user)):
    return [_public(alert) for alert in db.alerts.find().sort("created_at", -1).limit(200)]


@router.patch("/alerts/{alert_id}")
def update_alert(alert_id: str, body: AlertUpdate, user=Depends(current_user)):
    if body.status not in ALERT_STATUSES:
        raise HTTPException(status_code=422, detail="Unknown status.")
    result = db.alerts.update_one(
        {"_id": _object_id(alert_id)},
        {"$set": {"status": body.status, "updated_by": user["name"], "updated_at": _now()}})
    if not result.matched_count:
        raise HTTPException(status_code=404, detail="Alert not found.")
    return _public(db.alerts.find_one({"_id": _object_id(alert_id)}))


class NewTicket(BaseModel):
    category: str
    description: str = Field(min_length=1, max_length=4000)


class TicketUpdate(BaseModel):
    status: str


@router.get("/tickets")
def tickets(user=Depends(current_user)):
    query = {} if user["role"] == "Admin" else {"created_by": str(user["_id"])}
    return [_public(ticket) for ticket in db.tickets.find(query).sort("created_at", -1)]


@router.post("/tickets", status_code=201)
def create_ticket(body: NewTicket, user=Depends(current_user)):
    if body.category not in TICKET_CATEGORIES:
        raise HTTPException(status_code=422, detail="Unknown category.")
    if not body.description.strip():
        raise HTTPException(status_code=422, detail="Please describe the issue.")
    document = {
        "category": body.category, "description": body.description.strip(), "status": "Open",
        "created_by": str(user["_id"]), "created_by_name": user["name"], "created_at": _now(),
    }
    db.tickets.insert_one(document)
    return _public(document)


@router.patch("/tickets/{ticket_id}")
def update_ticket(ticket_id: str, body: TicketUpdate, _admin=Depends(require_admin)):
    if body.status not in TICKET_STATUSES:
        raise HTTPException(status_code=422, detail="Unknown status.")
    ticket_key = _object_id(ticket_id)
    ticket = db.tickets.find_one({"_id": ticket_key})
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    db.tickets.update_one({"_id": ticket_key}, {"$set": {"status": body.status, "updated_at": _now()}})
    notify("Your ticket \"%s\" is now %s." % (ticket["category"], body.status), ticket["created_by"])
    return _public(db.tickets.find_one({"_id": ticket_key}))


def _notification_query(user):
    return {"$or": [{"user_id": None}, {"user_id": str(user["_id"])}]}


@router.get("/notifications")
def notifications(user=Depends(current_user)):
    rows = db.notifications.find(_notification_query(user)).sort("created_at", -1).limit(30)
    user_id = str(user["_id"])
    return [{"id": str(row["_id"]), "text": row["text"], "created_at": row["created_at"],
             "read": user_id in row.get("read_by", [])} for row in rows]


@router.post("/notifications/read")
def mark_notifications_read(user=Depends(current_user)):
    db.notifications.update_many(_notification_query(user), {"$addToSet": {"read_by": str(user["_id"])}})
    return {"ok": True}
