from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from agent.manifest_schema import SceneManifest
from router.model_router import route_video_model
from utils.api_client import api_request, download_binary
from utils.credits import CreditTracker
from utils.jobs import extract_media_url, wait_for_async_response
from utils.media import SceneImage, local_image_to_data_uri
from utils.models import KLING_O3, SEEDANCE_2_PRO, WAN_2_7

logger = logging.getLogger(__name__)


def _image_reference(image: SceneImage | None) -> str | None:
    if image is None:
        return None
    return image.remote_url or local_image_to_data_uri(image.local_path)


def _build_video_payload(
    scene: SceneManifest,
    model: str,
    image: SceneImage | None,
) -> dict:
    duration = max(1, round(scene.duration_sec))
    payload: dict = {
        "model": model,
        "prompt": scene.motion_prompt,
        "duration": duration,
        "aspect_ratio": "16:9",
        "resolution": "1080p",
    }

    image_ref = _image_reference(image)

    if model == SEEDANCE_2_PRO and image_ref:
        payload["image"] = image_ref
        payload["mode"] = "i2v"
    elif model == KLING_O3 and image_ref:
        payload["reference_images"] = [image_ref]
    elif model == WAN_2_7:
        pass  # text-to-video only in prototype mode

    return payload


async def generate_scene_video(
    scene: SceneManifest,
    image: SceneImage | None,
    output_dir: Path,
    credit_tracker: CreditTracker,
    render_mode: str,
) -> Path | None:
    """Generate video for one scene. Returns None on failure."""
    model = route_video_model(scene, render_mode)
    dest_path = output_dir / f"scene_{scene.scene_id}_video.mp4"

    try:
        payload = _build_video_payload(scene, model, image)
        response = await api_request("POST", "/videos/generations", json_body=payload)
        response = await wait_for_async_response(response)

        credit_tracker.log_video(model, scene.duration_sec)
        remote_url = extract_media_url(response)
        await download_binary(remote_url, str(dest_path))
        logger.info(
            "Generated video for scene %d with %s -> %s",
            scene.scene_id,
            model,
            dest_path,
        )
        return dest_path
    except Exception as exc:
        logger.error(
            "Video gen failed for scene %d (model=%s): %s",
            scene.scene_id,
            model,
            exc,
        )
        return None


async def generate_all_videos(
    scenes: list[SceneManifest],
    image_assets: dict[int, SceneImage],
    output_dir: Path,
    credit_tracker: CreditTracker,
    render_mode: str,
) -> dict[int, Path | None]:
    """Generate videos for all scenes in parallel after critique pass."""
    tasks = [
        generate_scene_video(
            scene,
            image_assets.get(scene.scene_id),
            output_dir,
            credit_tracker,
            render_mode,
        )
        for scene in scenes
    ]
    results = await asyncio.gather(*tasks)

    video_paths: dict[int, Path | None] = {}
    for scene, result in zip(scenes, results):
        video_paths[scene.scene_id] = result

    return video_paths
