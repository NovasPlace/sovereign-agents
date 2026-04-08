"""
sovereign/registry.py — Agent Registry
Sovereign Agents v1.0

Scans ./agents/*.agent.yaml, validates definitions against known adapter paths
and the tool registry, and exposes a coroutine-safe runtime registry with hot-reload.

Review fixes applied on top of frontier AI implementation:
  1. base_model sentinel: skip disk path check for the persistent substrate.
  2. Adapter path existence: warning only — missing LoRAs don't block load.
  3. Docstring: coroutine-safe (not thread-safe — no locking, single event loop).
  4. Name validation: explicit re.match instead of fragile str.replace().isalnum().
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known adapter identifiers.  Pass a custom dict to AgentRegistry.__init__
# to extend without touching this module.
# ---------------------------------------------------------------------------
DEFAULT_ADAPTER_PATHS: dict[str, str] = {
    "base_model":   "",                   # Persistent substrate — no adapter dir
    "code_expert":  "adapters/code_expert",
    "logic_expert": "adapters/logic_expert",
}

# Sentinel: adapters that are always resident and need no disk path check.
_ALWAYS_RESIDENT: frozenset[str] = frozenset({"base_model"})

# Tools that are always available regardless of agent config.
DEFAULT_TOOL_REGISTRY: set[str] = {
    "memory_recall",
    "shell_exec",
    "web_search",
    "file_read",
    "file_write",
    "cortex_query",
    "htp_broadcast",
}

# Valid runtime statuses.
VALID_STATUSES = {"idle", "deployed", "sublimated"}

# Name must start with alphanumeric, may contain hyphens/underscores.
_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class AgentDefinition:
    """
    Pure configuration record for one agent.
    Populated from a .agent.yaml file; no live state here.
    Safely serialisable and reloadable without touching runtime.
    """
    name:             str
    skill:            str
    lora_adapter:     str
    system_prompt:    str
    tools:            list[str]     = field(default_factory=list)
    friction_heat:    float         = 35.0
    cooling_constant: float         = 0.003
    # Source path — set by the registry after load, not from YAML.
    source_path:      Path | None   = field(default=None, repr=False)


@dataclass
class AgentRuntimeState:
    """
    Live state for a deployed agent — kept separate from AgentDefinition
    so config stays pure and serialisable.
    Lazily created on first deploy; not persisted across restarts.
    """
    name:        str
    status:      str   = "idle"   # idle | deployed | sublimated
    last_active: float = 0.0      # unix timestamp, 0.0 = never activated
    plasma_temp: float = 0.0      # current ThermorphicPlasma temperature (K)

    def touch(self) -> None:
        self.last_active = time.time()

    def set_status(self, status: str) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Unknown status '{status}'. Valid: {VALID_STATUSES}")
        self.status = status


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class AgentRegistry:
    """
    Scans an agents directory for *.agent.yaml files, validates each definition,
    and maintains an in-memory registry with hot-reload support.

    Coroutine-safe within a single asyncio event loop (FastAPI/uvicorn).
    NOT thread-safe — no locking is applied. Do not share across threads.

    Usage::

        registry = AgentRegistry(
            agents_dir="./agents",
            adapter_paths=DEFAULT_ADAPTER_PATHS,   # optional override
            tool_registry=DEFAULT_TOOL_REGISTRY,   # optional override
        )
        registry.load()

        defn  = registry.get("zola")
        defns = registry.list()

        # Hot-reload without restarting the runtime:
        registry.reload()
    """

    def __init__(
        self,
        agents_dir: str | Path = "./agents",
        adapter_paths: dict[str, str] | None = None,
        tool_registry: set[str] | None = None,
    ) -> None:
        self._agents_dir    = Path(agents_dir)
        self._adapter_paths = adapter_paths if adapter_paths is not None else dict(DEFAULT_ADAPTER_PATHS)
        self._tool_registry = tool_registry if tool_registry is not None else set(DEFAULT_TOOL_REGISTRY)

        # name → AgentDefinition
        self._definitions: dict[str, AgentDefinition] = {}
        # name → AgentRuntimeState  (populated lazily on deploy)
        self._runtime: dict[str, AgentRuntimeState] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> list[AgentDefinition]:
        """
        Scan agents_dir for *.agent.yaml files, parse and validate each one.
        Malformed or invalid files are logged and skipped — partial load beats
        a hard crash on a single bad YAML.

        Returns the list of successfully loaded AgentDefinitions.
        """
        if not self._agents_dir.exists():
            log.warning("agents_dir '%s' does not exist — no agents loaded.", self._agents_dir)
            return []

        loaded: dict[str, AgentDefinition] = {}
        yaml_files = sorted(self._agents_dir.glob("*.agent.yaml"))

        if not yaml_files:
            log.warning("No *.agent.yaml files found in '%s'.", self._agents_dir)

        for path in yaml_files:
            defn, errors = self._parse_file(path)
            if defn is None:
                log.error("Skipping '%s': YAML parse failed.", path.name)
                continue
            if errors:
                for e in errors:
                    log.error("Skipping '%s': %s", path.name, e)
                continue
            if defn.name in loaded:
                log.warning(
                    "Duplicate agent name '%s' in '%s' — keeping first definition.",
                    defn.name, path.name,
                )
                continue
            loaded[defn.name] = defn
            log.info("Loaded agent '%s' from '%s'.", defn.name, path.name)

        self._definitions = loaded
        # Preserve runtime state for agents that survived the reload.
        self._runtime = {
            name: state
            for name, state in self._runtime.items()
            if name in self._definitions
        }
        return list(self._definitions.values())

    def reload(self) -> list[AgentDefinition]:
        """
        Hot-reload all agent definitions without restarting the runtime.
        Runtime state (status, plasma_temp, last_active) is preserved for
        agents whose names survive the reload.
        """
        log.info("Hot-reloading agent registry from '%s'.", self._agents_dir)
        return self.load()

    def get(self, name: str) -> AgentDefinition:
        """
        Return the AgentDefinition for *name*.
        Raises KeyError with a helpful message listing available agents.
        """
        if name not in self._definitions:
            available = ", ".join(sorted(self._definitions)) or "<none>"
            raise KeyError(f"Agent '{name}' not found. Available: {available}")
        return self._definitions[name]

    def list(self) -> list[AgentDefinition]:
        """Return all loaded AgentDefinitions, sorted by name."""
        return sorted(self._definitions.values(), key=lambda d: d.name)

    def validate(self, defn: AgentDefinition) -> list[str]:
        """
        Validate an AgentDefinition against known adapters and tools.
        Returns a list of error strings. Empty list == valid.

        Adapter path existence is a WARNING logged here but NOT returned as an
        error — callers should still be able to register agents whose LoRAs
        haven't been trained yet. The load path will warn; the router's
        ensure_loaded() will be the hard gate at inference time.
        """
        errors: list[str] = []

        # Name must match ^[a-zA-Z0-9][a-zA-Z0-9_-]*$
        if not defn.name or not _NAME_RE.match(defn.name):
            errors.append(
                f"name '{defn.name}' must start with alphanumeric and contain "
                f"only letters, digits, hyphens, or underscores."
            )

        if defn.lora_adapter not in self._adapter_paths:
            known = ", ".join(sorted(self._adapter_paths))
            errors.append(
                f"lora_adapter '{defn.lora_adapter}' unknown. Known adapters: {known}"
            )
        elif defn.lora_adapter not in _ALWAYS_RESIDENT:
            # Disk path check — warning only, not a blocking error.
            # LoRA weights may not exist until training completes.
            adapter_path = Path(self._adapter_paths[defn.lora_adapter])
            if not adapter_path.exists():
                log.warning(
                    "Adapter path '%s' for '%s' does not exist on disk. "
                    "Agent will load but inference will fall back to base_model "
                    "until weights are present.",
                    adapter_path, defn.lora_adapter,
                )

        unknown_tools = sorted(set(defn.tools) - self._tool_registry)
        if unknown_tools:
            errors.append(
                f"Unknown tools: {unknown_tools}. "
                f"Register them in tool_registry or remove from agent config."
            )

        if not defn.system_prompt or not defn.system_prompt.strip():
            errors.append("system_prompt must not be empty.")

        if defn.friction_heat <= 0:
            errors.append(f"friction_heat must be > 0, got {defn.friction_heat}.")

        if defn.cooling_constant <= 0:
            errors.append(f"cooling_constant must be > 0, got {defn.cooling_constant}.")

        return errors

    # ------------------------------------------------------------------
    # Runtime state helpers (used by CLI + API layer)
    # ------------------------------------------------------------------

    def get_runtime(self, name: str) -> AgentRuntimeState:
        """
        Return (or lazily create) the AgentRuntimeState for *name*.
        Raises KeyError if the agent definition doesn't exist.
        """
        self.get(name)  # validates existence
        if name not in self._runtime:
            self._runtime[name] = AgentRuntimeState(name=name)
        return self._runtime[name]

    def set_status(self, name: str, status: str) -> None:
        state = self.get_runtime(name)
        state.set_status(status)
        if status == "deployed":
            state.touch()

    def update_plasma_temp(self, name: str, temp_k: float) -> None:
        state = self.get_runtime(name)
        state.plasma_temp = temp_k

    def summary(self) -> list[dict[str, Any]]:
        """
        Flat summary of all agents — config + runtime state merged.
        Used by GET /agents and `sovereign list`.
        """
        out = []
        for defn in self.list():
            runtime = self._runtime.get(defn.name)
            out.append({
                "name":             defn.name,
                "skill":            defn.skill,
                "lora_adapter":     defn.lora_adapter,
                "tools":            defn.tools,
                "system_prompt":    defn.system_prompt,
                "friction_heat":    defn.friction_heat,
                "cooling_constant": defn.cooling_constant,
                "status":           runtime.status      if runtime else "idle",
                "last_active":      runtime.last_active if runtime else 0.0,
                "plasma_temp":      runtime.plasma_temp if runtime else 0.0,
            })
        return out

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_file(self, path: Path) -> tuple[AgentDefinition | None, list[str]]:
        """
        Parse a single .agent.yaml file.
        Returns (AgentDefinition, errors). If YAML parse fails, returns (None, []).
        """
        try:
            raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            log.exception("Failed to parse YAML at '%s': %s", path, exc)
            return None, []

        missing = [f for f in ("name", "skill", "lora_adapter", "system_prompt") if f not in raw]
        if missing:
            return None, [f"Missing required fields: {missing}"]

        defn = AgentDefinition(
            name             = str(raw["name"]),
            skill            = str(raw["skill"]),
            lora_adapter     = str(raw["lora_adapter"]),
            system_prompt    = str(raw["system_prompt"]),
            tools            = list(raw.get("tools", [])),
            friction_heat    = float(raw.get("friction_heat", 35.0)),
            cooling_constant = float(raw.get("cooling_constant", 0.003)),
            source_path      = path,
        )

        errors = self.validate(defn)
        return defn, errors
