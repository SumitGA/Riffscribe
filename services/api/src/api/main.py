from fastapi import FastAPI, HTTPException, status
from sqlalchemy import text

from api import jobs
from api.auth import CurrentUserDep
from api.deps import ApiSettingsDep, LimiterDep, RedisDep, SessionDep
from api.schemas import MeOut

app = FastAPI(title="TabScribe API", version="0.1.0")
app.include_router(jobs.router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness: the process is up."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz(session: SessionDep, redis_client: RedisDep) -> dict[str, str]:
    """Readiness: Postgres and Redis answer. Object storage isn't checked: it's a remote service
    whose outage shouldn't take every API instance out of the load balancer."""
    try:
        session.execute(text("SELECT 1"))
        redis_client.ping()
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "not ready") from exc
    return {"status": "ok"}


@app.get("/me")
def me(user: CurrentUserDep, limiter: LimiterDep, limits: ApiSettingsDep) -> MeOut:
    """Who the bearer token belongs to, and how much of this month's quota is used."""
    return MeOut(
        user_id=user.id,
        jobs_this_month=limiter.monthly_jobs_used(user.id),
        jobs_per_month=limits.free_jobs_per_month,
    )
