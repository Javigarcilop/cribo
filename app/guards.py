"""Límites sencillos para controlar coste y abuso (en memoria, válidos para una demo)."""
import os
import time
from collections import deque

MAX_LLM_CALLS_PER_HOUR = int(os.getenv("MAX_LLM_CALLS_PER_HOUR", "200"))
MAX_REQUESTS_PER_MINUTE = int(os.getenv("MAX_REQUESTS_PER_MINUTE", "20"))

_llm_calls: deque[float] = deque()
_requests: dict[str, deque[float]] = {}


def _prune(q: deque[float], window: float) -> None:
    now = time.time()
    while q and now - q[0] > window:
        q.popleft()


def allow_request(client_ip: str) -> bool:
    q = _requests.setdefault(client_ip, deque())
    _prune(q, 60)
    if len(q) >= MAX_REQUESTS_PER_MINUTE:
        return False
    q.append(time.time())
    return True


def reserve_llm_calls(n: int) -> bool:
    """Reserva n llamadas al modelo dentro del presupuesto horario."""
    _prune(_llm_calls, 3600)
    if len(_llm_calls) + n > MAX_LLM_CALLS_PER_HOUR:
        return False
    now = time.time()
    _llm_calls.extend([now] * n)
    return True


def reset() -> None:
    _llm_calls.clear()
    _requests.clear()
