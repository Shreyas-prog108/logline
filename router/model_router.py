from __future__ import annotations

import os

from agent.manifest_schema import SceneManifest
from utils.models import KLING_O3, SEEDANCE_2_PRO, WAN_2_7

RenderMode = str  # "prototype" | "final"


def get_render_mode() -> str:
    return os.getenv("RENDER_MODE", "prototype")


def route_video_model(scene: SceneManifest, mode: str | None = None) -> str:
    """Select the video generation model for a scene."""
    render_mode = mode or get_render_mode()

    if render_mode == "prototype":
        return WAN_2_7

    if render_mode == "final":
        if scene.is_hero:
            return KLING_O3
        if scene.role in ("problem", "solution", "cta"):
            return SEEDANCE_2_PRO
        return KLING_O3

    return WAN_2_7
