"""FastAPI web server with WebSocket support."""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

from .. import config
from ..core.session import session
from ..core.evaluator import capture_loop
from ..providers import registry
from ..api.routes import router as api_router

app = FastAPI(title="Focus Buddy")
app.include_router(api_router)
frontend_dir = Path(__file__).parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main frontend page."""
    frontend_path = Path(__file__).parent / "frontend" / "index.html"
    if frontend_path.exists():
        with open(frontend_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Focus Buddy</h1><p>Frontend not found.</p>"


@app.get("/api/config")
async def get_config():
    """Return current provider config (without API key)."""
    cfg = config.load_config()
    providers = {}
    for name, pcfg in cfg.get("providers", {}).items():
        safe = pcfg.copy()
        safe["api_key"] = safe.get("api_key", "")[:8] + "****"
        providers[name] = safe
    return {
        "default_provider": cfg.get("default_provider"),
        "capture_interval": cfg.get("capture_interval", 15),
        "providers": providers
    }


@app.get("/api/session")
async def get_session():
    """Return current session state."""
    return {
        "running": session.running,
        "goal": session.goal,
        "observations": len(session.observations),
        "evaluations": len(session.evaluations),
        "off_track_streak": session.off_track_streak,
        "provider": session.provider.get_name() if session.provider else None
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session.clients.append(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")

            if action == "start":
                goal = data.get("goal", "").strip()
                if not goal:
                    await websocket.send_json({"type": "error", "message": "No goal provided"})
                    continue

                provider_name = data.get("provider") or config.get("default_provider")
                try:
                    provider_cfg = config.get_provider_config(provider_name)
                except ValueError as e:
                    await websocket.send_json({"type": "error", "message": str(e)})
                    continue

                provider = registry.create_provider(provider_cfg)

                async with session.lock:
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
                session.capture_task = asyncio.create_task(capture_loop())
                await websocket.send_json({"type": "status", "message": "Capture started"})

            elif action == "stop":
                async with session.lock:
                    session.running = False
                    if session.capture_task:
                        session.capture_task.cancel()
                        session.capture_task = None

                summary = session.summary()
                session.write_log({"event": "stop", "timestamp": datetime.now().isoformat(), "summary": summary})
                await websocket.send_json({"type": "summary", "summary": summary})
                await websocket.send_json({"type": "status", "message": "Session stopped"})
                break

    except WebSocketDisconnect:
        pass
    finally:
        if websocket in session.clients:
            session.clients.remove(websocket)
        async with session.lock:
            session.running = False
            if session.capture_task:
                session.capture_task.cancel()
                session.capture_task = None
        if session.evaluations:
            summary = session.summary()
            session.write_log({"event": "disconnect_stop", "timestamp": datetime.now().isoformat(), "summary": summary})


def run_server(host: str = "0.0.0.0", port: int = 8765):
    import uvicorn
    uvicorn.run(app, host=host, port=port)
