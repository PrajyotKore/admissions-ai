import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .db import Base, engine
from . import models  # noqa: F401  (register tables)
from .routers import admin, auth, calls, dashboard, knowledge, leads, public

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("app")

app = FastAPI(title="Admissions AI Platform", version="0.1.0")

if settings.environment == "development":
    # Dev convenience only; production must use Alembic migrations (not yet added).
    Base.metadata.create_all(engine)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                   allow_methods=["*"], allow_headers=["*"])

for r in (auth.router, leads.router, dashboard.router, admin.router, knowledge.router, public.router, calls.router):
    app.include_router(r, prefix="/api")


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    # Log the exception type only: payloads may contain PII.
    log.error("unhandled error on %s %s: %s", request.method, request.url.path, type(exc).__name__)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


@app.get("/api/health")
def health():
    return {"status": "ok"}
