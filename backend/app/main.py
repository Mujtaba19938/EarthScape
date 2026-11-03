"""EarthScape API. Also serves the website, so both share one address."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pymongo.errors import PyMongoError

from . import config
from .db import db, ensure_indexes
from .routes_auth import router as auth_router
from .routes_data import router as data_router
from .routes_live import router as live_router
from .routes_ml import router as ml_router
from .routes_ops import router as ops_router
from .routes_status import router as status_router

app = FastAPI(title="EarthScape API", version="0.5.0")
app.include_router(auth_router)
app.include_router(data_router)
app.include_router(live_router)
app.include_router(ml_router)
app.include_router(ops_router)
app.include_router(status_router)


@app.on_event("startup")
def startup():
    ensure_indexes()


@app.middleware("http")
async def add_response_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-EarthScape-Instance"] = config.INSTANCE_NAME
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@app.get("/api/health")
def health():
    """The load balancer stops sending people to an instance that can't reach the database."""
    try:
        db.command("ping")
    except PyMongoError:
        return JSONResponse({"status": "unavailable", "instance": config.INSTANCE_NAME}, status_code=503)
    return {"status": "ok", "instance": config.INSTANCE_NAME}


app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
