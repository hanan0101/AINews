"""Rate limiting and batching helpers for Gemini-backed processing."""

from __future__ import annotations

import time
from threading import Lock
from typing import Any, Callable


class GeminiRateLimiter:
    """Enforces a safe request cadence below Gemini's 15 requests/minute limit."""

    def __init__(self, min_interval_seconds: float = 6.0):
        self.min_interval = min_interval_seconds
        self.last_call = 0.0
        self.lock = Lock()

    def wait(self) -> None:
        with self.lock:
            elapsed = time.time() - self.last_call
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self.last_call = time.time()


_limiter = GeminiRateLimiter()


def wait_for_gemini_slot() -> None:
    _limiter.wait()


def process_candidates_in_batches(
    candidates: list[Any],
    processor_fn: Callable[[Any], Any],
    batch_size: int = 5,
) -> dict[str, Any]:
    """Process candidates in small batches and keep going after failures."""
    successful: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    total_batches = (len(candidates) + batch_size - 1) // batch_size

    for index in range(0, len(candidates), batch_size):
        batch = candidates[index:index + batch_size]
        batch_num = (index // batch_size) + 1
        print(f"[{batch_num}/{total_batches}] Processing {len(batch)} candidates...", flush=True)

        for candidate in batch:
            try:
                result = processor_fn(candidate)
                successful.append({"candidate": candidate, "result": result})
            except Exception as exc:
                print(f"  Failed: {exc}", flush=True)
                failed.append({"candidate": candidate, "error": str(exc)})
                continue

        if index + batch_size < len(candidates):
            time.sleep(3)

    return {
        "successful": successful,
        "failed": failed,
        "success_rate": len(successful) / len(candidates) if candidates else 0,
    }


def evaluate_run(processing_result: dict[str, Any], min_required: int = 6) -> dict[str, Any]:
    successful_count = len(processing_result.get("successful") or [])
    if successful_count >= min_required:
        return {"status": "success", "count": successful_count}
    if successful_count >= min_required // 2:
        return {
            "status": "partial",
            "count": successful_count,
            "warning": f"Only {successful_count} succeeded out of {min_required} required",
        }
    return {
        "status": "insufficient",
        "count": successful_count,
        "error": "Not enough candidates processed",
    }
