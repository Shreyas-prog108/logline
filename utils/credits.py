from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Estimated costs (USD) — update if pricing changes
COST_PER_UNIT: dict[str, float] = {
    "wan-2-7": 0.07,
    "kling-o3": 0.90,
    "seedance-2-0-pro": 0.70,
    "seedream-5-0-lite": 0.04,
    "gemini-2-5-flash-tts": 0.001,
    "glm-4-6v-flash": 0.003,
    "qwen3-max-thinking": 0.004,
}


class CreditTracker:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.entries: list[dict[str, Any]] = []

    def log_call(
        self,
        model_id: str,
        call_type: str,
        cost_usd: float,
        *,
        units: float | None = None,
    ) -> None:
        entry = {
            "model_id": model_id,
            "call_type": call_type,
            "cost_usd": round(cost_usd, 6),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if units is not None:
            entry["units"] = units
        self.entries.append(entry)
        self._persist()

    def estimate_cost(
        self,
        model_id: str,
        call_type: str,
        units: float,
    ) -> float:
        rate = COST_PER_UNIT.get(model_id, 0.0)
        if call_type in {"video", "video_generation"}:
            return rate * units
        if call_type in {"image", "image_generation"}:
            return rate * units
        if call_type in {"tts", "speech"}:
            return rate * units
        if call_type in {"chat", "vision", "director"}:
            return rate * (units / 1000.0)
        return rate * units

    def log_chat(self, model_id: str, call_type: str, token_estimate: float) -> None:
        cost = self.estimate_cost(model_id, call_type, token_estimate)
        self.log_call(model_id, call_type, cost, units=token_estimate)

    def log_image(self, model_id: str) -> None:
        cost = self.estimate_cost(model_id, "image", 1)
        self.log_call(model_id, "image_generation", cost, units=1)

    def log_video(self, model_id: str, duration_sec: float) -> None:
        cost = self.estimate_cost(model_id, "video", duration_sec)
        self.log_call(model_id, "video_generation", cost, units=duration_sec)

    def log_tts(self, model_id: str, char_count: int) -> None:
        cost = self.estimate_cost(model_id, "tts", char_count)
        self.log_call(model_id, "speech", cost, units=char_count)

    def _persist(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text(json.dumps(self.entries, indent=2))

    def print_summary(self) -> None:
        aggregated: dict[str, dict[str, float | int]] = {}
        for entry in self.entries:
            model_id = entry["model_id"]
            if model_id not in aggregated:
                aggregated[model_id] = {"calls": 0, "cost_usd": 0.0}
            aggregated[model_id]["calls"] += 1
            aggregated[model_id]["cost_usd"] += entry["cost_usd"]

        print("\n--- Credit Summary ---")
        print(f"{'Model':<22} | {'Calls':>5} | {'Est. Cost':>10}")
        print("-" * 44)
        total_cost = 0.0
        for model_id in sorted(aggregated):
            stats = aggregated[model_id]
            cost = stats["cost_usd"]
            total_cost += cost
            print(f"{model_id:<22} | {stats['calls']:>5} | ${cost:>9.4f}")
        print("-" * 44)
        print(f"{'TOTAL':<22} | {'':>5} | ${total_cost:>9.4f}")
        print()
