"""
tests/test_registry.py
Test suite for sovereign/registry.py covering:
  - Happy path: valid agents load cleanly
  - Error path: bad YAML, missing fields, unknown adapter, unknown tools
  - Edge: duplicate names, empty agents dir, name validation
  - Adversarial: path traversal attempt in name, empty system_prompt
  - Runtime state: deploy/status/plasma_temp lifecycle
  - Hot-reload: runtime state preserved across reload
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tempfile
import textwrap
from pathlib import Path

import pytest
from sovereign.registry import (
    AgentRegistry,
    AgentDefinition,
    AgentRuntimeState,
    DEFAULT_ADAPTER_PATHS,
    DEFAULT_TOOL_REGISTRY,
)

# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────
def write_yaml(dir_: Path, filename: str, content: str) -> Path:
    p = dir_ / filename
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p

def make_registry(agents_dir: Path) -> AgentRegistry:
    return AgentRegistry(
        agents_dir=agents_dir,
        adapter_paths={
            "base_model":   "",           # sentinel — no disk check
            "code_expert":  "/tmp/fake_code_expert",
            "logic_expert": "/tmp/fake_logic_expert",
        },
        tool_registry=DEFAULT_TOOL_REGISTRY,
    )

# ─────────────────────────────────────────
# 1. Happy path
# ─────────────────────────────────────────
def test_load_valid_agent():
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        write_yaml(dp, "zola.agent.yaml", """
            name: zola
            skill: reasoning
            lora_adapter: base_model
            system_prompt: "You are Zola."
            tools: [memory_recall, cortex_query]
        """)
        reg = make_registry(dp)
        agents = reg.load()
        assert len(agents) == 1
        assert agents[0].name == "zola"
        assert agents[0].lora_adapter == "base_model"
        assert "memory_recall" in agents[0].tools

def test_load_multiple_agents():
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        write_yaml(dp, "zola.agent.yaml", """
            name: zola
            skill: reasoning
            lora_adapter: base_model
            system_prompt: "Zola."
        """)
        write_yaml(dp, "auditor.agent.yaml", """
            name: auditor
            skill: code_review
            lora_adapter: base_model
            system_prompt: "Auditor."
        """)
        reg = make_registry(dp)
        agents = reg.load()
        assert len(agents) == 2
        names = [a.name for a in reg.list()]
        assert names == sorted(names)  # list() returns sorted

# ─────────────────────────────────────────
# 2. Fault tolerant load
# ─────────────────────────────────────────
def test_bad_yaml_skipped():
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        (dp / "broken.agent.yaml").write_text("{{ not: valid: yaml: {{", encoding="utf-8")
        write_yaml(dp, "good.agent.yaml", """
            name: good
            skill: test
            lora_adapter: base_model
            system_prompt: "Good agent."
        """)
        reg = make_registry(dp)
        agents = reg.load()
        assert len(agents) == 1
        assert agents[0].name == "good"

def test_missing_required_fields_skipped():
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        write_yaml(dp, "incomplete.agent.yaml", """
            name: incomplete
            skill: test
            # missing lora_adapter and system_prompt
        """)
        reg = make_registry(dp)
        agents = reg.load()
        assert len(agents) == 0

def test_duplicate_name_keeps_first():
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        write_yaml(dp, "a_zola.agent.yaml", """
            name: zola
            skill: first
            lora_adapter: base_model
            system_prompt: "First."
        """)
        write_yaml(dp, "b_zola.agent.yaml", """
            name: zola
            skill: second
            lora_adapter: base_model
            system_prompt: "Second."
        """)
        reg = make_registry(dp)
        agents = reg.load()
        assert len(agents) == 1
        assert agents[0].skill == "first"

# ─────────────────────────────────────────
# 3. Validation
# ─────────────────────────────────────────
def test_unknown_adapter_is_error():
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        write_yaml(dp, "bad_adapter.agent.yaml", """
            name: ghost
            skill: test
            lora_adapter: nonexistent_expert
            system_prompt: "Ghost."
        """)
        reg = make_registry(dp)
        agents = reg.load()
        assert len(agents) == 0

def test_unknown_tools_are_error():
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        write_yaml(dp, "bad_tools.agent.yaml", """
            name: badtools
            skill: test
            lora_adapter: base_model
            system_prompt: "Test."
            tools: [memory_recall, nonexistent_tool]
        """)
        reg = make_registry(dp)
        agents = reg.load()
        assert len(agents) == 0

def test_empty_system_prompt_is_error():
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        write_yaml(dp, "empty_prompt.agent.yaml", """
            name: silent
            skill: test
            lora_adapter: base_model
            system_prompt: "   "
        """)
        reg = make_registry(dp)
        agents = reg.load()
        assert len(agents) == 0

def test_invalid_name_rejected():
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        write_yaml(dp, "bad_name.agent.yaml", """
            name: "../path-traversal"
            skill: test
            lora_adapter: base_model
            system_prompt: "Bad actor."
        """)
        reg = make_registry(dp)
        agents = reg.load()
        assert len(agents) == 0

def test_name_with_hyphens_underscores_valid():
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        write_yaml(dp, "valid.agent.yaml", """
            name: my-agent_v2
            skill: test
            lora_adapter: base_model
            system_prompt: "Valid name."
        """)
        reg = make_registry(dp)
        agents = reg.load()
        assert len(agents) == 1

def test_base_model_no_disk_path_required():
    """base_model is always-resident — no disk path check should block loading."""
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        write_yaml(dp, "zola.agent.yaml", """
            name: zola
            skill: reasoning
            lora_adapter: base_model
            system_prompt: "Zola."
        """)
        # adapters/base_model dir does NOT exist — must still load cleanly
        reg = AgentRegistry(
            agents_dir=dp,
            adapter_paths={"base_model": "nonexistent/path/that/does/not/exist"},
            tool_registry=DEFAULT_TOOL_REGISTRY,
        )
        agents = reg.load()
        assert len(agents) == 1  # base_model sentinel skips the path check

# ─────────────────────────────────────────
# 4. get() / KeyError
# ─────────────────────────────────────────
def test_get_existing_agent():
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        write_yaml(dp, "zola.agent.yaml", """
            name: zola
            skill: reasoning
            lora_adapter: base_model
            system_prompt: "Zola."
        """)
        reg = make_registry(dp)
        reg.load()
        defn = reg.get("zola")
        assert defn.name == "zola"

def test_get_missing_raises_keyerror():
    with tempfile.TemporaryDirectory() as d:
        reg = make_registry(Path(d))
        reg.load()
        with pytest.raises(KeyError, match="not found"):
            reg.get("ghost")

# ─────────────────────────────────────────
# 5. Runtime state lifecycle
# ─────────────────────────────────────────
def test_runtime_state_lazy_creation():
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        write_yaml(dp, "zola.agent.yaml", """
            name: zola
            skill: reasoning
            lora_adapter: base_model
            system_prompt: "Zola."
        """)
        reg = make_registry(dp)
        reg.load()
        state = reg.get_runtime("zola")
        assert isinstance(state, AgentRuntimeState)
        assert state.status == "idle"
        assert state.plasma_temp == 0.0

def test_set_status_deploy():
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        write_yaml(dp, "zola.agent.yaml", """
            name: zola
            skill: reasoning
            lora_adapter: base_model
            system_prompt: "Zola."
        """)
        reg = make_registry(dp)
        reg.load()
        reg.set_status("zola", "deployed")
        state = reg.get_runtime("zola")
        assert state.status == "deployed"
        assert state.last_active > 0

def test_plasma_temp_update():
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        write_yaml(dp, "zola.agent.yaml", """
            name: zola
            skill: reasoning
            lora_adapter: base_model
            system_prompt: "Zola."
        """)
        reg = make_registry(dp)
        reg.load()
        reg.update_plasma_temp("zola", 142.5)
        assert reg.get_runtime("zola").plasma_temp == 142.5

# ─────────────────────────────────────────
# 6. Hot-reload preserves runtime state
# ─────────────────────────────────────────
def test_reload_preserves_deployed_state():
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        write_yaml(dp, "zola.agent.yaml", """
            name: zola
            skill: reasoning
            lora_adapter: base_model
            system_prompt: "Zola."
        """)
        reg = make_registry(dp)
        reg.load()
        reg.set_status("zola", "deployed")
        reg.update_plasma_temp("zola", 200.0)

        reg.reload()  # hot-reload

        state = reg.get_runtime("zola")
        assert state.status == "deployed"
        assert state.plasma_temp == 200.0

def test_reload_drops_removed_agent_runtime():
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        write_yaml(dp, "zola.agent.yaml", """
            name: zola
            skill: reasoning
            lora_adapter: base_model
            system_prompt: "Zola."
        """)
        write_yaml(dp, "temp.agent.yaml", """
            name: temp
            skill: test
            lora_adapter: base_model
            system_prompt: "Temp."
        """)
        reg = make_registry(dp)
        reg.load()
        reg.set_status("temp", "deployed")

        # Remove temp agent file before reload
        (dp / "temp.agent.yaml").unlink()
        reg.reload()

        assert "temp" not in reg._runtime
        assert "temp" not in [a.name for a in reg.list()]

# ─────────────────────────────────────────
# 7. summary()
# ─────────────────────────────────────────
def test_summary_shape():
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        write_yaml(dp, "zola.agent.yaml", """
            name: zola
            skill: reasoning
            lora_adapter: base_model
            system_prompt: "Zola."
            tools: [memory_recall]
        """)
        reg = make_registry(dp)
        reg.load()
        s = reg.summary()
        assert len(s) == 1
        row = s[0]
        for key in ("name", "skill", "lora_adapter", "tools",
                    "friction_heat", "cooling_constant",
                    "status", "last_active", "plasma_temp"):
            assert key in row, f"Missing key in summary: {key}"
        assert row["status"] == "idle"
        assert row["plasma_temp"] == 0.0

# ─────────────────────────────────────────
# 8. Empty agents dir
# ─────────────────────────────────────────
def test_empty_agents_dir_returns_empty():
    with tempfile.TemporaryDirectory() as d:
        reg = make_registry(Path(d))
        agents = reg.load()
        assert agents == []

def test_nonexistent_agents_dir_returns_empty():
    reg = make_registry(Path("/tmp/sovereign_agents_dir_that_doesnt_exist_xyz"))
    agents = reg.load()
    assert agents == []
