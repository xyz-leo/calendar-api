from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import router as auth_router
from app.database import Base, engine, get_db
from app.events import router as events_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Calendar API", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(events_router)


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    # A liveness check that can't fail tells you the process is running, nothing
    # more. Touching the database is what actually distinguishes "up" from "up
    # but its only real dependency is broken."
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
