"""Command-line interface for Focus Buddy.

Usage:
    buddy provider list
    buddy provider add <name> --type <type> --url <url> --api-key <key> --vision <model> --reasoning <model>
    buddy provider use <name>
    buddy provider remove <name>
    buddy provider check <name>
    buddy config show
    buddy config set <key> <value>
    buddy start --goal "..." [--provider <name>]
    buddy stop
    buddy status
    buddy logs [--today]
    buddy web [--port 8765]

Examples:
    buddy provider add lmstudio --type lmstudio --url http://100.76.124.69:1234/v1 --api-key not-needed --vision qwen-vl --reasoning deepseek
    buddy start --goal "Finish report" --provider nvidia
    buddy start --goal "Code review" --provider lmstudio
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from . import config
from .providers import registry
from .core.session import session
from .core.evaluator import capture_loop


def _provider_list(args):
    providers = config.list_providers()
    default = config.get("default_provider")
    print(f"{'NAME':<15} {'TYPE':<12} {'URL':<40} {'DEFAULT'}")
    print("-" * 80)
    for name, cfg in providers.items():
        is_default = "*" if name == default else ""
        url = cfg.get("url", "")[:37]
        print(f"{name:<15} {cfg.get('type', '?'):<12} {url:<40} {is_default}")


def _provider_add(args):
    provider_cfg = {
        "type": args.type,
        "url": args.url,
        "api_key": args.api_key or "",
        "vision_model": args.vision or "",
        "reasoning_model": args.reasoning or "",
        "timeout": args.timeout or 90
    }
    config.add_provider(args.name, provider_cfg)
    print(f"Provider '{args.name}' added.")
    # Auto-set as default if it's the only one
    providers = config.list_providers()
    if len(providers) == 1:
        config.set_default_provider(args.name)
        print(f"Set as default provider.")


def _provider_use(args):
    config.set_default_provider(args.name)
    print(f"Default provider set to: {args.name}")


def _provider_remove(args):
    config.remove_provider(args.name)
    print(f"Provider '{args.name}' removed.")


def _provider_check(args):
    async def check():
        try:
            cfg = config.get_provider_config(args.name)
            provider = registry.create_provider(cfg)
            print(f"Checking {provider.get_name()}...")
            result = await provider.health_check()
            if result["ok"]:
                print(f"  Status: OK")
                print(f"  Models found: {len(result['models'])}")
                print(f"  Vision model ({cfg['vision_model']}): {'OK' if result['vision_ok'] else 'NOT FOUND'}")
                print(f"  Reasoning model ({cfg['reasoning_model']}): {'OK' if result['reasoning_ok'] else 'NOT FOUND'}")
            else:
                print(f"  Status: FAILED")
                print(f"  Error: {result['error']}")
        except Exception as e:
            print(f"Check failed: {e}")
    asyncio.run(check())


def _config_show(args):
    cfg = config.load_config()
    # Mask API keys
    safe = json.dumps(cfg, indent=2)
    import re
    safe = re.sub(r'("api_key"\s*:\s*")([^"]{8})[^"]*"', r'\1\2****"', safe)
    print(safe)


def _config_set(args):
    config.set_(args.key, args.value)
    print(f"Set {args.key} = {args.value}")


def _start(args):
    async def start_session():
        provider_name = args.provider or config.get("default_provider")
        try:
            provider_cfg = config.get_provider_config(provider_name)
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)

        provider = registry.create_provider(provider_cfg)
        session.provider = provider
        session.capture_interval = config.get("capture_interval", 15)
        session.eval_interval = config.get("eval_interval", 4)
        session.goal = args.goal
        session.running = True
        session.observations.clear()
        session.evaluations.clear()
        session.off_track_streak = 0
        session.session_start = datetime.now()

        log_dir = config.get_logs_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        session.log_file = log_dir / f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        session.write_log({"event": "start", "goal": args.goal, "timestamp": datetime.now().isoformat()})

        print(f"Session started: {args.goal}")
        print(f"Provider: {provider.get_name()}")
        print(f"Capturing every {session.capture_interval}s...")
        print("Press Ctrl+C to stop")

        session.capture_task = asyncio.create_task(capture_loop())
        try:
            await session.capture_task
        except asyncio.CancelledError:
            pass

    try:
        asyncio.run(start_session())
    except KeyboardInterrupt:
        print("\nStopping session...")
        session.running = False
        if session.capture_task:
            session.capture_task.cancel()
        summary = session.summary()
        print(f"\nSession Summary:")
        print(f"  Focus Score: {summary['focus_score']}/10")
        print(f"  On-track: {summary['on_track_pct']}%")
        print(f"  Duration: {summary['duration_min']} min")
        session.reset()


def _stop(args):
    if not session.running:
        print("No active session.")
        return
    session.running = False
    if session.capture_task:
        session.capture_task.cancel()
    summary = session.summary()
    session.write_log({"event": "stop", "timestamp": datetime.now().isoformat(), "summary": summary})
    print(f"Session stopped.")
    print(f"Focus Score: {summary['focus_score']}/10")
    session.reset()


def _status(args):
    if not session.running:
        print("No active session.")
        return
    print(f"Goal: {session.goal}")
    print(f"Running: {session.running}")
    print(f"Observations: {len(session.observations)}")
    print(f"Evaluations: {len(session.evaluations)}")
    print(f"Off-track streak: {session.off_track_streak}")
    print(f"Provider: {session.provider.get_name() if session.provider else 'None'}")


def _logs(args):
    log_dir = config.get_logs_dir()
    if not log_dir.exists():
        print("No logs found.")
        return

    files = sorted(log_dir.glob("*.jsonl"))
    if args.today:
        today = datetime.now().strftime("%Y%m%d")
        files = [f for f in files if f.name.startswith(f"session_{today}")]

    if not files:
        print("No logs found.")
        return

    for f in files:
        size = f.stat().st_size
        print(f"{f.name} ({size} bytes)")


def _web(args):
    from .web.server import run_server
    print(f"Starting web server on http://localhost:{args.port}")
    print(f"Open your browser to http://localhost:{args.port}")
    run_server(host=args.host, port=args.port)


def main():
    parser = argparse.ArgumentParser(
        prog="buddy",
        description="Focus Buddy - AI-powered accountability partner"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # provider
    provider_parser = subparsers.add_parser("provider", help="Manage AI providers")
    provider_sub = provider_parser.add_subparsers(dest="provider_cmd")

    p_list = provider_sub.add_parser("list", help="List configured providers")
    p_list.set_defaults(func=_provider_list)

    p_add = provider_sub.add_parser("add", help="Add a provider")
    p_add.add_argument("name", help="Provider name")
    p_add.add_argument("--type", required=True, choices=["nvidia", "lmstudio", "openai", "ollama"], help="Provider type")
    p_add.add_argument("--url", required=True, help="API endpoint URL")
    p_add.add_argument("--api-key", default="", help="API key")
    p_add.add_argument("--vision", required=True, help="Vision model name")
    p_add.add_argument("--reasoning", required=True, help="Reasoning model name")
    p_add.add_argument("--timeout", type=int, default=90, help="Request timeout in seconds")
    p_add.set_defaults(func=_provider_add)

    p_use = provider_sub.add_parser("use", help="Set default provider")
    p_use.add_argument("name", help="Provider name")
    p_use.set_defaults(func=_provider_use)

    p_remove = provider_sub.add_parser("remove", help="Remove a provider")
    p_remove.add_argument("name", help="Provider name")
    p_remove.set_defaults(func=_provider_remove)

    p_check = provider_sub.add_parser("check", help="Check provider health")
    p_check.add_argument("name", help="Provider name")
    p_check.set_defaults(func=_provider_check)

    # config
    config_parser = subparsers.add_parser("config", help="Manage configuration")
    config_sub = config_parser.add_subparsers(dest="config_cmd")

    c_show = config_sub.add_parser("show", help="Show current config")
    c_show.set_defaults(func=_config_show)

    c_set = config_sub.add_parser("set", help="Set a config value")
    c_set.add_argument("key", help="Config key")
    c_set.add_argument("value", help="Config value")
    c_set.set_defaults(func=_config_set)

    # start
    start_parser = subparsers.add_parser("start", help="Start a focus session")
    start_parser.add_argument("--goal", "-g", required=True, help="Session goal")
    start_parser.add_argument("--provider", "-p", help="Override provider")
    start_parser.set_defaults(func=_start)

    # stop
    stop_parser = subparsers.add_parser("stop", help="Stop current session")
    stop_parser.set_defaults(func=_stop)

    # status
    status_parser = subparsers.add_parser("status", help="Show session status")
    status_parser.set_defaults(func=_status)

    # logs
    logs_parser = subparsers.add_parser("logs", help="List session logs")
    logs_parser.add_argument("--today", action="store_true", help="Show only today's logs")
    logs_parser.set_defaults(func=_logs)

    # web
    web_parser = subparsers.add_parser("web", help="Start web UI server")
    web_parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    web_parser.add_argument("--port", "-p", type=int, default=8765, help="Bind port")
    web_parser.set_defaults(func=_web)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
