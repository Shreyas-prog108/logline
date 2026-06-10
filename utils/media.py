from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SceneImage:
    local_path: Path
    remote_url: str


def local_image_to_data_uri(image_path: Path) -> str:
    """Encode a local image as a data URI for API calls that accept inline images."""
    mime_type, _ = mimetypes.guess_type(str(image_path))
    mime_type = mime_type or "image/png"
    encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"
