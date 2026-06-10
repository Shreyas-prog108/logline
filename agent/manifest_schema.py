from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from utils.timing import MAX_SCENE_CHARS, MIN_SCENE_CHARS

PitchVibe = Literal["sleek_b2b", "scrappy_technical", "consumer_emotional"]
SceneRole = Literal["opener", "problem", "solution", "cta"]


class SceneManifest(BaseModel):
    scene_id: int = Field(..., ge=1)
    role: SceneRole
    narration_text: str
    visual_prompt: str
    motion_prompt: str
    duration_sec: float = Field(..., gt=0)
    is_hero: bool

    @field_validator("narration_text")
    @classmethod
    def validate_narration(cls, value: str) -> str:
        char_count = len(value)
        word_count = len(value.split())
        if word_count > 25:
            raise ValueError(f"narration_text exceeds 25 words ({word_count})")
        if char_count < MIN_SCENE_CHARS:
            raise ValueError(
                f"narration_text too short ({char_count} chars, need at least {MIN_SCENE_CHARS})"
            )
        if char_count > MAX_SCENE_CHARS:
            raise ValueError(
                f"narration_text too long ({char_count} chars, max {MAX_SCENE_CHARS})"
            )
        return value


class PitchManifest(BaseModel):
    pitch_title: str
    pitch_vibe: PitchVibe
    scenes: list[SceneManifest]

    @model_validator(mode="after")
    def validate_manifest(self) -> PitchManifest:
        if len(self.scenes) != 3:
            raise ValueError("manifest must contain exactly 3 scenes")

        scene_ids = sorted(scene.scene_id for scene in self.scenes)
        if scene_ids != [1, 2, 3]:
            raise ValueError("scene_id values must be 1, 2, and 3")

        total_duration = sum(scene.duration_sec for scene in self.scenes)
        if not 12.0 <= total_duration <= 18.0:
            raise ValueError(
                f"total duration must be between 12 and 18 seconds (got {total_duration})"
            )

        hero_scenes = [scene for scene in self.scenes if scene.is_hero]
        if len(hero_scenes) != 1 or hero_scenes[0].scene_id != 1:
            raise ValueError("is_hero must be true only for scene_id == 1")

        return self
