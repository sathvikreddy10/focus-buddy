import asyncio
import base64
import io
import json
import os
import time
from collections import deque
from datetime import datetime
from typing import Optional

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from openai import AsyncOpenAI
import mss
from PIL import Image

app = FastAPI(title="Focus Buddy")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Ensure logs directory exists
os.makedirs("logs", exist_ok=True)


def get_env(key: str, default: str) -> str:
    return os.environ.get(key, default)


class AIClient:
    """OpenAI-compatible client with configurable endpoints."""
    def __init__(
        self,
        base_url: str = None,
        api_key: str = None,
        vision_model: str = None,
        reasoning_model: str = None
    ):
        self.base_url = base_url or get_env("FOCUS_API_URL", "https://integrate.api.nvidia.com/v1")
        self.api_key = api_key or get_env("FOCUS_API_KEY", "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")
        self.vision_model = vision_model or get_env("FOCUS_VISION_MODEL", "meta/llama-3.2-11b-vision-instruct")
        self.reasoning_model = reasoning_model or get_env("FOCUS_REASONING_MODEL", "qwen/qwen2.5-coder-32b-instruct")
        self.client = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key, timeout=90)

    async def describe_screen(self, image_base64: str) -> str:
        try:
            completion = await self.client.chat.completions.create(
                model=self.vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "You are a precise screen activity analyst. Describe what the user is "
                                    "currently doing on their computer screen. Be specific: identify the active "
                                    "application or website, visible content, and infer the task. Keep it concise "
                                    "but detailed enough to judge productivity."
                                )
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                            }
                        ]
                    }
                ],
                temperature=0.2,
                max_tokens=400,
            )
            return completion.choices[0].message.content.strip()
        except Exception as e:
            return f"[Vision Error: {e}]"

    async def evaluate_focus(self, goal: str, observations: list) -> dict:
        obs_text = "\n".join(
            f"[{obs['timestamp']}] {obs['description']}" for obs in observations
        )
        prompt = (
            f"The user's stated goal for this session is: \"{goal}\"\n\n"
            f"Recent screen observations (most recent last):\n{obs_text}\n\n"
            f"You are a ruthless accountability partner. Be harsh and direct. "
            f"If the user is doing ANYTHING that is not directly advancing their stated goal, "
            f"they are BULLSHITTING. Social media, news, games, idle browsing, chatting = bullshit. "
            f"Only genuine work on the stated goal counts as on-track.\n\n"
            f"Respond ONLY with a JSON object exactly like this:\n"
            f'{{"on_track": true/false, "confidence": 0.0-1.0, "reason": "brief explanation"}}'
        )
        try:
            completion = await self.client.chat.completions.create(
                model=self.reasoning_model,
                messages=[
                    {"role": "system", "content": "You are a brutally honest focus evaluator. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=400,
            )
            content = completion.choices[0].message.content.strip()
            # Extract JSON
            import re
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                result = json.loads(match.group())
            else:
                result = {"on_track": True, "confidence": 0.5, "reason": "parse error"}
            return result
        except Exception as e:
            return {"on_track": True, "confidence": 0.0, "reason": f"Error: {e}"}


ai_client = AIClient()


class SessionState:
    def __init__(self):
        self.goal: str = ""
        self.running: bool = False
        self.observations: deque = deque(maxlen=24)  # 6 minutes
        self.off_track_streak: int = 0
        self.last_eval_time: float = 0
        self.clients: list[WebSocket] = []
        self.lock = asyncio.Lock()
        self.eval_lock = asyncio.Lock()
        self.capture_task: Optional[asyncio.Task] = None
        self.evaluations: list[dict] = []
        self.session_start: Optional[datetime] = None
        self.log_file: Optional[str] = None

    async def broadcast(self, msg: dict):
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
        if self.log_file:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")


session = SessionState()


def capture_screenshot() -> str:
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        screenshot = sct.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        img.thumbnail((1024, 1024))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75)
        return base64.b64encode(buf.getvalue()).decode("utf-8")


async def capture_loop():
    loop = asyncio.get_running_loop()
    while session.running:
        await asyncio.sleep(15)
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
            description = await ai_client.describe_screen(img_b64)
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

        # Evaluate every ~60 seconds (every 4 observations) or if streak is building
        eval_interval = 4 if session.off_track_streak < 2 else 2
        if len(session.observations) % eval_interval == 0 and len(session.observations) >= eval_interval:
            asyncio.create_task(evaluate_and_notify())


async def evaluate_and_notify():
    if session.eval_lock.locked():
        return
    async with session.eval_lock:
        recent = list(session.observations)[-min(8, len(session.observations)):]
        if not recent:
            return

        await session.broadcast({"type": "status", "message": "Evaluating focus..."})

        result = await ai_client.evaluate_focus(session.goal, recent)

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

        # Notification logic with variation
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
                f"You've been distracted for {session.off_track_streak * 15}s! Goal: {session.goal}",
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


def compute_session_summary() -> dict:
    if not session.evaluations:
        return {"focus_score": 10, "on_track_pct": 100, "total_evals": 0}
    on_count = sum(1 for e in session.evaluations if e.get("on_track"))
    total = len(session.evaluations)
    pct = (on_count / total) * 100 if total else 100
    # 0-10 scale: linear mapping from 0-100%
    score = round(pct / 10)
    return {
        "focus_score": score,
        "on_track_pct": round(pct, 1),
        "total_evals": total,
        "duration_min": round((datetime.now() - session.session_start).total_seconds() / 60, 1) if session.session_start else 0
    }


@app.get("/", response_class=HTMLResponse)
async def root():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Focus Buddy</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
    color: #e0e0e0;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 2rem 1rem;
  }
  h1 { font-size: 2.8rem; margin-bottom: 0.25rem; background: linear-gradient(90deg, #00f260, #0575e6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; letter-spacing: -1px; }
  .subtitle { color: #a0a0c0; margin-bottom: 2rem; font-size: 1.05rem; }
  .card {
    background: rgba(255,255,255,0.04);
    backdrop-filter: blur(16px);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 20px;
    padding: 2rem;
    width: 100%;
    max-width: 640px;
    margin-bottom: 1.5rem;
    box-shadow: 0 8px 32px rgba(0,0,0,0.3);
    transition: transform 0.2s;
  }
  .card:hover { transform: translateY(-2px); }
  input[type="text"] {
    width: 100%;
    padding: 1rem 1.25rem;
    border-radius: 14px;
    border: 1px solid rgba(255,255,255,0.12);
    background: rgba(0,0,0,0.25);
    color: #fff;
    font-size: 1rem;
    margin-bottom: 1rem;
    outline: none;
    transition: border-color 0.2s;
  }
  input[type="text"]:focus { border-color: #00f260; }
  input::placeholder { color: #8892b0; }
  button {
    width: 100%;
    padding: 1rem;
    border: none;
    border-radius: 14px;
    font-size: 1.05rem;
    font-weight: 700;
    cursor: pointer;
    transition: all 0.25s;
    letter-spacing: 0.5px;
  }
  .btn-start { background: linear-gradient(90deg, #00f260, #0575e6); color: #0a0a0a; }
  .btn-start:hover { transform: translateY(-2px); box-shadow: 0 12px 30px rgba(0,242,96,0.25); }
  .btn-stop { background: linear-gradient(90deg, #ff416c, #ff4b2b); color: #fff; }
  .btn-stop:hover { transform: translateY(-2px); box-shadow: 0 12px 30px rgba(255,65,108,0.3); }
  .btn-secondary { background: rgba(255,255,255,0.08); color: #ccd6f6; border: 1px solid rgba(255,255,255,0.15); margin-top: 0.5rem; font-size: 0.9rem; padding: 0.75rem; }
  .btn-secondary:hover { background: rgba(255,255,255,0.15); }
  .btn-red { background: linear-gradient(90deg, #ff416c, #ff4b2b); color: #fff; margin-top: 0.5rem; font-size: 0.9rem; padding: 0.75rem; }
  #status {
    text-align: center;
    font-size: 0.95rem;
    color: #00f260;
    margin-top: 1rem;
    min-height: 1.5rem;
    font-weight: 500;
  }
  #permStatus {
    text-align: center;
    font-size: 0.8rem;
    margin-top: 0.5rem;
    padding: 0.4rem 0.8rem;
    border-radius: 8px;
    display: inline-block;
  }
  .perm-granted { background: rgba(0,242,96,0.15); color: #00f260; }
  .perm-denied { background: rgba(255,65,108,0.15); color: #ff416c; }
  .perm-default { background: rgba(255,193,7,0.15); color: #ffc107; }
  #summary {
    display: none;
    text-align: center;
    margin-top: 1rem;
    padding: 1rem;
    background: rgba(0,0,0,0.2);
    border-radius: 12px;
  }
  #summary h3 { color: #ccd6f6; margin-bottom: 0.5rem; }
  #summary .score { font-size: 2.5rem; font-weight: 800; background: linear-gradient(90deg, #00f260, #0575e6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
  #log {
    max-height: 360px;
    overflow-y: auto;
    font-family: 'SF Mono', Consolas, monospace;
    font-size: 0.82rem;
    color: #a8b2d1;
    background: rgba(0,0,0,0.25);
    border-radius: 12px;
    padding: 1rem;
    margin-top: 1rem;
    line-height: 1.5;
  }
  #log::-webkit-scrollbar { width: 6px; }
  #log::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.15); border-radius: 3px; }
  .log-entry { margin-bottom: 0.6rem; border-left: 3px solid #00f260; padding-left: 0.6rem; opacity: 0; animation: fadeIn 0.3s forwards; }
  .log-entry.off-track { border-left-color: #ff416c; }
  .log-entry.notify { border-left-color: #ffd700; background: rgba(255,215,0,0.04); }
  .log-entry.error { border-left-color: #ff416c; color: #ff6b6b; }
  @keyframes fadeIn { to { opacity: 1; } }
  .hidden { display: none !important; }
  .streak-container { text-align: center; margin-top: 0.75rem; }
  .streak-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.35rem 0.9rem;
    border-radius: 24px;
    font-size: 0.85rem;
    font-weight: 700;
    border: 1px solid transparent;
  }
  .streak-ok { background: rgba(0,242,96,0.12); color: #00f260; border-color: rgba(0,242,96,0.25); }
  .streak-warn { background: rgba(255,193,7,0.12); color: #ffc107; border-color: rgba(255,193,7,0.25); }
  .streak-danger { background: rgba(255,65,108,0.12); color: #ff416c; border-color: rgba(255,65,108,0.25); animation: pulse 1.5s infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.7; } }
  .config-row { display: flex; gap: 0.75rem; margin-bottom: 1rem; }
  .config-row input { flex: 1; margin-bottom: 0; }
  small.hint { display: block; color: #8892b0; font-size: 0.75rem; margin-top: 0.25rem; }
  /* Flash overlay for aggressive mode */
  #flashOverlay {
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(255, 0, 0, 0.0);
    pointer-events: none;
    z-index: 9999;
    transition: background 0.1s;
  }
  #flashOverlay.active {
    background: rgba(255, 0, 0, 0.3);
    animation: flashRed 0.5s ease-in-out 3;
  }
  @keyframes flashRed {
    0%, 100% { background: rgba(255, 0, 0, 0.0); }
    50% { background: rgba(255, 0, 0, 0.4); }
  }
  /* Full-screen alert */
  #alertOverlay {
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.92);
    display: none;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    z-index: 10000;
    text-align: center;
    padding: 2rem;
  }
  #alertOverlay.show { display: flex; }
  #alertOverlay h2 {
    font-size: 3rem;
    color: #ff416c;
    margin-bottom: 1rem;
    animation: shake 0.5s infinite;
  }
  #alertOverlay p {
    font-size: 1.3rem;
    color: #e0e0e0;
    max-width: 500px;
    margin-bottom: 2rem;
  }
  #alertOverlay button {
    width: auto;
    padding: 1rem 3rem;
    font-size: 1.2rem;
    background: linear-gradient(90deg, #00f260, #0575e6);
    color: #0a0a0a;
    border-radius: 50px;
  }
  @keyframes shake {
    0%, 100% { transform: translateX(0); }
    25% { transform: translateX(-10px); }
    75% { transform: translateX(10px); }
  }
</style>
</head>
<body>
  <div id="flashOverlay"></div>
  <div id="alertOverlay">
    <h2 id="alertTitle">STOP BULLSHITTING</h2>
    <p id="alertBody">Get back to work!</p>
    <button onclick="dismissAlert()">I'M SORRY, BACK TO WORK</button>
  </div>

  <h1>Focus Buddy</h1>
  <p class="subtitle">AI-powered accountability partner. Don't bullshit.</p>

  <div class="card">
    <div class="config-row">
      <input type="text" id="goalInput" placeholder="Session goal (e.g., 'Finish report')" />
    </div>
    <button id="startBtn" class="btn-start">Start Session</button>
    <button id="stopBtn" class="btn-start hidden" style="background:linear-gradient(90deg,#ff416c,#ff4b2b);color:#fff;">Stop Session</button>
    <div id="status"></div>
    <div style="text-align:center;">
      <div id="permStatus" class="perm-default">🔔 Notifications: Checking...</div>
    </div>
    <div class="streak-container hidden" id="streakWrap">
      <span id="streakBadge" class="streak-badge streak-ok">On Track</span>
    </div>
    <div id="summary"></div>
    <button id="testNotifyBtn" class="btn-secondary" onclick="testNotification()">Test Notification</button>
  </div>

  <div class="card">
    <h3 style="margin-bottom:0.75rem;color:#ccd6f6;font-size:1.1rem;">Live Activity Log</h3>
    <div id="log"></div>
  </div>

<script>
  const goalInput = document.getElementById('goalInput');
  const startBtn = document.getElementById('startBtn');
  const stopBtn = document.getElementById('stopBtn');
  const statusEl = document.getElementById('status');
  const logEl = document.getElementById('log');
  const streakWrap = document.getElementById('streakWrap');
  const streakBadge = document.getElementById('streakBadge');
  const summaryEl = document.getElementById('summary');
  const permStatus = document.getElementById('permStatus');
  const flashOverlay = document.getElementById('flashOverlay');
  const alertOverlay = document.getElementById('alertOverlay');
  const alertTitle = document.getElementById('alertTitle');
  const alertBody = document.getElementById('alertBody');
  let ws = null;
  let audioCtx = null;

  // Audio beep generator
  function playBeep(freq=800, duration=0.3, type='square') {
    try {
      if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = type;
      osc.frequency.value = freq;
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start();
      gain.gain.exponentialRampToValueAtTime(0.00001, audioCtx.currentTime + duration);
      osc.stop(audioCtx.currentTime + duration);
    } catch(e) {}
  }

  function playAlertSound(severity) {
    if (severity === 'aggressive') {
      playBeep(400, 0.4, 'sawtooth');
      setTimeout(() => playBeep(600, 0.4, 'sawtooth'), 200);
      setTimeout(() => playBeep(800, 0.6, 'square'), 400);
    } else if (severity === 'moderate') {
      playBeep(500, 0.3, 'square');
      setTimeout(() => playBeep(700, 0.3, 'square'), 150);
    } else {
      playBeep(600, 0.2, 'sine');
    }
  }

  // Notification permission handling
  function updatePermStatus() {
    if (!('Notification' in window)) {
      permStatus.textContent = '🔕 Notifications not supported';
      permStatus.className = 'perm-denied';
      return;
    }
    if (Notification.permission === 'granted') {
      permStatus.textContent = '🔔 Notifications enabled';
      permStatus.className = 'perm-granted';
    } else if (Notification.permission === 'denied') {
      permStatus.textContent = '🔕 Notifications BLOCKED — click to fix';
      permStatus.className = 'perm-denied';
      permStatus.style.cursor = 'pointer';
      permStatus.onclick = () => {
        alert('Unblock notifications in your browser address bar (click the lock icon), then refresh');
      };
    } else {
      permStatus.textContent = '🔔 Click to enable notifications';
      permStatus.className = 'perm-default';
      permStatus.style.cursor = 'pointer';
      permStatus.onclick = requestNotificationPermission;
    }
  }

  async function requestNotificationPermission() {
    if (!('Notification' in window)) return;
    const result = await Notification.requestPermission();
    updatePermStatus();
    if (result === 'granted') {
      new Notification('Focus Buddy', { body: 'Notifications are now active. Prepare to be held accountable.' });
    }
  }

  function testNotification() {
    if (!('Notification' in window)) { alert('Notifications not supported'); return; }
    if (Notification.permission !== 'granted') {
      requestNotificationPermission();
      return;
    }
    playAlertSound('aggressive');
    flashOverlay.classList.add('active');
    setTimeout(() => flashOverlay.classList.remove('active'), 2000);
    new Notification('🔥 TEST ALERT', { body: 'If you see this, notifications are working. Now get back to work.', requireInteraction: true });
    alertTitle.textContent = '🔥 TEST ALERT';
    alertBody.textContent = 'Notifications are working. Now stop testing and start working.';
    alertOverlay.classList.add('show');
  }

  function dismissAlert() {
    alertOverlay.classList.remove('show');
  }

  updatePermStatus();

  function appendLog(msg, type='normal') {
    const div = document.createElement('div');
    div.className = 'log-entry' + (type==='off-track' ? ' off-track' : type==='notify' ? ' notify' : type==='error' ? ' error' : '');
    div.textContent = msg;
    logEl.prepend(div);
  }

  function updateStreak(streak, severity) {
    streakWrap.classList.remove('hidden');
    if (streak === 0) {
      streakBadge.textContent = '✅ On Track';
      streakBadge.className = 'streak-badge streak-ok';
    } else if (severity === 'aggressive') {
      streakBadge.textContent = '🔥 OFF-TRACK x' + streak;
      streakBadge.className = 'streak-badge streak-danger';
    } else if (severity === 'moderate') {
      streakBadge.textContent = '⚠️ Off-track x' + streak;
      streakBadge.className = 'streak-badge streak-warn';
    } else {
      streakBadge.textContent = '👀 Off-track x' + streak;
      streakBadge.className = 'streak-badge streak-warn';
    }
  }

  function sendNotify(title, body, severity) {
    // Always play sound and flash screen
    playAlertSound(severity);
    flashOverlay.classList.add('active');
    setTimeout(() => flashOverlay.classList.remove('active'), severity === 'aggressive' ? 3000 : 1500);

    // Vibrate on mobile
    if (navigator.vibrate) {
      navigator.vibrate(severity === 'aggressive' ? [300, 100, 300, 100, 500] : [200, 100, 200]);
    }

    // Browser notification
    if ('Notification' in window && Notification.permission === 'granted') {
      const n = new Notification(title, {
        body,
        tag: 'focus-buddy-' + Date.now(),
        requireInteraction: severity === 'aggressive',
        silent: true  // We handle sound ourselves
      });
      if (severity === 'aggressive') {
        setTimeout(() => {
          new Notification(title, {
            body,
            tag: 'focus-buddy-aggr2',
            requireInteraction: true,
            silent: true
          });
          playAlertSound('aggressive');
        }, 3000);
      }
    }

    // Full-screen overlay for aggressive
    if (severity === 'aggressive') {
      alertTitle.textContent = title;
      alertBody.textContent = body;
      alertOverlay.classList.add('show');
    }
  }

  startBtn.onclick = () => {
    const goal = goalInput.value.trim();
    if (!goal) { alert('Enter a goal first!'); return; }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
    ws.onopen = () => {
      ws.send(JSON.stringify({ action: 'start', goal }));
      startBtn.classList.add('hidden');
      stopBtn.classList.remove('hidden');
      summaryEl.style.display = 'none';
      statusEl.textContent = 'Session active • Capturing every 15s';
      logEl.innerHTML = '';
      appendLog('🚀 Session started. Goal: ' + goal);
      playBeep(800, 0.1, 'sine');
    };
    ws.onmessage = (ev) => {
      const data = JSON.parse(ev.data);
      if (data.type === 'status') {
        statusEl.textContent = data.message;
      } else if (data.type === 'observation') {
        const t = data.timestamp.split('T')[1].split('.')[0];
        appendLog(`[${t}] ${data.description}`);
      } else if (data.type === 'evaluation') {
        const status = data.on_track ? 'ON TRACK' : 'OFF TRACK';
        appendLog(`[EVAL] ${status} • conf ${(data.confidence*100).toFixed(0)}% • ${data.reason}`, data.on_track ? 'normal' : 'off-track');
        updateStreak(data.off_track_streak, data.severity);
      } else if (data.type === 'notify') {
        appendLog(`[ALERT] ${data.title}: ${data.body}`, 'notify');
        sendNotify(data.title, data.body, data.severity);
      } else if (data.type === 'summary') {
        summaryEl.style.display = 'block';
        summaryEl.innerHTML = `
          <h3>Session Summary</h3>
          <div class="score">${data.summary.focus_score}/10</div>
          <p style="color:#a0a0c0;margin-top:0.5rem;">
            On-track ${data.summary.on_track_pct}% • ${data.summary.total_evals} checks • ${data.summary.duration_min} min
          </p>
        `;
      } else if (data.type === 'error') {
        appendLog('[ERR] ' + data.message, 'error');
      }
    };
    ws.onclose = () => {
      statusEl.textContent = 'Session ended';
      startBtn.classList.remove('hidden');
      stopBtn.classList.add('hidden');
      streakWrap.classList.add('hidden');
    };
  };

  stopBtn.onclick = () => {
    if (ws) {
      ws.send(JSON.stringify({ action: 'stop' }));
      ws.close();
    }
  };
</script>
</body>
</html>
    """


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

                async with session.lock:
                    session.goal = goal
                    session.running = True
                    session.observations.clear()
                    session.evaluations.clear()
                    session.off_track_streak = 0
                    session.last_eval_time = time.time()
                    session.session_start = datetime.now()
                    session.log_file = f"logs/session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"

                session.write_log({"event": "start", "goal": goal, "timestamp": datetime.now().isoformat()})
                session.capture_task = asyncio.create_task(capture_loop())
                await websocket.send_json({"type": "status", "message": "Capture started"})

            elif action == "stop":
                async with session.lock:
                    session.running = False
                    if session.capture_task:
                        session.capture_task.cancel()
                        session.capture_task = None

                summary = compute_session_summary()
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
        # Ensure summary is sent if not already
        if session.evaluations:
            summary = compute_session_summary()
            session.write_log({"event": "disconnect_stop", "timestamp": datetime.now().isoformat(), "summary": summary})


@app.get("/api/config")
async def get_config():
    return {
        "api_url": ai_client.base_url,
        "vision_model": ai_client.vision_model,
        "reasoning_model": ai_client.reasoning_model,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)
