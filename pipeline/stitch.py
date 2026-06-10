from __future__ import annotations

import logging
from pathlib import Path

import ffmpeg

logger = logging.getLogger(__name__)

CROSSFADE_SEC = 0.3
OUTPUT_WIDTH = 1920
OUTPUT_HEIGHT = 1080
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"
PIX_FMT = "yuv420p"


def _probe_duration(file_path: Path) -> float:
    probe = ffmpeg.probe(str(file_path))
    return float(probe.get("format", {}).get("duration", 0))


def _scale_video_stream(stream: ffmpeg.nodes.FilterableStream) -> ffmpeg.nodes.FilterableStream:
    """Normalize video to 1080p with letterboxing."""
    return (
        stream.filter("scale", OUTPUT_WIDTH, OUTPUT_HEIGHT, force_original_aspect_ratio="decrease")
        .filter("pad", OUTPUT_WIDTH, OUTPUT_HEIGHT, "(ow-iw)/2", "(oh-ih)/2")
        .filter("fps", fps=30)
    )


def _merge_scene_video_audio(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    """Merge a scene's video and audio into a single clip."""
    video_input = ffmpeg.input(str(video_path))
    audio_input = ffmpeg.input(str(audio_path))
    scaled_video = _scale_video_stream(video_input.video)

    output = ffmpeg.output(
        scaled_video,
        audio_input.audio,
        str(output_path),
        vcodec=VIDEO_CODEC,
        acodec=AUDIO_CODEC,
        pix_fmt=PIX_FMT,
        shortest=1,
        **{"b:a": "192k"},
    )
    ffmpeg.run(output, overwrite_output=True, quiet=True)
    logger.info("Merged scene clip -> %s", output_path)
    return output_path


def _concat_with_crossfade(merged_paths: list[Path], output_path: Path) -> Path:
    """Concatenate merged clips with crossfade transitions."""
    if len(merged_paths) == 1:
        inp = ffmpeg.input(str(merged_paths[0]))
        (
            ffmpeg.output(
                _scale_video_stream(inp.video),
                inp.audio,
                str(output_path),
                vcodec=VIDEO_CODEC,
                acodec=AUDIO_CODEC,
                pix_fmt=PIX_FMT,
                shortest=1,
            )
            .overwrite_output()
            .run(quiet=True)
        )
        return output_path

    inputs = [ffmpeg.input(str(path)) for path in merged_paths]
    video_streams = [_scale_video_stream(inp.video) for inp in inputs]
    audio_streams = [inp.audio for inp in inputs]

    durations = [_probe_duration(path) for path in merged_paths]

    current_v = video_streams[0]
    current_a = audio_streams[0]
    offset = max(0.0, durations[0] - CROSSFADE_SEC)

    for index in range(1, len(merged_paths)):
        next_v = video_streams[index]
        next_a = audio_streams[index]
        fade_duration = min(CROSSFADE_SEC, durations[index - 1], durations[index])
        current_v = ffmpeg.filter(
            [current_v, next_v],
            "xfade",
            transition="fade",
            duration=fade_duration,
            offset=offset,
        )
        current_a = ffmpeg.filter(
            [current_a, next_a],
            "acrossfade",
            d=fade_duration,
        )
        offset += max(0.0, durations[index] - fade_duration)

    (
        ffmpeg.output(
            current_v,
            current_a,
            str(output_path),
            vcodec=VIDEO_CODEC,
            acodec=AUDIO_CODEC,
            pix_fmt=PIX_FMT,
        )
        .overwrite_output()
        .run(quiet=True)
    )

    logger.info("Stitched final pitch -> %s", output_path)
    return output_path


def stitch_pitch(
    scene_pairs: list[tuple[int, Path, Path]],
    output_dir: Path,
) -> Path | None:
    """
    Merge video+audio per scene, then concatenate into final_pitch.mp4.

    scene_pairs: list of (scene_id, video_path, audio_path) in order.
    Skips scenes where video or audio is missing.
    """
    merged_paths: list[Path] = []

    for scene_id, video_path, audio_path in scene_pairs:
        if not video_path.exists():
            logger.warning("Skipping scene %d — video missing", scene_id)
            continue
        if not audio_path.exists():
            logger.warning("Skipping scene %d — audio missing", scene_id)
            continue

        merged_path = output_dir / f"scene_{scene_id}_merged.mp4"
        try:
            _merge_scene_video_audio(video_path, audio_path, merged_path)
            merged_paths.append(merged_path)
        except Exception as exc:
            logger.error("Failed to merge scene %d: %s", scene_id, exc)

    if not merged_paths:
        logger.error("No scenes available to stitch")
        return None

    final_path = output_dir / "final_pitch.mp4"
    return _concat_with_crossfade(merged_paths, final_path)
