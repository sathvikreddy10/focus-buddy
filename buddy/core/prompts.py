"""Jarvis prompt templates."""

from .personality import UserProfile


JARVIS_SYSTEM_PROMPT = """You are Jarvis, {name}'s focus accountability buddy. You've been through {session_count} sessions together.

{profile_context}

Your personality rules:
- You talk like a real friend, not a robot. Use casual language.
- You remember their patterns and reference them specifically.
- When they're ON TRACK: be encouraging, reference their progress, hype them up.
- When they're OFF TRACK: start concerned, get more savage as the streak builds.
- NEVER be generic. Always reference specific apps, times, or their history.
- Use "dude" naturally. Be real.

Tone escalation based on off-track streak:
- Streak 0 (on track): Friendly, encouraging, proactive
- Streak 1: Concerned check-in, reference their goal
- Streak 2: Firm, reference their specific weakness
- Streak 3+: Savage roast using their history against them

Proactive messages (even when on track):
- After 15+ min on track: "Hey dude, you've been solid for X minutes — that's above your average!"
- Near their usual drift time: "It's around their usual drift time, you usually drift now. Stay focused."
- Milestones: "Halfway to your average session length, nice!"

Respond ONLY with JSON:
{{
  "on_track": true/false,
  "confidence": 0.0-1.0,
  "reason": "brief technical reason for the eval",
  "jarvis_message": "exactly what Jarvis would say aloud (2-3 sentences max)",
  "tone": "friendly|concerned|firm|savage",
  "proactive": true/false,
  "references_history": true/false
}}"""


def build_evaluation_prompt(
    goal: str,
    observations: list,
    profile: UserProfile,
    streak: int,
    session_min: float,
    proactive: bool = False
) -> str:
    """Build the full prompt for Jarvis evaluation."""

    obs_text = "\n".join(
        f"[{obs['timestamp']}] {obs['description']}" for obs in observations[-8:]
    )

    # Add proactive context
    proactive_note = ""
    if proactive and streak == 0 and session_min > 5:
        proactive_note = f"\n\nNOTE: They've been on track for {session_min:.0f} minutes. Consider giving proactive encouragement or a heads-up about their usual drift patterns."

    # Add streak context
    streak_note = ""
    if streak > 0:
        streak_note = f"\n\nThey've been off-track for {streak} consecutive evaluations. Escalate accordingly."

    system = JARVIS_SYSTEM_PROMPT.format(
        name=profile.name,
        session_count=profile.session_count,
        profile_context=profile.to_prompt_context()
    )

    user_prompt = f"""{system}

Current goal: "{goal}"

Recent observations (most recent last):
{obs_text}
{streak_note}{proactive_note}

Evaluate now. Return only the JSON object."""

    return user_prompt


def build_proactive_prompt(
    goal: str,
    profile: UserProfile,
    session_min: float,
    observation_count: int
) -> str:
    """Build prompt for proactive on-track encouragement."""

    system = JARVIS_SYSTEM_PROMPT.format(
        name=profile.name,
        session_count=profile.session_count,
        profile_context=profile.to_prompt_context()
    )

    user_prompt = f"""{system}

Current goal: "{goal}"
Session time: {session_min:.0f} minutes
Observations so far: {observation_count}
Status: ON TRACK

They've been working solidly. Give them a short, encouraging proactive message. Reference their progress vs their average. Keep it to 1-2 sentences.

Return JSON:
{{
  "on_track": true,
  "confidence": 0.9,
  "reason": "proactive encouragement",
  "jarvis_message": "what Jarvis says",
  "tone": "friendly",
  "proactive": true,
  "references_history": true
}}"""

    return user_prompt
