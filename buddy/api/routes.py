"""REST API routes for agent integration.

External agents can interact via HTTP:
  POST /api/v1/session/start
  POST /api/v1/session/stop
  GET  /api/v1/session/status
  GET  /api/v1/providers
"""

from datetime import datetime

from fastapi import APIRouter

from .. import config
from ..core.session import session
from ..core.evaluator import capture_loop
from ..providers import registry

router = APIRouter(prefix="/api/v1")


@router.post("/session/start")
async def api_start(req: dict):
    """Start a session via API."""
    if session.running:
        return {"error": "Session already running"}

    goal = req.get("goal", "").strip()
    if not goal:
        return {"error": "No goal provided"}

    provider_name = req.get("provider") or config.get("default_provider")
    try:
        provider_cfg = config.get_provider_config(provider_name)
    except ValueError as e:
        return {"error": str(e)}

    provider = registry.create_provider(provider_cfg)
    session.provider = provider
    session.capture_interval = config.get("capture_interval", 15)
    session.eval_interval = config.get("eval_interval", 4)
    session.goal = goal
    session.running = True
    session.observations.clear()
    session.evaluations.clear()
    session.off_track_streak = 0
    session.session_start = datetime.now()

    log_dir = config.get_logs_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    session.log_file = log_dir / f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    session.write_log({"event": "start", "goal": goal, "timestamp": datetime.now().isoformat()})

    import asyncio
    session.capture_task = asyncio.create_task(capture_loop())

    return {
        "status": "started",
        "goal": goal,
        "provider": provider.get_name()
    }


@router.post("/session/stop")
async def api_stop():
    """Stop current session."""
    if not session.running:
        return {"error": "No active session"}

    session.running = False
    if session.capture_task:
        session.capture_task.cancel()
        session.capture_task = None

    summary = session.summary()
    session.write_log({"event": "stop", "timestamp": datetime.now().isoformat(), "summary": summary})
    session.reset()
    return {"status": "stopped", "summary": summary}


@router.get("/session/status")
async def api_status():
    """Get current session status."""
    return {
        "running": session.running,
        "goal": session.goal,
        "observations": len(session.observations),
        "evaluations": len(session.evaluations),
        "off_track_streak": session.off_track_streak,
        "provider": session.provider.get_name() if session.provider else None,
        "summary": session.summary() if session.running else None
    }


@router.get("/providers")
async def api_providers():
    """List configured providers."""
    providers = config.list_providers()
    default = config.get("default_provider")
    return {
        "default": default,
        "providers": {
            name: {
                "type": cfg.get("type"),
                "url": cfg.get("url"),
                "vision_model": cfg.get("vision_model"),
                "reasoning_model": cfg.get("reasoning_model")
            }
            for name, cfg in providers.items()
        }
    }
