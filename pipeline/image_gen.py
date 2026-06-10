from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from agent.manifest_schema import SceneManifest
from utils.api_client import api_request, download_binary
from utils.credits import CreditTracker
from utils.jobs import extract_media_url, wait_for_async_response
from utils.media import SceneImage
from utils.models import SEEDREAM_5_LITE

logger = logging.getLogger(__name__)


async def generate_scene_image(
    scene: SceneManifest,
    output_dir: Path,
    credit_tracker: CreditTracker,
) -> SceneImage:
    """Generate a still image for one scene."""
    dest_path = output_dir / f"scene_{scene.scene_id}_image.png"
    payload = {
        "model": SEEDREAM_5_LITE,
        "prompt": scene.visual_prompt,
        "aspect_ratio": "16:9",
        "num_images": 1,
    }

    response = await api_request("POST", "/images/generations", json_body=payload)
    response = await wait_for_async_response(response)

    credit_tracker.log_image(SEEDREAM_5_LITE)
    remote_url = extract_media_url(response)
    await download_binary(remote_url, str(dest_path))
    logger.info("Generated image for scene %d -> %s", scene.scene_id, dest_path)
    return SceneImage(local_path=dest_path, remote_url=remote_url)


async def generate_all_images(
    scenes: list[SceneManifest],
    output_dir: Path,
    credit_tracker: CreditTracker,
) -> dict[int, SceneImage]:
    """Generate images for all scenes in parallel."""
    tasks = [
        generate_scene_image(scene, output_dir, credit_tracker) for scene in scenes
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    image_assets: dict[int, SceneImage] = {}
    for scene, result in zip(scenes, results):
        if isinstance(result, Exception):
            logger.error("Image gen failed for scene %d: %s", scene.scene_id, result)
            raise result
        image_assets[scene.scene_id] = result

    return image_assets
