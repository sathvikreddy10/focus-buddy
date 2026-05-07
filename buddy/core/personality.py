"""Jarvis personality engine - reads session history, builds user profile."""

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .. import config


class UserProfile:
    """Jarvis's memory of the user."""

    def __init__(self):
        self.name = "dude"
        self.session_count = 0
        self.common_distractions: list[str] = []
        self.best_focus_hours: list[str] = []
        self.worst_focus_hours: list[str] = []
        self.avg_focus_score = 5.0
        self.avg_session_min = 30.0
        self.most_common_goal = ""
        self.distraction_pattern = ""
        self.effective_tone = "friendly"  # friendly -> savage
        self.roast_hits: list[str] = []
        self.last_sessions: list[dict] = []
        self.total_observations = 0
        self.total_evaluations = 0

    def to_prompt_context(self) -> str:
        """Format profile for injection into LLM prompt."""
        lines = [
            f"Profile: {self.session_count} sessions, avg score {self.avg_focus_score:.1f}/10, avg length {self.avg_session_min:.0f}min.",
            f"Distractions: {', '.join(self.common_distractions[:3]) if self.common_distractions else 'various'}.",
            f"Pattern: {self.distraction_pattern if self.distraction_pattern else 'still learning'}.",
            f"Tone that works: {self.effective_tone}.",
        ]
        return " ".join(lines)


def _extract_distractions(observations: list[dict]) -> list[str]:
    """Extract likely distractions from observation descriptions."""
    distraction_keywords = [
        "twitter", "youtube", "discord", "reddit", "instagram", "tiktok",
        "facebook", "netflix", "game", "gaming", "minecraft", "steam",
        "chat", "messaging", "slack", "whatsapp", "telegram",
        "browser", "browsing", "scrolling", "feed", "news",
        "music", "spotify", "video", "stream"
    ]
    distractions = []
    for obs in observations:
        desc = obs.get("description", "").lower()
        for keyword in distraction_keywords:
            if keyword in desc:
                distractions.append(keyword)
    return distractions


def _analyze_hours(evaluations: list[dict]) -> tuple[list[str], list[str]]:
    """Find best and worst focus hours."""
    hour_scores = {h: [] for h in range(24)}
    for ev in evaluations:
        ts = ev.get("timestamp", "")
        try:
            dt = datetime.fromisoformat(ts)
            hour = dt.hour
            score = 10 if ev.get("on_track") else 0
            hour_scores[hour].append(score)
        except Exception:
            continue

    avg_by_hour = {h: (sum(scores) / len(scores)) if scores else 5 for h, scores in hour_scores.items()}
    best = [f"{h:02d}:00" for h, score in sorted(avg_by_hour.items(), key=lambda x: x[1], reverse=True)[:3] if score > 6]
    worst = [f"{h:02d}:00" for h, score in sorted(avg_by_hour.items(), key=lambda x: x[1])[:3] if score < 4]
    return best, worst


def build_profile() -> UserProfile:
    """Read last 15 session logs and build user profile."""
    profile = UserProfile()
    log_dir = config.get_logs_dir()
    if not log_dir.exists():
        return profile

    log_files = sorted(log_dir.glob("*.jsonl"), reverse=True)[:15]
    if not log_files:
        return profile

    all_evaluations = []
    all_observations = []
    goals = Counter()
    session_durations = []
    focus_scores = []
    off_track_reasons = []

    for log_file in log_files:
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                events = [json.loads(line) for line in f if line.strip()]
        except Exception:
            continue

        profile.session_count += 1
        session_obs = []
        session_evals = []
        session_goal = ""

        for event in events:
            etype = event.get("event")
            if etype == "start":
                session_goal = event.get("goal", "")
                if session_goal:
                    goals[session_goal] += 1
            elif etype == "observation":
                session_obs.append(event)
                all_observations.append(event)
            elif etype == "evaluation":
                session_evals.append(event)
                all_evaluations.append(event)
                if not event.get("on_track"):
                    reason = event.get("reason", "")
                    if reason:
                        off_track_reasons.append(reason)
            elif etype in ("stop", "disconnect_stop"):
                summary = event.get("summary", {})
                if summary.get("duration_min"):
                    session_durations.append(summary["duration_min"])
                if summary.get("focus_score") is not None:
                    focus_scores.append(summary["focus_score"])

        profile.total_observations += len(session_obs)
        profile.total_evaluations += len(session_evals)

    # Compute aggregates
    if focus_scores:
        profile.avg_focus_score = sum(focus_scores) / len(focus_scores)
    if session_durations:
        profile.avg_session_min = sum(session_durations) / len(session_durations)
    if goals:
        profile.most_common_goal = goals.most_common(1)[0][0]

    # Distractions
    distractions = _extract_distractions(all_observations)
    if distractions:
        profile.common_distractions = [item for item, _ in Counter(distractions).most_common(5)]

    # Focus hours
    profile.best_focus_hours, profile.worst_focus_hours = _analyze_hours(all_evaluations)

    # Distraction pattern
    if all_evaluations:
        off_track_count = sum(1 for e in all_evaluations if not e.get("on_track"))
        pct = (off_track_count / len(all_evaluations)) * 100
        if pct < 20:
            profile.distraction_pattern = f"rarely drifts ({pct:.0f}% of evals)"
        elif pct < 50:
            profile.distraction_pattern = f"occasionally drifts ({pct:.0f}% of evals)"
        else:
            profile.distraction_pattern = f"often drifts ({pct:.0f}% of evals)"

    # Effective tone - if they have many sessions and still drift, get savage
    if profile.session_count >= 5 and profile.avg_focus_score < 6:
        profile.effective_tone = "savage"
    elif profile.session_count >= 3 and profile.avg_focus_score < 7:
        profile.effective_tone = "firm"
    else:
        profile.effective_tone = "friendly"

    # Roast hits - common off-track reasons
    if off_track_reasons:
        profile.roast_hits = [r[:80] for r, _ in Counter(off_track_reasons).most_common(3)]

    # Store last sessions for detailed context
    profile.last_sessions = []
    for log_file in log_files[:5]:
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                events = [json.loads(line) for line in f if line.strip()]
                if events:
                    profile.last_sessions.append(events)
        except Exception:
            continue

    return profile
