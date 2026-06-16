import json
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import companies, teams, apis, endpoints, triples


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="SLM Knowledge Platform", lifespan=lifespan)

origins = json.loads(os.environ.get("BACKEND_CORS_ORIGINS", '["http://localhost:3000"]'))
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(companies.router, prefix="/api/v1")
app.include_router(teams.router, prefix="/api/v1")
app.include_router(apis.router, prefix="/api/v1")
app.include_router(endpoints.router, prefix="/api/v1")
app.include_router(triples.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}
