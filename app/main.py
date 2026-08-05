from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, Response
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import router as auth_router
from app.database import Base, engine, get_db
from app.events import router as events_router
from app.rate_limit import limiter
from app.tasks import router as tasks_router

STATIC_DIR = Path(__file__).resolve().parent / "static"

# CSP allows 'unsafe-inline' for script/style because app/static/index.html is a single
# self-contained file by design (see docs/architecture.md) — no external script/style
# host to move them to without a build step. Still meaningfully narrower than no CSP at
# all: blocks plugins (object-src), base-tag hijacking, framing, and any resource load
# from anywhere but this origin (img-src's "data:" exception is only for the inline SVG
# favicon). See tmp/learning-security-testing.md for the full reasoning.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    ),
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


# docs_url/redoc_url/openapi_url disabled: the auto-generated schema and interactive
# "try it out" console were reachable by anyone, unauthenticated — see
# tmp/learning-security-testing.md Part 2. This is a single-user personal API with no
# external integrators who'd need that documentation.
app = FastAPI(
    title="Calendar API",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
# app.state.limiter + this exception handler are what SlowAPIMiddleware and
# every @limiter.limit(...) decorator actually rely on — the middleware alone
# is not enough. default_limits from app/rate_limit.py (RATE_LIMIT in .env)
# apply to every route automatically; individual routes can override with
# their own @limiter.limit(...) (see app/auth.py's login/callback).
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.include_router(auth_router)
app.include_router(events_router)
app.include_router(tasks_router)


@app.middleware("http")
async def security_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers.update(_SECURITY_HEADERS)
    return response


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    # The read-only web client — same origin as the API itself (see app/auth.py's
    # cookie-based login branch), so it needs no CORS and no configurable server URL.
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    # A liveness check that can't fail tells you the process is running, nothing
    # more. Touching the database is what actually distinguishes "up" from "up
    # but its only real dependency is broken."
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
