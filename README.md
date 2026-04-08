# Sovereign Agents

**Everything Claude Managed Agents does — on your hardware, with memory that actually works, free forever.**

> Claude Managed Agents launched April 8th, 2026. Cloud-only. Per-token billing. Stateless memory.
> Sovereign Agents ships the same week. Local-first. Zero API costs. Physics-based memory with verified benchmark results.

---

## The Memory Problem Nobody Talks About

Every managed agent platform has the same silent failure: **stale facts in context.**

Ask your agent about the codebase after a long session. It retrieves things you discussed three hours ago alongside things you discussed three minutes ago, weighted equally. The agent "knows" both. It acts on both. The older one is probably wrong.

This isn't a prompt engineering problem. It's a retrieval architecture problem.

**Flat RAG treats every memory as equally valid regardless of when it was last relevant.** Your agent is driving with a windshield full of old maps.

---

## The Fix: Memory With Temperature

Sovereign Agents replaces LRU cache with **Thermomorphic Memory Plasma** — a physics-based working memory layer built on Newton's Law of Cooling.

- Every memory has a **temperature** measured in Kelvin
- Access adds **friction heat** — keeps it hot
- Time without access causes **exponential decay** — it cools
- At absolute zero, the memory **sublimates** — auto-evicted from VRAM

No garbage collection. No TTL tuning. One constant: `k` (your Focus Window).

### Benchmark Results

Setup: 100 memory events over 20 sessions — 10 core truths (accessed repeatedly) + 70 random noise + 20 **adversarial noise** (geometrically near the truth cluster, appeared once recently to fool retrieval).

```
                    Flat RAG    Sovereign Agents
─────────────────────────────────────────────────
Recall @ top-10       80%           100%    (+20%)
Noise in context        2              0    (zero)
─────────────────────────────────────────────────
Sublimation audit:   N/A         38 evictions
Core truths lost:    N/A              0     (zero)
Noise evicted:       N/A             38   (100%)
```

**The physics discriminates at the retention layer, not just retrieval ranking.**
Every single event that sublimated was noise. Not one core truth was lost.

Zero noise in context isn't a tuning outcome. It's the physics.

---

## vs Cloud Managed Agents

| | Cloud Platforms | Sovereign Agents |
|---|---|---|
| **Runs on** | Their servers | Your hardware |
| **Cost** | Per-token billing | Free forever |
| **Memory** | Stateless / basic RAG | Thermomorphic Plasma |
| **Privacy** | Your data leaves your machine | Never leaves your machine |
| **VRAM management** | N/A (cloud GPU) | Thermal LoRA eviction |
| **Multi-agent** | Yes | Yes (P2P, no broker) |
| **Offline** | ❌ | ✅ |

---

## Quick Start

**Requirements:** Python 3.11+, PostgreSQL 14+, [Living Mind Cortex](https://github.com/NovasPlace/living-mind-cortex)

```bash
git clone https://github.com/NovasPlace/sovereign-agents
cd sovereign-agents
./install.sh
```

`install.sh` will:
1. Check PostgreSQL is running (exits with a clear error if not)
2. Create the database and seed the schema
3. Install Python dependencies
4. Start the Living Mind Cortex server
5. Confirm all agents are loaded

**That's it.** Your agents are running locally.

---

## Defining an Agent

Agents are YAML files. Drop them in `./agents/` and reload — no restart needed.

```yaml
# agents/my-agent.agent.yaml
name: my-agent
skill: autonomous_reasoning
lora_adapter: base_model          # base_model | code_expert | logic_expert
friction_heat: 35.0               # How fast this agent heats up in plasma
cooling_constant: 0.003           # How fast it cools (Focus Window)
system_prompt: |
  You are my-agent. Replace this with your agent's identity.
tools:
  - memory_recall
  - cortex_query
  - web_search
```

**The `friction_heat` and `cooling_constant` are your agent's thermal profile.**
A high `friction_heat` agent dominates context once active. A low `cooling_constant` agent stays relevant for hours. This is the Terry archetype in config form.

---

## CLI

```
sovereign create <name>     Scaffold a new agent YAML with sane defaults
sovereign validate <name>   Validate an agent YAML (offline — no server needed)
sovereign list              List all agents with live plasma temperatures
sovereign deploy <name>     Deploy an agent — heats its plasma domain
sovereign status            Full system status (VRAM, plasma, heartbeat, bus)
sovereign bench             Run the 'Drives the Car Better' memory benchmark
```

```bash
$ sovereign list

  Sovereign Agents  http://localhost:8008

  NAME                 ADAPTER        STATUS       PLASMA TEMPERATURE
  ──────────────────────────────────────────────────────────────────
  ● zola               base_model     deployed     ████████████░░░░░░░░ 287.4K
  ○ auditor            code_expert    idle         ░░░░░░░░░░░░░░░░░░░░   0.0K
```

---

## Architecture

```
sovereign-agents
├── sovereign/
│   ├── registry.py     AgentDefinition + AgentRuntimeState, fault-tolerant YAML load
│   ├── cli.py          `sovereign` command — offline + online modes
│   └── bus.py          P2P agent bus — HTTP signaling → HTP WebRTC data
├── agents/
│   ├── zola.agent.yaml
│   └── auditor.agent.yaml
└── tests/
    └── test_registry.py   21 tests — happy, error, edge, adversarial, hot-reload

Living Mind Cortex (engine dependency)
├── cortex/heatsink.py      Thermomorphic Memory Plasma — Newton's Law of Cooling
├── cortex/router.py        BiomechanicRouter — geometric + thermal MoE routing
├── cortex/adapter_lifecycle.py  VRAM eviction daemon
└── sovereign/bus.py        AgentBus — wired into SovereignHeartbeat.tick()
```

**Agents are not separate processes.** They are registered configurations dispatched through the Living Mind Cortex inference pipeline. `sovereign deploy` marks an agent as active and heats its plasma domain — it doesn't spawn anything. Logs are the server logs.

---

## Multi-Agent Bus

Sovereign Agents supports point-to-point agent sync via the **Holographic Transfer Protocol** — zero-serialization cognitive sync over WebRTC.

```bash
# Connect two Cortex nodes
sovereign-node-1$ sovereign bus connect http://node-2:8008

# Memories sync automatically across the HTP channel
# Peer list persists in local PostgreSQL — survives restarts
```

v1: point-to-point (2 nodes).
v2: N-peer mesh topology.

---

## Benchmarking Your Setup

```bash
sovereign bench
```

Runs the deterministic "Drives the Car Better" benchmark with a simulated clock — no `time.sleep()`, reproduces in 0.04s. Prints a full recall + noise + sublimation audit.

Tune your agents' thermal profiles against these numbers. The physics rewards access patterns that reflect real cognitive load, not recency alone.

---

## License

MIT. You own your agents, your memory, your hardware.

---

*Built the week Claude Managed Agents launched. The timing is not a coincidence.*
