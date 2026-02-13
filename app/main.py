from fastapi import FastAPI

from app.api.routes import router as agent_router
from app.plugins import auto_discover

app = FastAPI(title="AI Agent", version="0.1.0")

# Discover and register plugins
auto_discover()

# Include routers
app.include_router(agent_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
