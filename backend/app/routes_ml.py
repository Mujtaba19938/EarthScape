"""Results of the saved training runs, and the button that starts a new one."""
import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from . import ml_client
from .db import db
from .security import current_user, require_admin

router = APIRouter(prefix="/api/ml")

BASELINE = "persistence"


def _scores(score):
    """Final-decade error of the chosen method and of the baseline, from one series' results."""
    errors = {row["method"]: row["test_rmse"] for row in score["comparison"]}
    return errors[score["chosen_method"]], errors[BASELINE]


def _history_row(run):
    scores = run["forecast_scores"]
    chosen = [_scores(score) for score in scores]
    global_scores = next((_scores(score) for score in scores if score["series"] == "Glob"), (None, None))
    return {
        "version": run["version"],
        "trained_at": run["trained_at"],
        "triggered_by": run["triggered_by"],
        "global_test_rmse": global_scores[0],
        "global_baseline_rmse": global_scores[1],
        "series_beating_baseline": sum(1 for model, baseline in chosen if model < baseline),
        "series_count": len(chosen),
        "false_alarm_rate": run["anomaly"]["false_alarm_rate"],
        "recall_by_spike_size": run["anomaly"]["recall_by_spike_size"],
    }


@router.get("/summary")
def summary(_user=Depends(current_user)):
    runs = list(db.ml_runs.find({}, {"_id": 0}).sort("trained_at", -1).limit(10))
    for run in runs:
        run["trained_at"] = run["trained_at"].replace(tzinfo=datetime.timezone.utc)
    return {
        "retraining": ml_client.is_running(),
        "latest": runs[0] if runs else None,
        "history": [_history_row(run) for run in runs],
    }


@router.get("/forecast")
def forecast(series: str = "Glob", _user=Depends(current_user)):
    document = db.ml_forecasts.find_one({"series": series}, {"_id": 0})
    if not document:
        raise HTTPException(status_code=404, detail="No forecast for that series.")
    return document


@router.get("/anomalies")
def anomalies(limit: int = Query(50, ge=1, le=500), _user=Depends(current_user)):
    return list(db.ml_anomalies.find({}, {"_id": 0}).sort("score", -1).limit(limit))


@router.get("/correlations")
def correlations(_user=Depends(current_user)):
    return list(db.ml_correlations.find({}, {"_id": 0}))


@router.post("/retrain", status_code=202)
def retrain(admin=Depends(require_admin)):
    if not ml_client.start_training(admin["name"]):
        raise HTTPException(status_code=409, detail="Training is already running.")
    return {"started": True}
