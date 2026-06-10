from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from enum import Enum
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent.critique import critique_motion_prompt
from agent.director import generate_manifest
from agent.manifest_schema import PitchManifest, SceneManifest
from pipeline.image_gen import generate_all_images
from pipeline.stitch import stitch_pitch
from pipeline.tts_gen import generate_all_audio
from pipeline.video_gen import generate_all_videos
from utils.credits import CreditTracker
from utils.media import SceneImage

load_dotenv()
load_dotenv(".env.local", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="pitch_engine", version="1.0.0")

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./outputs"))


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class GenerateRequest(BaseModel):
    idea: str = Field(..., min_length=1)
    render_mode: str = Field(default="prototype", pattern="^(prototype|final)$")


class GenerateResponse(BaseModel):
    job_id: str
    status: str


class StatusResponse(BaseModel):
    job_id: str
    status: str
    stage: str
    error: str | None = None


jobs: dict[str, dict[str, Any]] = {}


def _job_output_dir(job_id: str) -> Path:
    path = OUTPUT_DIR / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _update_job(job_id: str, **fields: Any) -> None:
    if job_id in jobs:
        jobs[job_id].update(fields)


async def _run_critique_pass(
    scenes: list[SceneManifest],
    image_assets: dict[int, SceneImage],
    credit_tracker: CreditTracker,
) -> list[SceneManifest]:
    """Run vision critique on each scene in parallel."""

    async def _critique_one(scene: SceneManifest) -> SceneManifest:
        image = image_assets.get(scene.scene_id)
        motion_prompt = scene.motion_prompt
        if image and image.local_path.exists():
            motion_prompt = await critique_motion_prompt(
                image.local_path,
                scene.motion_prompt,
                credit_tracker,
            )
        return scene.model_copy(update={"motion_prompt": motion_prompt})

    return list(await asyncio.gather(*[_critique_one(scene) for scene in scenes]))


async def run_pipeline(job_id: str, idea: str, render_mode: str) -> None:
    """Execute the full pitch generation pipeline."""
    output_dir = _job_output_dir(job_id)
    credit_log_path = output_dir / "credit_log.json"
    credit_tracker = CreditTracker(credit_log_path)

    try:
        _update_job(job_id, status=JobStatus.RUNNING.value, stage="director")

        manifest: PitchManifest = await generate_manifest(idea, credit_tracker)
        scenes = list(manifest.scenes)

        _update_job(job_id, stage="image_generation")
        image_assets = await generate_all_images(scenes, output_dir, credit_tracker)

        _update_job(job_id, stage="vision_critique")
        scenes = await _run_critique_pass(scenes, image_assets, credit_tracker)

        _update_job(job_id, stage="video_generation")
        video_paths = await generate_all_videos(
            scenes,
            image_assets,
            output_dir,
            credit_tracker,
            render_mode,
        )

        _update_job(job_id, stage="tts_generation")
        audio_paths = await generate_all_audio(scenes, output_dir, credit_tracker)

        _update_job(job_id, stage="stitching")
        scene_pairs_with_fallback = []
        for scene in sorted(scenes, key=lambda s: s.scene_id):
            video = video_paths.get(scene.scene_id)
            audio = audio_paths.get(scene.scene_id)
            if audio is None or not audio.exists():
                continue
            if video is None or not video.exists():
                logger.warning("Scene %d video failed — excluded from stitch", scene.scene_id)
                continue
            scene_pairs_with_fallback.append((scene.scene_id, video, audio))

        final_path = stitch_pitch(scene_pairs_with_fallback, output_dir)

        credit_tracker.print_summary()

        if final_path and final_path.exists():
            _update_job(
                job_id,
                status=JobStatus.DONE.value,
                stage="complete",
                final_path=str(final_path),
            )
        else:
            _update_job(
                job_id,
                status=JobStatus.FAILED.value,
                stage="stitching",
                error="No scenes could be stitched into final video",
            )

    except Exception as exc:
        logger.exception("Pipeline failed for job %s", job_id)
        credit_tracker.print_summary()
        _update_job(
            job_id,
            status=JobStatus.FAILED.value,
            stage=jobs.get(job_id, {}).get("stage", "unknown"),
            error=str(exc),
        )


@app.post("/generate", response_model=GenerateResponse)
async def generate_pitch(
    request: GenerateRequest,
    background_tasks: BackgroundTasks,
) -> GenerateResponse:
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "job_id": job_id,
        "status": JobStatus.QUEUED.value,
        "stage": "queued",
        "idea": request.idea,
        "render_mode": request.render_mode,
        "error": None,
        "final_path": None,
    }

    background_tasks.add_task(run_pipeline, job_id, request.idea, request.render_mode)
    return GenerateResponse(job_id=job_id, status="queued")


@app.get("/status/{job_id}", response_model=StatusResponse)
async def get_status(job_id: str) -> StatusResponse:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return StatusResponse(
        job_id=job_id,
        status=job["status"],
        stage=job["stage"],
        error=job.get("error"),
    )


@app.get("/download/{job_id}")
async def download_pitch(job_id: str) -> FileResponse:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != JobStatus.DONE.value:
        raise HTTPException(status_code=409, detail=f"Job status is {job['status']}")

    final_path = Path(job.get("final_path") or _job_output_dir(job_id) / "final_pitch.mp4")
    if not final_path.exists():
        raise HTTPException(status_code=404, detail="Final video not found")

    return FileResponse(
        path=str(final_path),
        media_type="video/mp4",
        filename="final_pitch.mp4",
    )


@app.get("/credits/{job_id}")
async def get_credits(job_id: str) -> list[dict[str, Any]]:
    credit_log_path = _job_output_dir(job_id) / "credit_log.json"
    if not credit_log_path.exists():
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return []

    return json.loads(credit_log_path.read_text())


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
