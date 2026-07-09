from fastapi import FastAPI

from app.api.routes_knowledge import router as knowledge_router
from app.api.routes_settings import router as settings_router

app = FastAPI(title="Cyber Interview Agent API")
app.include_router(settings_router)
app.include_router(knowledge_router)

@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
