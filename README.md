# Focus Buddy

AI-powered accountability partner. It watches your screen, judges your focus, and yells at you when you're bullshitting.

---

## What It Does

1. **Captures your screen** every 15 seconds
2. **Vision model** describes what you're actually doing
3. **Reasoning model** evaluates if it's aligned with your stated goal
4. **Notifies you** with sound + browser alerts when you're off-track
5. **Escalates**: gentle → moderate → aggressive (with voice alerts)

---

## Installation

```bash
cd Buddy-v0
pip install -r requirements.txt
```

---

## Quick Start

### Web UI (Recommended)

```bash
python -m buddy web
```

Open `http://localhost:8765` in your browser. Enter a goal, click **Start Session**.

### CLI Mode

```bash
python -m buddy start --goal "Finish the report"
```

Press `Ctrl+C` to stop.

---

## Provider Management (Dynamic Switching)

Focus Buddy supports multiple AI backends. You can switch between them anytime without editing code.

### Supported Provider Types

| Type | Description | Example |
|------|-------------|---------|
| `nvidia` | NVIDIA NIM API | `https://integrate.api.nvidia.com/v1` |
| `lmstudio` | Local LM Studio server | `http://100.76.124.69:1234/v1` |
| `openai` | Generic OpenAI-compatible | Any `/v1` endpoint |
| `ollama` | Local Ollama server | `http://localhost:11434` |

### List Providers

```bash
python -m buddy provider list
```

Output:
```
NAME            TYPE         URL                                      DEFAULT
--------------------------------------------------------------------------------
nvidia          nvidia       https://integrate.api.nvidia.com/v1      *
lmstudio        lmstudio     http://100.76.124.69:1234/v1
```

### Add a Provider

**NVIDIA (default, pre-configured):**
Already included. No action needed.

**LM Studio (local):**
```bash
python -m buddy provider add lmstudio \
  --type lmstudio \
  --url http://100.76.124.69:1234/v1 \
  --api-key not-needed \
  --vision qwen/qwen2.5-vl-7b-instruct \
  --reasoning deepseek-ai/deepseek-v4-pro
```

**Ollama (local):**
```bash
python -m buddy provider add local \
  --type ollama \
  --url http://localhost:11434 \
  --vision llava \
  --reasoning llama3
```

**Generic OpenAI-compatible endpoint:**
```bash
python -m buddy provider add myapi \
  --type openai \
  --url https://api.example.com/v1 \
  --api-key sk-xxx \
  --vision gpt-4o \
  --reasoning gpt-4o
```

### Switch Default Provider

```bash
python -m buddy provider use lmstudio
```

This changes the default for all future sessions (CLI + Web UI).

### One-Off Provider Override

Start a session with a specific provider without changing the default:

```bash
python -m buddy start --goal "Code review" --provider lmstudio
```

### Check Provider Health

```bash
python -m buddy provider check nvidia
```

Verifies the endpoint is reachable and models are available.

### Remove a Provider

```bash
python -m buddy provider remove lmstudio
```

---

## CLI Commands

### Session Control

```bash
# Start session (uses default provider)
python -m buddy start --goal "Finish report"

# Start with specific provider
python -m buddy start --goal "Finish report" --provider lmstudio

# Stop session
python -m buddy stop

# Check status
python -m buddy status
```

### Logs

```bash
# List all session logs
python -m buddy logs

# List only today's logs
python -m buddy logs --today
```

Logs are stored in `~/.local/share/buddy/logs/` (XDG compliant).

### Config

```bash
# Show full config (API keys masked)
python -m buddy config show

# Change capture interval (seconds)
python -m buddy config set capture_interval 10

# Change evaluation interval (observations per eval)
python -m buddy config set eval_interval 4
```

### Web UI

```bash
# Start web server on default port 8765
python -m buddy web

# Custom port
python -m buddy web --port 8080

# Custom host
python -m buddy web --host 127.0.0.1 --port 8080
```

---

## Web UI Features

- **Goal input**: What you plan to work on
- **Live activity log**: Real-time screen descriptions
- **Focus status**: On-track / off-track indicator
- **Streak counter**: How long you've been distracted
- **Test Notification**: Verify sound + TTS before starting
- **Notification permission status**: Green (enabled) / Yellow (click to enable) / Red (blocked)

### Alert System

| Level | Trigger | What Happens |
|-------|---------|--------------|
| **Gentle** | 1st off-track eval | Soft beep + browser notification |
| **Moderate** | 2nd off-track eval | Louder beeps + TTS speaks the reason |
| **Aggressive** | 3rd+ off-track eval | Alarm sound + red screen flash + TTS yells + repeat notification every 3s |

**Note**: No full-screen blocking. Your screen stays usable.

---

## REST API (For Agent Integration)

Any external agent can control Focus Buddy via HTTP.

### Endpoints

#### List Providers
```bash
GET /api/v1/providers
```

#### Start Session
```bash
POST /api/v1/session/start
Content-Type: application/json

{
  "goal": "Finish report",
  "provider": "nvidia"
}
```

#### Check Status
```bash
GET /api/v1/session/status
```

Response:
```json
{
  "running": true,
  "goal": "Finish report",
  "observations": 12,
  "evaluations": 3,
  "off_track_streak": 1,
  "provider": "NVIDIA NIM",
  "summary": null
}
```

#### Stop Session
```bash
POST /api/v1/session/stop
```

Response:
```json
{
  "status": "stopped",
  "summary": {
    "focus_score": 8,
    "on_track_pct": 85.7,
    "total_evals": 7,
    "duration_min": 5.2
  }
}
```

---

## Configuration

Config is stored in `~/.config/buddy/config.json` (XDG Base Directory spec).

Example:
```json
{
  "version": "0.2.0",
  "default_provider": "nvidia",
  "capture_interval": 15,
  "eval_interval": 4,
  "providers": {
    "nvidia": {
      "type": "nvidia",
      "url": "https://integrate.api.nvidia.com/v1",
      "api_key": "nvapi-...",
      "vision_model": "meta/llama-3.2-11b-vision-instruct",
      "reasoning_model": "qwen/qwen2.5-coder-32b-instruct",
      "timeout": 90
    },
    "lmstudio": {
      "type": "lmstudio",
      "url": "http://100.76.124.69:1234/v1",
      "api_key": "not-needed",
      "vision_model": "qwen/qwen2.5-vl-7b-instruct",
      "reasoning_model": "deepseek-ai/deepseek-v4-pro",
      "timeout": 90
    }
  }
}
```

---

## Architecture

```
buddy/
├── cli.py              # Terminal interface
├── config.py           # ~/.config/buddy/config.json management
├── core/
│   ├── session.py      # Session state machine
│   ├── evaluator.py    # Vision → reasoning pipeline
│   └── capture.py      # Screenshot engine
├── providers/
│   ├── base.py         # Abstract provider interface
│   ├── registry.py     # Provider discovery
│   ├── openai_compatible.py  # NVIDIA, LM Studio, generic
│   └── ollama.py       # Ollama local server
├── web/
│   ├── server.py       # FastAPI + WebSocket
│   └── frontend/
│       └── index.html  # Browser UI
└── api/
    └── routes.py       # REST API for agents
```

---

## Environment Variables

You can override config via environment variables:

```bash
FOCUS_API_URL=https://integrate.api.nvidia.com/v1
FOCUS_API_KEY=nvapi-...
FOCUS_VISION_MODEL=meta/llama-3.2-11b-vision-instruct
FOCUS_REASONING_MODEL=qwen/qwen2.5-coder-32b-instruct
```

These are used as fallbacks if no providers are configured.

---

## Troubleshooting

### "Provider not found"
Run `python -m buddy provider list` to see configured providers. Add one with `provider add`.

### "Vision Error: 404"
The vision model doesn't exist on your endpoint. Run `python -m buddy provider check <name>` to see available models.

### Notifications not showing
Click the yellow **"Click to enable notifications"** badge on the web UI, or check your browser's site permissions.

### No sound
Click **"Test Notification"** before starting. Browser autoplay policies may block audio until you interact with the page.

### WebSocket crashes
Make sure you're running `python -m buddy web`, not the old `app.py` directly.

---

## License

MIT
