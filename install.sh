#!/usr/bin/env bash
# install.sh — Sovereign Agents installer
# Sequence: PG preflight → DB + schema → pip install → start server → confirm
set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
fail() { echo -e "${RED}✗${NC} $*" >&2; exit 1; }
info() { echo -e "${DIM}  $*${NC}"; }
hdr()  { echo -e "\n${BOLD}$*${NC}"; }

SOVEREIGN_DB="${SOVEREIGN_DB:-sovereign_agents}"
SOVEREIGN_AGENTS_DIR="${SOVEREIGN_AGENTS_DIR:-./agents}"
CORTEX_DIR="${CORTEX_DIR:-../living-mind-cortex}"
SERVER_PORT="${SERVER_PORT:-8008}"
VENV_DIR=".venv"

hdr "Sovereign Agents — Installer"
echo -e "  ${DIM}Local-first managed agent platform${NC}\n"

# ─────────────────────────────────────────────────────────────────────────────
# Step 1: PostgreSQL preflight
# The #1 DX killer for local-first tools is a silent crash on missing PG.
# We exit immediately with a human-readable error — not a Python traceback.
# ─────────────────────────────────────────────────────────────────────────────
hdr "Step 1 — PostgreSQL preflight"

if ! command -v pg_isready &>/dev/null; then
    fail "pg_isready not found. Install PostgreSQL first.\n  Ubuntu/Debian: sudo apt install postgresql\n  macOS:        brew install postgresql"
fi

if ! pg_isready -q; then
    fail "PostgreSQL is not running.\n  Start it with:  sudo systemctl start postgresql\n  or:             brew services start postgresql"
fi
ok "PostgreSQL is running."

# Check if the database exists; offer to create it
if psql -lqt 2>/dev/null | cut -d\| -f1 | grep -qw "${SOVEREIGN_DB}"; then
    ok "Database '${SOVEREIGN_DB}' exists."
else
    warn "Database '${SOVEREIGN_DB}' not found."
    read -rp "  Create it now? [Y/n] " yn
    yn="${yn:-Y}"
    if [[ "$yn" =~ ^[Yy]$ ]]; then
        createdb "${SOVEREIGN_DB}" && ok "Database '${SOVEREIGN_DB}' created."
    else
        fail "Cannot proceed without a database. Set SOVEREIGN_DB to an existing database or create one."
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Seed schema
# Runs the Cortex schema.sql + bus_peers DDL.
# Idempotent — safe to re-run on an existing database.
# ─────────────────────────────────────────────────────────────────────────────
hdr "Step 2 — Seed schema"

SCHEMA_FILE="${CORTEX_DIR}/cortex/schema.sql"

if [[ ! -d "$CORTEX_DIR" ]]; then
    info "living-mind-cortex not found at ${CORTEX_DIR}. Cloning..."
    git clone https://github.com/NovasPlace/living-mind-cortex.git "$CORTEX_DIR" || fail "Failed to clone Cortex."
fi

if [[ ! -f "$SCHEMA_FILE" ]]; then
    fail "Cortex schema not found at ${SCHEMA_FILE}.\n  Verify CORTEX_DIR points to a valid living-mind-cortex repository."
fi

psql -d "${SOVEREIGN_DB}" -f "$SCHEMA_FILE" -q && ok "Cortex schema applied."

# bus_peers table — added by AgentBus.ensure_schema() at runtime but we seed
# it here too so the schema is fully represented at install time.
psql -d "${SOVEREIGN_DB}" -q <<'SQL'
CREATE TABLE IF NOT EXISTS bus_peers (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL UNIQUE,
    last_seen   TIMESTAMPTZ DEFAULT now(),
    status      TEXT DEFAULT 'active'
        CHECK (status IN ('active', 'unreachable', 'evicted'))
);
SQL
ok "bus_peers schema applied."

# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Python dependencies
# Uses a local venv to avoid polluting the system Python.
# ─────────────────────────────────────────────────────────────────────────────
hdr "Step 3 — Python dependencies"

if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
    info "Created virtual environment at ${VENV_DIR}/"
fi

# shellcheck source=/dev/null
source "${VENV_DIR}/bin/activate"

pip install -q --upgrade pip
pip install -q pyyaml httpx
pip install -q -e .

# Install Cortex dependencies too
if [[ -f "${CORTEX_DIR}/requirements.txt" ]]; then
    pip install -q -r "${CORTEX_DIR}/requirements.txt"
    ok "Cortex dependencies installed."
fi

ok "Python dependencies ready."

# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Seed example agents
# Only copies bundled agents if ./agents/ is empty — never overwrites.
# Bundled: zola, auditor, researcher (ship with the repo in agents/)
# ─────────────────────────────────────────────────────────────────────────────
hdr "Step 4 — Example agents"

mkdir -p "$SOVEREIGN_AGENTS_DIR"

# Count existing agent files
existing_agents=$(find "$SOVEREIGN_AGENTS_DIR" -name "*.agent.yaml" 2>/dev/null | wc -l)

if [[ "$existing_agents" -eq 0 ]]; then
    # First install — agents/ is empty, copy bundled examples
    # The repo ships agents/ with zola, auditor, researcher already in place,
    # so this is a no-op for fresh clones. It handles the edge case where
    # someone deleted the agents/ dir manually.
    for f in agents/zola.agent.yaml agents/auditor.agent.yaml agents/researcher.agent.yaml; do
        if [[ -f "$f" ]] && [[ "$SOVEREIGN_AGENTS_DIR" != "agents" ]]; then
            cp "$f" "${SOVEREIGN_AGENTS_DIR}/"
            info "Seeded $(basename $f)"
        fi
    done
fi

agent_count=$(find "$SOVEREIGN_AGENTS_DIR" -name "*.agent.yaml" | wc -l)
ok "${agent_count} agent(s) in ${SOVEREIGN_AGENTS_DIR}/"

if [[ "$agent_count" -eq 0 ]]; then
    fail "No agent YAML files found in ${SOVEREIGN_AGENTS_DIR}/. Cannot confirm install."
fi

# ─────────────────────────────────────────────────────────────────────────────
# Step 5: Start server + confirm
# Starts the Living Mind Cortex in the background, waits for it to come up,
# then runs `sovereign list` to confirm agents are loaded.
# ─────────────────────────────────────────────────────────────────────────────
hdr "Step 5 — Start server"

# Set env so the Cortex finds the sovereign-agents repo
export SOVEREIGN_AGENTS_PATH="$(pwd)"
export DATABASE_URL="postgresql://localhost/${SOVEREIGN_DB}"
export SOVEREIGN_LOCAL_URL="http://localhost:${SERVER_PORT}"

# Persist environment configuration
mkdir -p ~/.config/sovereign
cat <<EOF > ~/.config/sovereign/.env
SOVEREIGN_AGENTS_DIR="${SOVEREIGN_AGENTS_PATH}/agents"
SOVEREIGN_AGENTS_PATH="${SOVEREIGN_AGENTS_PATH}"
DATABASE_URL="${DATABASE_URL}"
SOVEREIGN_SERVER="${SOVEREIGN_LOCAL_URL}"
CORTEX_DIR="${CORTEX_DIR}"
EOF
info "Persisted configuration to ~/.config/sovereign/.env"

# Create logs dir BEFORE nohup
mkdir -p "${OLDPWD}/logs"

# Check if server is already running
if curl -sf "http://localhost:${SERVER_PORT}/status" &>/dev/null; then
    ok "Server already running at http://localhost:${SERVER_PORT}"
else
    info "Starting Living Mind Cortex..."
    pushd "$CORTEX_DIR" > /dev/null
    nohup python3 -m uvicorn api.main:app \
        --host 0.0.0.0 \
        --port "$SERVER_PORT" \
        --log-level warning \
        > "${OLDPWD}/logs/server.log" 2>&1 &
    SERVER_PID=$!
    popd > /dev/null

    echo -n "  Waiting for server"
    for i in $(seq 1 20); do
        sleep 1
        echo -n "."
        if curl -sf "http://localhost:${SERVER_PORT}/status" &>/dev/null; then
            echo ""
            ok "Server is up (PID ${SERVER_PID}) → http://localhost:${SERVER_PORT}"
            break
        fi
        if [[ $i -eq 20 ]]; then
            echo ""
            fail "Server did not start within 20s. Check logs/server.log"
        fi
    done
fi

# Confirm sovereign list returns agents
hdr "Confirming install"

python3 -m sovereign.cli list --server "http://localhost:${SERVER_PORT}" 2>/dev/null || \
    warn "sovereign list failed — server may still be warming up. Run: sovereign list"

echo ""
echo -e "${BOLD}${GREEN}Sovereign Agents is ready.${NC}"
echo ""
echo -e "  ${DIM}CLI commands:${NC}"
echo -e "    sovereign list              — view all agents"
echo -e "    sovereign deploy zola       — deploy your first agent"
echo -e "    sovereign status            — full system status"
echo -e "    sovereign bench             — run the memory benchmark"
echo ""
echo -e "  ${DIM}Docs:${NC} https://github.com/NovasPlace/sovereign-agents"
echo ""
