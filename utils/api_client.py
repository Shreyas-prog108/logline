from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

EMPIRIO_BASE_URL = "https://api.empiriolabs.ai/v1"
MAX_RETRIES = 3
INITIAL_BACKOFF_SEC = 1.0


def get_api_key() -> str:
    api_key = os.getenv("EMPIRIO_API_KEY", "")
    if not api_key:
        raise RuntimeError("EMPIRIO_API_KEY environment variable is not set")
    return api_key


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {get_api_key()}",
        "Content-Type": "application/json",
    }


async def api_request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: float = 300.0,
    expect_binary: bool = False,
) -> dict[str, Any] | bytes:
    """Execute an Empirio API request with exponential backoff (max 3 retries)."""
    url = f"{EMPIRIO_BASE_URL}{path}"
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(
                    method,
                    url,
                    headers=_auth_headers(),
                    json=json_body,
                )
                response.raise_for_status()
                if not response.content:
                    return b"" if expect_binary else {}
                if expect_binary:
                    content_type = response.headers.get("content-type", "")
                    if "application/json" in content_type:
                        return response.json()
                    return response.content
                return response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text
            try:
                body = exc.response.json()
                detail = body.get("error", {}).get("message", detail)
            except Exception:
                pass
            last_error = RuntimeError(f"{exc.response.status_code} {path}: {detail}")
            if exc.response.status_code < 500 and exc.response.status_code != 429:
                break
        except Exception as exc:
            last_error = exc

        if attempt < MAX_RETRIES - 1:
            backoff = INITIAL_BACKOFF_SEC * (2**attempt)
            logger.warning(
                "API request failed (attempt %d/%d): %s — retrying in %.1fs",
                attempt + 1,
                MAX_RETRIES,
                last_error,
                backoff,
            )
            await asyncio.sleep(backoff)
        else:
            logger.error(
                "API request failed after %d attempts: %s",
                MAX_RETRIES,
                last_error,
            )

    raise RuntimeError(f"API request to {path} failed: {last_error}") from last_error


async def download_binary(url: str, dest_path: str) -> None:
    """Download binary content from a URL with retry logic."""
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                with open(dest_path, "wb") as file_handle:
                    file_handle.write(response.content)
                return
        except Exception as exc:
            last_error = exc
            if attempt < MAX_RETRIES - 1:
                backoff = INITIAL_BACKOFF_SEC * (2**attempt)
                await asyncio.sleep(backoff)

    raise RuntimeError(f"Failed to download {url}: {last_error}") from last_error
