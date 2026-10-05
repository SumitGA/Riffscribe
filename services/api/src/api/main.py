from fastapi import FastAPI

app = FastAPI(title="TabScribe API", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness: the process is up. Readiness (database, Redis) is `/readyz`, added with them."""
    return {"status": "ok"}
