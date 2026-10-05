from fastapi import FastAPI

from api.auth import CurrentUserDep

app = FastAPI(title="TabScribe API", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness: the process is up. Readiness (database, Redis) is `/readyz`, added with them."""
    return {"status": "ok"}


@app.get("/me")
def me(user: CurrentUserDep) -> dict[str, str]:
    """Who the bearer token belongs to. Handy for checking a token with curl."""
    return {"user_id": user.id}
