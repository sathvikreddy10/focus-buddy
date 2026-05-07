"""Focus evaluation orchestrator with Jarvis personality."""

import asyncio
import json
import re
from datetime import datetime

from .session import session
from .personality import build_profile
from .prompts import build_evaluation_prompt, build_proactive_prompt
from .voice import get_voice


# Track last proactive message time
_last_proactive_time = 0.0
_proactive_interval = 180  # 3 minutes between proactive messages


async def evaluate_and_notify():
    """Evaluate recent observations with Jarvis personality."""
    if session.eval_lock.locked() or not session.running:
        return

    async with session.eval_lock:
        recent = list(session.observations)[-min(8, len(session.observations)):]
        if not recent:
            return

        await session.broadcast({"type": "status", "message": "Jarvis is thinking..."})

        # Build user profile from history
        profile = build_profile()

        # Calculate session duration
        session_min = 0.0
        if session.session_start:
            session_min = (datetime.now() - session.session_start).total_seconds() / 60

        # Build Jarvis prompt
        prompt = build_evaluation_prompt(
            goal=session.goal,
            observations=recent,
            profile=profile,
            streak=session.off_track_streak,
            session_min=session_min
        )

        # Call reasoning model
        try:
            result = await _call_jarvis(prompt)
        except Exception as e:
            result = {
                "on_track": True,
                "confidence": 0.0,
                "reason": f"Error: {e}",
                "jarvis_message": "Yo dude, my brain glitched. Still here though.",
                "tone": "friendly",
                "proactive": False,
                "references_history": False
            }

        on_track = result.get("on_track", True)
        confidence = result.get("confidence", 0.5)
        reason = result.get("reason", "")
        jarvis_message = result.get("jarvis_message", "")
        tone = result.get("tone", "friendly")
        is_proactive = result.get("proactive", False)
        refs_history = result.get("references_history", False)

        # Update streak
        if not on_track and confidence > 0.5:
            session.off_track_streak += 1
        else:
            session.off_track_streak = max(0, session.off_track_streak - 1)

        eval_record = {
            "event": "evaluation",
            "timestamp": datetime.now().isoformat(),
            "on_track": on_track,
            "confidence": confidence,
            "reason": reason,
            "jarvis_message": jarvis_message,
            "tone": tone,
            "off_track_streak": session.off_track_streak,
            "proactive": is_proactive,
            "references_history": refs_history
        }
        session.evaluations.append(eval_record)
        session.write_log(eval_record)

        # Determine severity for notifications
        severity = _get_severity(session.off_track_streak, tone, is_proactive)

        # Generate voice audio if there's a message
        audio_b64 = ""
        if jarvis_message:
            try:
                voice = get_voice()
                audio_b64 = voice.synthesize_base64(jarvis_message)
            except Exception as e:
                print(f"[Voice Error] {e}")

        await session.broadcast({
            "type": "evaluation",
            "on_track": on_track,
            "confidence": confidence,
            "reason": reason,
            "jarvis_message": jarvis_message,
            "tone": tone,
            "off_track_streak": session.off_track_streak,
            "severity": severity,
            "proactive": is_proactive,
            "audio": audio_b64,
        })

        if severity != "none" or (is_proactive and jarvis_message):
            await session.broadcast({
                "type": "notify",
                "title": "Jarvis" if is_proactive else _get_title(tone),
                "body": jarvis_message,
                "severity": severity,
                "audio": audio_b64,
                "proactive": is_proactive,
            })


async def check_proactive():
    """Check if we should send a proactive encouragement message."""
    global _last_proactive_time

    if not session.running or session.off_track_streak > 0:
        return

    now = datetime.now().timestamp()
    if now - _last_proactive_time < _proactive_interval:
        return

    if len(session.observations) < 4:
        return  # Not enough data yet

    session_min = 0.0
    if session.session_start:
        session_min = (datetime.now() - session.session_start).total_seconds() / 60

    if session_min < 5:
        return  # Too early

    _last_proactive_time = now

    profile = build_profile()
    prompt = build_proactive_prompt(
        goal=session.goal,
        profile=profile,
        session_min=session_min,
        observation_count=len(session.observations)
    )

    try:
        result = await _call_jarvis(prompt)
        jarvis_message = result.get("jarvis_message", "")
        if jarvis_message:
            audio_b64 = ""
            try:
                voice = get_voice()
                audio_b64 = voice.synthesize_base64(jarvis_message)
            except Exception:
                pass

            await session.broadcast({
                "type": "notify",
                "title": "Jarvis",
                "body": jarvis_message,
                "severity": "gentle",
                "audio": audio_b64,
                "proactive": True,
            })
    except Exception:
        pass


async def _call_jarvis(prompt: str) -> dict:
    """Call reasoning model with Jarvis prompt."""
    content = await session.provider.reason_with_prompt(prompt)
    match = re.search(r'\{.*\}', content, re.DOTALL)
    if match:
        return json.loads(match.group())
    return {"on_track": True, "confidence": 0.5, "reason": "parse error",
            "jarvis_message": "My brain glitched, dude.", "tone": "friendly",
            "proactive": False, "references_history": False}


def _get_severity(streak: int, tone: str, proactive: bool) -> str:
    if proactive:
        return "gentle"
    if streak >= 3:
        return "aggressive"
    elif streak == 2:
        return "moderate"
    elif streak == 1:
        return "gentle"
    return "none"


def _get_title(tone: str) -> str:
    titles = {
        "friendly": "Jarvis says",
        "concerned": "Jarvis is worried",
        "firm": "Jarvis is serious",
        "savage": "Jarvis is pissed"
    }
    return titles.get(tone, "Jarvis")


async def capture_loop():
    """Background loop: capture screen every N seconds."""
    from .capture import capture_screenshot

    global _last_proactive_time
    _last_proactive_time = 0.0

    loop = asyncio.get_running_loop()
    observation_count = 0

    while session.running:
        await asyncio.sleep(session.capture_interval)
        if not session.running:
            break

        ts = datetime.now().isoformat()
        try:
            img_b64 = await loop.run_in_executor(None, capture_screenshot)
        except Exception as e:
            await session.broadcast({"type": "error", "message": f"Capture failed: {e}"})
            continue

        await session.broadcast({"type": "status", "message": "Jarvis is watching..."})

        try:
            description = await session.provider.describe_screen(img_b64)
        except Exception as e:
            description = f"[Error: {e}]"

        obs = {"timestamp": ts, "description": description}
        session.observations.append(obs)
        session.write_log({"event": "observation", "timestamp": ts, "description": description})
        observation_count += 1

        await session.broadcast({
            "type": "observation",
            "timestamp": ts,
            "description": description
        })

        # Trigger evaluation
        eval_interval = session.eval_interval if session.off_track_streak < 2 else 2
        if len(session.observations) % eval_interval == 0 and len(session.observations) >= eval_interval:
            asyncio.create_task(evaluate_and_notify())

        # Check for proactive message
        if observation_count % 6 == 0:  # Every ~90 seconds
            asyncio.create_task(check_proactive())
