from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response, status
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from sqlalchemy import text

from api import jobs, push, versions
from api.auth import CurrentUserDep
from api.deps import ApiSettingsDep, LimiterDep, QueueDep, RedisDep, SessionDep
from api.observability import metrics_response, time_requests
from api.schemas import MeOut
from tabscribe_platform.observability import configure_logging, configure_tracing


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging("api")
    configure_tracing("api")
    yield


app = FastAPI(title="TabScribe API", version="0.1.0", lifespan=lifespan)
app.include_router(jobs.router)
app.include_router(push.router)
app.include_router(versions.router)
app.middleware("http")(time_requests)
# One span per request; the submit span becomes the root of the job's trace.
FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics")


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


@app.get("/metrics", include_in_schema=False)
def metrics(queue: QueueDep) -> Response:
    """Prometheus metrics (internal: not routed to clients)."""
    return metrics_response(queue)


@app.get("/me")
def me(user: CurrentUserDep, limiter: LimiterDep, limits: ApiSettingsDep) -> MeOut:
    """Who the bearer token belongs to, and how much of this month's quota is used."""
    return MeOut(
        user_id=user.id,
        jobs_this_month=limiter.monthly_jobs_used(user.id),
        jobs_per_month=limits.free_jobs_per_month,
    )
