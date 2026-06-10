from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path

import ffmpeg

from agent.manifest_schema import SceneManifest
from utils.api_client import api_request, download_binary
from utils.credits import CreditTracker
from utils.models import GEMINI_TTS

logger = logging.getLogger(__name__)

ATEMPO_MIN = 0.85
ATEMPO_MAX = 1.15
DURATION_TOLERANCE_SEC = 0.3


def _probe_audio_duration(audio_path: Path) -> float:
    probe = ffmpeg.probe(str(audio_path))
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == "audio":
            return float(stream.get("duration", 0))
    format_info = probe.get("format", {})
    return float(format_info.get("duration", 0))


async def _save_audio_from_response(response: dict, dest_path: Path) -> None:
    data = response.get("data") or []
    if data:
        item = data[0]
        if item.get("b64_json"):
            dest_path.write_bytes(base64.b64decode(item["b64_json"]))
            return
        if item.get("url"):
            await download_binary(item["url"], str(dest_path))
            return

    raise RuntimeError(f"Unrecognized TTS response: {list(response.keys())}")


def _adjust_audio_duration(
    source_path: Path,
    dest_path: Path,
    target_duration: float,
    actual_duration: float,
) -> None:
    """Stretch or compress audio with ffmpeg atempo to match target duration."""
    if actual_duration <= 0:
        logger.warning("Cannot adjust audio with zero duration")
        source_path.rename(dest_path)
        return

    tempo = actual_duration / target_duration
    if tempo < ATEMPO_MIN or tempo > ATEMPO_MAX:
        logger.warning(
            "atempo %.3f out of safe range [%.2f, %.2f] — clamping",
            tempo,
            ATEMPO_MIN,
            ATEMPO_MAX,
        )
        tempo = max(ATEMPO_MIN, min(ATEMPO_MAX, tempo))

    (
        ffmpeg.input(str(source_path))
        .filter("atempo", tempo)
        .output(str(dest_path), acodec="libmp3lame")
        .overwrite_output()
        .run(quiet=True)
    )


async def generate_scene_audio(
    scene: SceneManifest,
    output_dir: Path,
    credit_tracker: CreditTracker,
) -> Path:
    """Generate TTS audio for one scene, adjusting duration if needed."""
    dest_path = output_dir / f"scene_{scene.scene_id}_audio.mp3"
    raw_path = output_dir / f"scene_{scene.scene_id}_audio_raw.mp3"

    payload = {
        "model": GEMINI_TTS,
        "input": scene.narration_text,
        "voice": "Charon",
        "output_format": "mp3",
        "response_format": "b64_json",
    }

    response = await api_request("POST", "/audio/speech", json_body=payload)
    if not isinstance(response, dict):
        raise RuntimeError("Unexpected binary TTS response")
    await _save_audio_from_response(response, raw_path)

    credit_tracker.log_tts(GEMINI_TTS, len(scene.narration_text))

    actual_duration = _probe_audio_duration(raw_path)
    delta = abs(actual_duration - scene.duration_sec)

    if delta > DURATION_TOLERANCE_SEC:
        logger.info(
            "Adjusting scene %d audio: actual=%.2fs target=%.2fs",
            scene.scene_id,
            actual_duration,
            scene.duration_sec,
        )
        _adjust_audio_duration(raw_path, dest_path, scene.duration_sec, actual_duration)
        raw_path.unlink(missing_ok=True)
    else:
        raw_path.rename(dest_path)

    logger.info("Generated audio for scene %d -> %s", scene.scene_id, dest_path)
    return dest_path


async def generate_all_audio(
    scenes: list[SceneManifest],
    output_dir: Path,
    credit_tracker: CreditTracker,
) -> dict[int, Path]:
    """Generate TTS for all scenes in parallel."""
    tasks = [
        generate_scene_audio(scene, output_dir, credit_tracker) for scene in scenes
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    audio_paths: dict[int, Path] = {}
    for scene, result in zip(scenes, results):
        if isinstance(result, Exception):
            logger.error("TTS failed for scene %d: %s", scene.scene_id, result)
            raise result
        audio_paths[scene.scene_id] = result

    return audio_paths
