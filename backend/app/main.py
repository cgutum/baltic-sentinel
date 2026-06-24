"""Baltic Sentinel backend entrypoint.

Run:
    uvicorn app.main:app --reload --port 8000

H0 goal: GET /health returns {"ok": true}.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router

app = FastAPI(title="Baltic Sentinel", version="0.1.0")

# Allow the local frontend (and Vercel later) to call us during the demo.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
def health():
    """Liveness check. Done-when target for H0-H1."""
    return {"ok": True}
