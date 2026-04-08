"""
sovereign/cli.py — The `sovereign` command
Sovereign Agents v1.0

Offline commands (no server required):
  sovereign create <name>     Scaffold a new .agent.yaml with sane defaults
  sovereign validate <name>   Validate an agent YAML against the registry rules

Online commands (requires Living Mind Cortex server):
  sovereign list              List all registered agents + live plasma temps
  sovereign deploy <name>     Mark an agent as deployed; heats its plasma domain
  sovereign status            Full system status (VRAM, plasma, heartbeat)
  sovereign bench             Run the 'Drives the Car Better' memory benchmark

Usage:
  python -m sovereign.cli <command> [args]
  # or after pip install: sovereign <command> [args]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

# ── Native .env Loader ───────────────────────────────────────────────────────
_env_file = Path(os.path.expanduser("~/.config/sovereign/.env"))
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        if _line.strip() and not _line.startswith("#"):
            try:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())
            except ValueError:
                pass

# ── Optional httpx for online commands ──────────────────────────────────────
try:
    import httpx
    _HTTPX = True
except ImportError:
    _HTTPX = False

# ── Config ───────────────────────────────────────────────────────────────────
DEFAULT_SERVER   = os.environ.get("SOVEREIGN_SERVER", "http://localhost:8008")
DEFAULT_AGENTS   = os.environ.get("SOVEREIGN_AGENTS_DIR", "./agents")

_default_cortex = os.environ.get(
    "CORTEX_DIR", 
    str(Path(__file__).parent.parent.parent / "living-mind-cortex")
)
BENCHMARK_SCRIPT = os.environ.get(
    "SOVEREIGN_BENCH_SCRIPT",
    str(Path(_default_cortex) / "benchmark_memory.py"),
)

AGENT_YAML_TEMPLATE = """\
name: {name}
skill: autonomous_reasoning
lora_adapter: base_model
friction_heat: 35.0
cooling_constant: 0.003
system_prompt: |
  You are {name}, an autonomous agent in the Sovereign ecosystem.
  Replace this prompt with your agent's identity and directives.
tools:
  - memory_recall
  - cortex_query
  - web_search
"""

# ── ANSI colours ─────────────────────────────────────────────────────────────
_NO_COLOUR = not sys.stdout.isatty() or os.environ.get("NO_COLOR")

def _c(code: str, text: str) -> str:
    return text if _NO_COLOUR else f"\033[{code}m{text}\033[0m"

def green(t: str)  -> str: return _c("32", t)
def yellow(t: str) -> str: return _c("33", t)
def red(t: str)    -> str: return _c("31", t)
def bold(t: str)   -> str: return _c("1",  t)
def dim(t: str)    -> str: return _c("2",  t)
def cyan(t: str)   -> str: return _c("36", t)

# ── Helpers ───────────────────────────────────────────────────────────────────
def _require_httpx() -> None:
    if not _HTTPX:
        print(red("Error: httpx is required for online commands."))
        print(dim("  pip install httpx"))
        sys.exit(1)

def _get(path: str, server: str = DEFAULT_SERVER) -> dict:
    try:
        r = httpx.get(f"{server}{path}", timeout=8.0)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        print(red(f"Cannot reach server at {server}"))
        print(dim("  Is the Living Mind Cortex running? Try: ./start.sh"))
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        print(red(f"Server returned {e.response.status_code}: {e.response.text}"))
        sys.exit(1)

def _post(path: str, payload: dict, server: str = DEFAULT_SERVER) -> dict:
    try:
        r = httpx.post(f"{server}{path}", json=payload, timeout=8.0)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        print(red(f"Cannot reach server at {server}"))
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        print(red(f"Server returned {e.response.status_code}: {e.response.text}"))
        sys.exit(1)

def _plasma_bar(temp_k: float, width: int = 20) -> str:
    """Visual heat bar: ░░░░░▓▓▓▓▓███████████ 142.5K"""
    ratio   = min(temp_k / 500.0, 1.0)
    filled  = int(ratio * width)
    bar     = "█" * filled + "░" * (width - filled)
    colour  = red if temp_k > 300 else (yellow if temp_k > 100 else dim)
    return colour(bar) + f" {temp_k:.1f}K"

def _status_dot(status: str) -> str:
    return {
        "deployed":    green("●"),
        "idle":        dim("○"),
        "sublimated":  yellow("◌"),
    }.get(status, "?")


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_create(args: argparse.Namespace) -> None:
    """Scaffold a new .agent.yaml with sane defaults."""
    agents_dir = Path(args.agents_dir)
    agents_dir.mkdir(parents=True, exist_ok=True)

    # Validate name
    import re
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$", args.name):
        print(red(f"Invalid agent name '{args.name}'."))
        print(dim("  Names must start with alphanumeric and contain only letters, digits, hyphens, underscores."))
        sys.exit(1)

    target = agents_dir / f"{args.name}.agent.yaml"
    if target.exists() and not args.force:
        print(yellow(f"'{target}' already exists. Use --force to overwrite."))
        sys.exit(1)

    target.write_text(AGENT_YAML_TEMPLATE.format(name=args.name), encoding="utf-8")
    print(green("✓") + f" Created {bold(str(target))}")
    print(dim(f"  Edit the file, then run: sovereign validate {args.name}"))


def cmd_validate(args: argparse.Namespace) -> None:
    """Validate an agent YAML without starting the server."""
    from sovereign.registry import AgentRegistry
    reg = AgentRegistry(agents_dir=args.agents_dir)
    reg.load()

    try:
        defn = reg.get(args.name)
    except KeyError as e:
        print(red(f"✗ {e}"))
        sys.exit(1)

    errors = reg.validate(defn)
    if errors:
        print(red(f"✗ '{args.name}' has {len(errors)} validation error(s):"))
        for e in errors:
            print(f"  {red('–')} {e}")
        sys.exit(1)
    else:
        print(green(f"✓ '{args.name}' is valid."))
        print(dim(f"  adapter={defn.lora_adapter}  tools={defn.tools}"))


def cmd_list(args: argparse.Namespace) -> None:
    """List all registered agents with live plasma temperatures."""
    _require_httpx()
    agents = _get("/agents", server=args.server)

    if not agents:
        print(dim("No agents registered. Run: sovereign create <name>"))
        return

    print(f"\n  {bold('Sovereign Agents')}  {dim(args.server)}\n")
    print(f"  {'NAME':<20} {'ADAPTER':<14} {'STATUS':<12} {'PLASMA TEMPERATURE'}")
    print(f"  {dim('─' * 70)}")

    for a in sorted(agents, key=lambda x: x["name"]):
        dot    = _status_dot(a["status"])
        bar    = _plasma_bar(a["plasma_temp"])
        name   = bold(a["name"])
        print(f"  {dot} {name:<28} {dim(a['lora_adapter']):<14} {a['status']:<12} {bar}")
    print()


def cmd_deploy(args: argparse.Namespace) -> None:
    """Mark an agent as deployed and heat its plasma domain."""
    _require_httpx()
    resp = _post(f"/agents/{args.name}/deploy", {}, server=args.server)
    temp = resp.get("plasma_temp", 0.0)
    print(green("✓") + f" '{bold(args.name)}' deployed — plasma: {_plasma_bar(temp)}")


def cmd_status(args: argparse.Namespace) -> None:
    """Full system status: VRAM, plasma, heartbeat."""
    _require_httpx()

    runtime  = _get("/status",          server=args.server)
    hb       = _get("/heartbeat/stats", server=args.server)
    mem      = _get("/memory/stats",    server=args.server)

    try:
        agents = _get("/agents", server=args.server)
        n_deployed = sum(1 for a in agents if a["status"] == "deployed")
    except SystemExit:
        agents     = []
        n_deployed = 0

    print(f"\n  {bold('Sovereign System Status')}\n")
    print(f"  {dim('Runtime')}")
    print(f"    Pulse loops:   {runtime.get('event_loops', 'N/A')}")
    print(f"    Phase:         {runtime.get('phase', 'N/A')}")

    print(f"\n  {dim('Heartbeat')}")
    print(f"    Ticks:         {hb.get('ticks', 0)}")
    print(f"    REM cycles:    {hb.get('rem_cycles', 0)}")
    print(f"    Idle for:      {hb.get('idle_s', 0):.0f}s")
    print(f"    Hot nodes:     {hb.get('hot_nodes', 0)}")
    print(f"    HSM magnitude: {hb.get('hsm_magnitude', 0)}")

    print(f"\n  {dim('Memory')}")
    print(f"    Total stored:  {mem.get('total_memories', 'N/A')}")
    print(f"    Semantic:      {mem.get('semantic_count', 'N/A')}")
    print(f"    Episodic:      {mem.get('episodic_count', 'N/A')}")

    print(f"\n  {dim('Agents')}")
    print(f"    Registered:    {len(agents)}")
    print(f"    Deployed:      {n_deployed}")
    print()


def cmd_bench(args: argparse.Namespace) -> None:
    """Run the 'Drives the Car Better' memory benchmark."""
    script = Path(args.bench_script)
    if not script.exists():
        print(red(f"Benchmark script not found: {script}"))
        print(dim(f"  Set SOVEREIGN_BENCH_SCRIPT or pass --bench-script"))
        sys.exit(1)

    print(cyan("Running memory benchmark..."))
    print(dim(f"  {script}\n"))
    result = subprocess.run([sys.executable, str(script)], check=False)
    sys.exit(result.returncode)


# ── Argument parser ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sovereign",
        description=bold("Sovereign Agents — Local-First Managed Agent Platform"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Environment variables:
              SOVEREIGN_SERVER      Base URL of the Living Mind Cortex (default: http://localhost:8008)
              SOVEREIGN_AGENTS_DIR  Path to agents directory (default: ./agents)
              SOVEREIGN_BENCH_SCRIPT  Path to benchmark_memory.py
              NO_COLOR              Disable ANSI colours
        """),
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # ── create ──────────────────────────────────────────────────
    p_create = sub.add_parser("create", help="Scaffold a new agent YAML")
    p_create.add_argument("name", help="Agent name (alphanumeric, hyphens, underscores)")
    p_create.add_argument("--agents-dir", default=DEFAULT_AGENTS, metavar="DIR")
    p_create.add_argument("--force", action="store_true", help="Overwrite existing file")

    # ── validate ─────────────────────────────────────────────────
    p_val = sub.add_parser("validate", help="Validate an agent YAML (offline)")
    p_val.add_argument("name", help="Agent name to validate")
    p_val.add_argument("--agents-dir", default=DEFAULT_AGENTS, metavar="DIR")

    # ── list ─────────────────────────────────────────────────────
    p_list = sub.add_parser("list", help="List agents with live plasma temperatures")
    p_list.add_argument("--server", default=DEFAULT_SERVER, metavar="URL")

    # ── deploy ───────────────────────────────────────────────────
    p_dep = sub.add_parser("deploy", help="Deploy an agent (heats plasma domain)")
    p_dep.add_argument("name", help="Agent name to deploy")
    p_dep.add_argument("--server", default=DEFAULT_SERVER, metavar="URL")

    # ── status ───────────────────────────────────────────────────
    p_stat = sub.add_parser("status", help="Full system status")
    p_stat.add_argument("--server", default=DEFAULT_SERVER, metavar="URL")

    # ── bench ────────────────────────────────────────────────────
    p_bench = sub.add_parser("bench", help="Run the memory benchmark")
    p_bench.add_argument(
        "--bench-script", default=BENCHMARK_SCRIPT, metavar="PATH",
        help="Path to benchmark_memory.py",
    )

    return parser


# ── Entry point ───────────────────────────────────────────────────────────────

COMMANDS = {
    "create":   cmd_create,
    "validate": cmd_validate,
    "list":     cmd_list,
    "deploy":   cmd_deploy,
    "status":   cmd_status,
    "bench":    cmd_bench,
}

def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()
    COMMANDS[args.command](args)

if __name__ == "__main__":
    main()
