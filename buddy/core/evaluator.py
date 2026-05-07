"""Focus evaluation orchestrator."""

import asyncio
from datetime import datetime

from .session import session


async def evaluate_and_notify():
    """Evaluate recent observations and send notifications if off-track."""
    if session.eval_lock.locked() or not session.running:
        return

    async with session.eval_lock:
        recent = list(session.observations)[-min(8, len(session.observations)):]
        if not recent:
            return

        await session.broadcast({"type": "status", "message": "Evaluating focus..."})

        result = await session.provider.evaluate_focus(session.goal, recent)

        on_track = result.get("on_track", True)
        confidence = result.get("confidence", 0.5)
        reason = result.get("reason", "")

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
            "off_track_streak": session.off_track_streak
        }
        session.evaluations.append(eval_record)
        session.write_log(eval_record)

        # Determine severity
        severity = "none"
        title = ""
        body = ""

        if session.off_track_streak >= 3:
            severity = "aggressive"
            titles = [
                "STOP BULLSHITTING",
                "GET BACK TO WORK",
                "FOCUS! You're drifting hard",
                "Accountability check: FAILED"
            ]
            bodies = [
                f"You've been distracted for {session.off_track_streak * session.capture_interval}s! Goal: {session.goal}",
                f"Still not working on: {session.goal}. Reason: {reason}",
                f"Your goal was '{session.goal}' — what are you actually doing?"
            ]
            title = titles[session.off_track_streak % len(titles)]
            body = bodies[session.off_track_streak % len(bodies)]
        elif session.off_track_streak == 2:
            severity = "moderate"
            title = "Still Off-Track"
            body = f"You're still not working on: {session.goal}. {reason}"
        elif session.off_track_streak == 1:
            severity = "gentle"
            title = "Focus Check"
            body = f"You seem off-track. Remember: {session.goal}"

        await session.broadcast({
            "type": "evaluation",
            "on_track": on_track,
            "confidence": confidence,
            "reason": reason,
            "off_track_streak": session.off_track_streak,
            "severity": severity,
            "notification_title": title,
            "notification_body": body,
        })

        if severity != "none":
            await session.broadcast({
                "type": "notify",
                "title": title,
                "body": body,
                "severity": severity
            })


async def capture_loop():
    """Background loop: capture screen every N seconds."""
    from .capture import capture_screenshot

    loop = asyncio.get_running_loop()
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

        await session.broadcast({"type": "status", "message": "Analyzing screen..."})

        try:
            description = await session.provider.describe_screen(img_b64)
        except Exception as e:
            description = f"[Error: {e}]"

        obs = {"timestamp": ts, "description": description}
        session.observations.append(obs)
        session.write_log({"event": "observation", "timestamp": ts, "description": description})

        await session.broadcast({
            "type": "observation",
            "timestamp": ts,
            "description": description
        })

        # Trigger evaluation
        eval_interval = session.eval_interval if session.off_track_streak < 2 else 2
        if len(session.observations) % eval_interval == 0 and len(session.observations) >= eval_interval:
            asyncio.create_task(evaluate_and_notify())
