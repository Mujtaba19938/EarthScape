"""EarthScape API. Also serves the website, so both share one address."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import config
from .db import ensure_indexes
from .routes_auth import router as auth_router
from .routes_data import router as data_router
from .routes_ops import router as ops_router

app = FastAPI(title="EarthScape API", version="0.2.0")
app.include_router(auth_router)
app.include_router(data_router)
app.include_router(ops_router)


@app.on_event("startup")
def startup():
    ensure_indexes()


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
