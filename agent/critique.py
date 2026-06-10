from __future__ import annotations

import logging
from pathlib import Path

from utils.api_client import api_request
from utils.credits import CreditTracker
from utils.media import local_image_to_data_uri
from utils.models import VISION_CRITIQUE

logger = logging.getLogger(__name__)

CRITIQUE_SYSTEM_PROMPT = (
    "You are a video director. Analyze this image and the intended motion prompt. "
    "Identify anything in the image composition that would cause the motion to look wrong "
    "(wrong subject position, conflicting depth, ambiguous foreground). "
    "Return ONLY a revised motion_prompt string that accounts for the actual image. "
    "If nothing needs changing, return the original."
)


async def critique_motion_prompt(
    image_path: Path,
    motion_prompt: str,
    credit_tracker: CreditTracker,
) -> str:
    """Run vision critique on a generated image and return a revised motion prompt."""
    try:
        image_uri = local_image_to_data_uri(image_path)
        payload = {
            "model": VISION_CRITIQUE,
            "messages": [
                {"role": "system", "content": CRITIQUE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Intended motion prompt: {motion_prompt}",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": image_uri},
                        },
                    ],
                },
            ],
            "temperature": 0.3,
        }

        response = await api_request("POST", "/chat/completions", json_body=payload)
        choices = response.get("choices") or []
        if not choices:
            raise ValueError("Vision critique returned no choices")

        revised = choices[0].get("message", {}).get("content", "").strip()
        token_estimate = float(response.get("usage", {}).get("total_tokens", 500))
        credit_tracker.log_chat(VISION_CRITIQUE, "vision", token_estimate)

        if revised:
            logger.info("Vision critique revised motion prompt for %s", image_path.name)
            return revised
        return motion_prompt
    except Exception as exc:
        logger.warning(
            "Vision critique failed for %s, using original motion_prompt: %s",
            image_path.name,
            exc,
        )
        return motion_prompt
