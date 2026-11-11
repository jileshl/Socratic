"""FastAPI service: student chat, teacher view, static files, and API router mounting.

    uvicorn socratic_tutor.web.server:app --host 0.0.0.0 --port 8000
    python -m socratic_tutor.app            (same thing)

Pages:  /            student view (practice and quiz modes)
        /teacher     teacher view (PIN login; the login decides the role, never chat text)
        /static/{n}  static assets (css, js, images)
API routes are implemented in socratic_tutor.web.api and mounted onto this app.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from socratic_tutor import config, trace
from socratic_tutor.web.api import (  # noqa: F401 - re-exported for backwards compatibility
    REFUSAL,
    NODE_DECIDER,
    api_router,
    graph,
    learners,
    ops,
    router,
)

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Automated retention policy enforcement: purge learner records older than 90 days on startup."""
    try:
        purged = learners.purge_expired_profiles(days=90)
        if purged:
            trace.record("retention_maintenance", purged_profiles=purged)
    except Exception:
        pass
    yield


app = FastAPI(title="Socratic Tutor", version=config.CONFIG_VERSION, lifespan=lifespan)

# Mount API routes
app.include_router(api_router)


# ------------------------------------------------------------------ frontend pages


@app.get("/", include_in_schema=False)
def student_page() -> FileResponse:
    return FileResponse(STATIC / "student.html")


@app.get("/teacher", include_in_schema=False)
def teacher_page() -> FileResponse:
    return FileResponse(STATIC / "teacher.html")


@app.get("/static/{name}", include_in_schema=False)
def static_file(name: str) -> FileResponse:
    path = (STATIC / name).resolve()
    if path.parent != STATIC.resolve() or not path.exists():
        raise HTTPException(404)
    return FileResponse(path)
