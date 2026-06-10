from __future__ import annotations

import json
import logging
import re

from pydantic import ValidationError

from agent.manifest_schema import PitchManifest
from utils.api_client import api_request
from utils.credits import CreditTracker
from utils.models import QWEN_DIRECTOR
from utils.timing import CHARS_PER_SECOND, estimate_duration_sec

logger = logging.getLogger(__name__)

MAX_MANIFEST_ATTEMPTS = 3

DIRECTOR_SYSTEM_PROMPT = f"""You are a startup pitch video director. Given a one-line startup idea, produce a scene manifest for a 3-scene pitch video.

Output ONLY valid JSON matching this schema — no preamble, no markdown fences, no explanation:
{{
  "pitch_title": string,
  "pitch_vibe": "sleek_b2b" | "scrappy_technical" | "consumer_emotional",
  "scenes": [
    {{
      "scene_id": int,
      "role": "opener" | "problem" | "solution" | "cta",
      "narration_text": string,
      "visual_prompt": string,
      "motion_prompt": string,
      "duration_sec": float,
      "is_hero": bool
    }}
  ]
}}

Rules:
- Exactly 3 scenes with scene_id 1, 2, 3.
- Scene 1 role must be "opener" with is_hero=true. Scenes 2 and 3 must have is_hero=false.
- Use roles: opener (scene 1), problem (scene 2), solution or cta (scene 3).
- Total duration_sec across all scenes must be between 12 and 18 seconds.
- Compute duration_sec as len(narration_text) / {CHARS_PER_SECOND} using CHARACTER count (not word count), rounded to 1 decimal place.
- Each narration_text must be 55–90 characters long (punchy but substantial — roughly 10–18 words).
- Total character count across all 3 narrations must be 174–261 characters.
- visual_prompt and motion_prompt must be separate strings optimized for image gen and video gen respectively.
- visual_prompt: cinematic still frame description for seedream-5-0-lite.
- motion_prompt: camera/subject motion description for video generation."""


def _extract_json(raw: str) -> dict:
    """Parse JSON from model output, stripping markdown fences if present."""
    text = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fence_match:
        text = fence_match.group(1).strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected JSON object, got {type(parsed).__name__}")
    return parsed


def _normalize_manifest(data: dict) -> dict:
    """Ensure duration_sec is computed correctly from narration character length."""
    scenes = data.get("scenes")
    if not isinstance(scenes, list):
        raise ValueError("manifest missing scenes array")

    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        narration = scene.get("narration_text", "")
        scene["duration_sec"] = estimate_duration_sec(narration)
        scene["is_hero"] = scene.get("scene_id") == 1
    return data


async def _call_director(messages: list[dict], credit_tracker: CreditTracker) -> dict:
    payload = {
        "model": QWEN_DIRECTOR,
        "messages": messages,
        "temperature": 0.7,
    }
    response = await api_request("POST", "/chat/completions", json_body=payload)

    choices = response.get("choices") or []
    if not choices:
        raise ValueError("Director returned no choices")

    content = choices[0].get("message", {}).get("content", "")
    if not content or not str(content).strip():
        raise ValueError("Director returned empty content")

    token_estimate = float(response.get("usage", {}).get("total_tokens", 1500))
    credit_tracker.log_chat(QWEN_DIRECTOR, "director", token_estimate)
    return _extract_json(str(content))


async def generate_manifest(
    idea: str,
    credit_tracker: CreditTracker,
) -> PitchManifest:
    """Call the director agent to produce a validated pitch manifest."""
    messages: list[dict] = [
        {"role": "system", "content": DIRECTOR_SYSTEM_PROMPT},
        {"role": "user", "content": f"Startup idea: {idea}"},
    ]

    last_error: Exception | None = None

    for attempt in range(1, MAX_MANIFEST_ATTEMPTS + 1):
        try:
            raw_data = await _call_director(messages, credit_tracker)
            normalized = _normalize_manifest(raw_data)
            manifest = PitchManifest.model_validate(normalized)
            logger.info(
                "Director manifest: %s (%d scenes, attempt %d)",
                manifest.pitch_title,
                len(manifest.scenes),
                attempt,
            )
            return manifest
        except (ValidationError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
            last_error = exc
            if isinstance(exc, ValidationError):
                error_summary = "; ".join(
                    f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
                    for err in exc.errors()
                )
            else:
                error_summary = str(exc)

            logger.warning(
                "Manifest failed (attempt %d/%d): %s",
                attempt,
                MAX_MANIFEST_ATTEMPTS,
                error_summary,
            )
            if attempt < MAX_MANIFEST_ATTEMPTS:
                if isinstance(exc, ValidationError):
                    messages.append(
                        {"role": "assistant", "content": json.dumps(normalized)}
                    )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your JSON failed validation: {error_summary}. "
                            f"Fix it. Remember: duration_sec = len(narration_text) / {CHARS_PER_SECOND} "
                            "(character count). Total duration must be 12–18 seconds. "
                            "Each narration_text needs 55–90 characters. "
                            "Output ONLY corrected JSON, no markdown."
                        ),
                    }
                )

    raise RuntimeError(
        f"Director failed to produce a valid manifest after {MAX_MANIFEST_ATTEMPTS} attempts: {last_error}"
    ) from last_error
