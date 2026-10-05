"""Per-user quotas and rate limits, kept in Redis so every API instance sees the same counts."""

from datetime import UTC, datetime

import redis

_MONTH_TTL_S = 40 * 24 * 3600  # a monthly counter outlives its month, then expires


class Limiter:
    def __init__(self, client: "redis.Redis", *, prefix: str = "tabscribe:limits") -> None:
        self._redis = client
        self._prefix = prefix

    def _month_key(self, user_id: str, now: datetime | None) -> str:
        month = (now or datetime.now(UTC)).strftime("%Y-%m")
        return f"{self._prefix}:jobs:{user_id}:{month}"

    def take_monthly_job(self, user_id: str, limit: int, *, now: datetime | None = None) -> bool:
        """Count one job against this month's quota; False (and nothing counted) if it's used up."""
        key = self._month_key(user_id, now)
        with self._redis.pipeline() as pipe:
            pipe.incr(key)
            pipe.expire(key, _MONTH_TTL_S)
            used, _ = pipe.execute()
        if int(used) > limit:
            self._redis.decr(key)
            return False
        return True

    def refund_monthly_job(self, user_id: str, *, now: datetime | None = None) -> None:
        self._redis.decr(self._month_key(user_id, now))

    def monthly_jobs_used(self, user_id: str, *, now: datetime | None = None) -> int:
        value = self._redis.get(self._month_key(user_id, now))
        return max(0, int(str(value))) if value is not None else 0

    def hit(self, user_id: str, action: str, limit: int, window_s: int) -> bool:
        """Fixed-window rate limit: False once `limit` hits happened in the current window."""
        window = int(datetime.now(UTC).timestamp()) // window_s
        key = f"{self._prefix}:rate:{action}:{user_id}:{window}"
        with self._redis.pipeline() as pipe:
            pipe.incr(key)
            pipe.expire(key, window_s)
            count, _ = pipe.execute()
        return int(count) <= limit
