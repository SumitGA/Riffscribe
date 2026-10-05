"""FastAPI dependencies. Clients are created once per process (connection pools); tests replace
them through `app.dependency_overrides`. No request state is kept between requests."""

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

import redis
from fastapi import Depends
from sqlalchemy.orm import Session, sessionmaker

from api.limits import Limiter
from api.settings import ApiSettings
from tabscribe_platform.db import make_engine, make_session_factory
from tabscribe_platform.jobqueue import JobQueue, RedisJobQueue
from tabscribe_platform.settings import Settings, get_settings
from tabscribe_platform.storage import ObjectStore


@lru_cache
def get_api_settings() -> ApiSettings:
    return ApiSettings()


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return make_session_factory(make_engine(str(get_settings().database_url)))


def get_session(
    factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> Iterator[Session]:
    with factory() as session:
        yield session


@lru_cache
def get_redis() -> "redis.Redis":
    return redis.Redis.from_url(str(get_settings().redis_url), decode_responses=True)


@lru_cache
def get_object_store() -> ObjectStore:
    return ObjectStore(get_settings())


@lru_cache
def get_job_queue() -> JobQueue:
    settings = get_settings()
    return RedisJobQueue(get_redis(), visibility_timeout_s=settings.queue_visibility_timeout_s)


@lru_cache
def get_limiter() -> Limiter:
    return Limiter(get_redis())


SettingsDep = Annotated[Settings, Depends(get_settings)]
ApiSettingsDep = Annotated[ApiSettings, Depends(get_api_settings)]
SessionDep = Annotated[Session, Depends(get_session)]
RedisDep = Annotated["redis.Redis", Depends(get_redis)]
StoreDep = Annotated[ObjectStore, Depends(get_object_store)]
QueueDep = Annotated[JobQueue, Depends(get_job_queue)]
LimiterDep = Annotated[Limiter, Depends(get_limiter)]
