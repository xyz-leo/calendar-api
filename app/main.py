from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import router as auth_router
from app.database import Base, engine, get_db
from app.events import router as events_router
from app.rate_limit import limiter


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Calendar API", lifespan=lifespan)
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


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    # A liveness check that can't fail tells you the process is running, nothing
    # more. Touching the database is what actually distinguishes "up" from "up
    # but its only real dependency is broken."
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
