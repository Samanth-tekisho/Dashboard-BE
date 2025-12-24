from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import analytics_router

from contextlib import asynccontextmanager
import asyncio
from services.mom_worker import start_mom_worker

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start the background worker
    asyncio.create_task(start_mom_worker())
    yield

app = FastAPI(
    title="Business Card Analytics API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analytics_router.router)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def root():
    return {"message": "Welcome to Business Card Analytics API. Visit /docs for API documentation."}

# Reload trigger 2
