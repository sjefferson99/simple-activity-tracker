import time
from collections import defaultdict, deque

# Above this many distinct keys, allow() evicts the oldest-touched key before
# adding a new one — bounds memory for a process that runs indefinitely and
# sees a steady trickle of distinct IPs/emails (see
# docs/SERVER-PRODUCTION-PLAN.md S6). Generous relative to any real self-hosted
# instance's traffic; only matters against sustained scanning/abuse.
_MAX_TRACKED_KEYS = 10_000


class InMemoryRateLimiter:
    """A simple sliding-window limiter, keyed by an arbitrary string (IP,
    email, "ip:email", ...). Single-process only — fine for the intended
    scale of a self-hosted instance behind one uvicorn worker; would need a
    shared store (Redis) if the app ever runs multiple workers/replicas."""

    def __init__(self, max_events: int, window_seconds: float) -> None:
        self._max_events = max_events
        self._window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        events = self._events[key]
        while events and now - events[0] > self._window_seconds:
            events.popleft()
        if len(events) >= self._max_events:
            return False
        events.append(now)
        if len(self._events) > _MAX_TRACKED_KEYS:
            self._prune_empty_and_evict_oldest()
        return True

    def _prune_empty_and_evict_oldest(self) -> None:
        # Only scans the whole map once the cap is actually exceeded, not on
        # every call — cheap in the common case where a self-hosted instance
        # never sees enough distinct keys to hit the cap at all.
        empty_keys = [key for key, events in self._events.items() if not events]
        for key in empty_keys:
            del self._events[key]
        while len(self._events) > _MAX_TRACKED_KEYS:
            oldest_key = next(iter(self._events))
            del self._events[oldest_key]

    def reset(self) -> None:
        """Clears all tracked events. Exists for test isolation — this is a
        module-level singleton, so without a reset, one test's login
        attempts count against the next test's rate-limit budget."""
        self._events.clear()


login_rate_limiter = InMemoryRateLimiter(max_events=10, window_seconds=60)

# Separate from login_rate_limiter: register and password-change are lower
# volume under normal use than login, so a tighter budget doesn't cost
# legitimate users anything, while still throttling credential-stuffing
# against /register or the "current password" field (see
# docs/SERVER-PRODUCTION-PLAN.md S6). Keyed by IP only (no email/account
# concept for a not-yet-existing registration).
account_action_rate_limiter = InMemoryRateLimiter(max_events=5, window_seconds=60)
