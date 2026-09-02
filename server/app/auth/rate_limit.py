import time
from collections import defaultdict, deque


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
        return True

    def reset(self) -> None:
        """Clears all tracked events. Exists for test isolation — this is a
        module-level singleton, so without a reset, one test's login
        attempts count against the next test's rate-limit budget."""
        self._events.clear()


login_rate_limiter = InMemoryRateLimiter(max_events=10, window_seconds=60)
