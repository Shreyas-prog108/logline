from __future__ import annotations

import asyncio
import logging
from typing import Any

from utils.api_client import api_request

logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 3.0
MAX_POLL_SEC = 600.0
TERMINAL_FAILURE_STATUSES = {"failed", "error", "cancelled"}


def _normalize_poll_path(poll_url: str) -> str:
    """Convert Empirio poll_url to a path relative to /v1."""
    if poll_url.startswith("/v1/"):
        return poll_url[len("/v1") :]
    if poll_url.startswith("/"):
        return poll_url
    return f"/jobs/{poll_url}"


async def poll_job(poll_url: str) -> dict[str, Any]:
    """Poll an Empirio async job until completed or failed."""
    elapsed = 0.0
    path = _normalize_poll_path(poll_url)

    while elapsed < MAX_POLL_SEC:
        response = await api_request("GET", path)
        status = response.get("status", "")

        if status == "completed":
            return response
        if status in TERMINAL_FAILURE_STATUSES:
            error_detail = response.get("error") or response.get("message") or status
            raise RuntimeError(f"Job failed: {error_detail}")

        progress = response.get("progress")
        if progress is not None:
            logger.debug("Job %s progress: %s", path, progress)

        await asyncio.sleep(POLL_INTERVAL_SEC)
        elapsed += POLL_INTERVAL_SEC

    raise TimeoutError(f"Job timed out after {MAX_POLL_SEC}s: {path}")


async def wait_for_async_response(response: dict[str, Any]) -> dict[str, Any]:
    """Poll when needed; pass through sync or already-completed responses."""
    if response.get("status") == "completed":
        return response

    poll_target = response.get("poll_url")
    if not poll_target and response.get("job_id"):
        poll_target = response["job_id"]

    if poll_target:
        return await poll_job(poll_target)

    return response


def extract_media_url(job_response: dict[str, Any]) -> str:
    """Extract the first media URL from a completed job or sync response."""
    candidates: list[dict[str, Any]] = []

    result = job_response.get("result")
    if isinstance(result, dict):
        candidates.extend(result.get("data") or [])

    candidates.extend(job_response.get("data") or [])

    for item in candidates:
        if isinstance(item, dict) and item.get("url"):
            return item["url"]

    raise RuntimeError(f"No media URL in response: {list(job_response.keys())}")
