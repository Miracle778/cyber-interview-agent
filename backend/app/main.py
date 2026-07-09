from fastapi import FastAPI

from app.api.routes_settings import router as settings_router

app = FastAPI(title="Cyber Interview Agent API")
app.include_router(settings_router)

@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
