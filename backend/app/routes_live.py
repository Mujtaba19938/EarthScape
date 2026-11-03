"""Latest live readings, their history, and a button to check straight away."""
import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from . import alert_checks, live, locks
from .db import db
from .security import current_user, require_admin

router = APIRouter(prefix="/api/live")

POLL_LOCK = "live_poll"
POLL_LOCK_SECONDS = 120
HIDDEN_FIELDS = {"_id": 0, "archived": 0, "fetched_at": 0}


def _public(reading):
    return {key: value for key, value in reading.items() if key not in HIDDEN_FIELDS}


@router.get("/latest")
def latest(_user=Depends(current_user)):
    return {"status": live.status(), "readings": [_public(row) for row in alert_checks.latest_readings()]}


@router.get("/history")
def history(location: str, hours: int = Query(48, ge=1, le=720), _user=Depends(current_user)):
    if location not in live.LOCATION_NAMES:
        raise HTTPException(status_code=404, detail="Unknown location.")
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    rows = db.live_readings.find({"location": location, "observed_at": {"$gte": since}}, HIDDEN_FIELDS)
    return list(rows.sort("observed_at", 1))


@router.post("/poll")
def poll_now(admin=Depends(require_admin)):
    if not locks.acquire(POLL_LOCK, POLL_LOCK_SECONDS):
        raise HTTPException(status_code=409, detail="A check is already running.")
    try:
        record = live.poll(admin["name"])
    finally:
        locks.release(POLL_LOCK)
    if not record["ok"]:
        raise HTTPException(status_code=502, detail="Couldn't reach Open-Meteo. Try again shortly.")
    record.pop("_id", None)
    return record
