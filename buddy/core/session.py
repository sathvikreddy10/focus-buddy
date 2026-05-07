"""Session state management."""

import asyncio
import json
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

from .. import config


class SessionState:
    """Holds all runtime state for a focus session."""

    def __init__(self):
        self.goal: str = ""
        self.running: bool = False
        self.observations: deque = deque(maxlen=24)
        self.off_track_streak: int = 0
        self.clients: list = []
        self.lock = asyncio.Lock()
        self.eval_lock = asyncio.Lock()
        self.capture_task: Optional[asyncio.Task] = None
        self.evaluations: list = []
        self.session_start: Optional[datetime] = None
        self.log_file: Optional[Path] = None
        self.provider = None
        self.capture_interval: int = 15
        self.eval_interval: int = 4
        self.voice_enabled: bool = False
        self._last_spoken: str = ""

    async def broadcast(self, msg: dict):
        """Send message to all connected WebSocket clients."""
        dead = []
        for client in self.clients:
            try:
                await client.send_json(msg)
            except Exception:
                dead.append(client)
        for d in dead:
            if d in self.clients:
                self.clients.remove(d)

    def write_log(self, entry: dict):
        """Append entry to session log file."""
        if self.log_file:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")

    def summary(self) -> dict:
        """Compute session summary."""
        if not self.evaluations:
            return {"focus_score": 10, "on_track_pct": 100.0, "total_evals": 0, "duration_min": 0.0}
        on_count = sum(1 for e in self.evaluations if e.get("on_track"))
        total = len(self.evaluations)
        pct = (on_count / total) * 100 if total else 100.0
        score = round(pct / 10)
        duration = 0.0
        if self.session_start:
            duration = round((datetime.now() - self.session_start).total_seconds() / 60, 1)
        return {
            "focus_score": score,
            "on_track_pct": round(pct, 1),
            "total_evals": total,
            "duration_min": duration
        }

    def reset(self):
        """Reset all session state."""
        self.goal = ""
        self.running = False
        self.observations.clear()
        self.off_track_streak = 0
        self.evaluations.clear()
        self.session_start = None
        self.log_file = None
        if self.capture_task:
            self.capture_task.cancel()
            self.capture_task = None


# Global session instance
session = SessionState()
