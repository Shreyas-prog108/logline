CHARS_PER_SECOND = 14.5

# Per-scene narration bounds (character length drives duration at CHARS_PER_SECOND).
MIN_SCENE_CHARS = 55   # ~3.8s per scene
MAX_SCENE_CHARS = 90   # ~6.2s per scene; 3 scenes ≈ 11.4–18.6s total


def estimate_duration_sec(narration_text: str) -> float:
    """Estimate spoken duration from narration character length."""
    return round(len(narration_text) / CHARS_PER_SECOND, 1)


def compute_scene_durations(scenes: list[dict]) -> list[dict]:
    """Recompute duration_sec for each scene dict in place."""
    for scene in scenes:
        scene["duration_sec"] = estimate_duration_sec(scene["narration_text"])
    return scenes
