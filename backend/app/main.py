import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.db.database import Base, engine, migrate_sqlite_columns
from app.models.transaction import Transaction  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    migrate_sqlite_columns()
    yield


app = FastAPI(title="ClearTrace AML Investigation API", version="1.0.0", lifespan=lifespan,
              description="Risk triage and transaction investigation demo. Indicators are not proof of money laundering.")
origins = os.getenv("API_CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
