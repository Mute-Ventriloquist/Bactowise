#!/bin/bash
# run_tests.sh
#
# Can be run in two ways:
#   1. Automatically by conda build (called from meta.yaml test block)
#   2. Manually at any time from the repo root:
#        bash run_tests.sh
#
# What it checks:
#   - Python imports all load correctly
#   - CLI entry point (genoflow) is available
#   - Config validation command works
#   - All unit tests pass (mocks Docker + tools, no real installs needed)

set -euo pipefail

# ── Helpers ──────────────────────────────────────────────────────────────────

PASS=0
FAIL=0
ERRORS=()

ok()   { echo "  ✓  $1"; PASS=$((PASS + 1)); }
fail() { echo "  ✗  $1"; FAIL=$((FAIL + 1)); ERRORS+=("$1"); }

header() {
    echo ""
    echo "────────────────────────────────────────────"
    echo "  $1"
    echo "────────────────────────────────────────────"
}

# ── Locate repo root (works whether called from root or elsewhere) ─────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Check Python is available ─────────────────────────────────────────────

PYTHON=$(command -v python3 || command -v python || true)
if [ -z "$PYTHON" ]; then
    echo "✗ Python not found. Cannot run tests."
    exit 1
fi

echo ""
echo "════════════════════════════════════════════"
echo "  Genoflow — Test Suite"
echo "  Python: $($PYTHON --version)"
echo "  Dir:    $SCRIPT_DIR"
echo "════════════════════════════════════════════"

# ── 1. Dependency check ───────────────────────────────────────────────────

header "1/4  Dependency Check"

for pkg in pydantic typer yaml docker; do
    if $PYTHON -c "import $pkg" 2>/dev/null; then
        ok "$pkg is importable"
    else
        fail "$pkg is NOT installed  →  pip install $pkg"
    fi
done

# ── 2. Package import check ───────────────────────────────────────────────

header "2/4  Package Import Check"

imports=(
    "genoflow"
    "genoflow.pipeline"
    "genoflow.models.config"
    "genoflow.utils.config_loader"
    "genoflow.runners.factory"
    "genoflow.runners.conda_runner"
    "genoflow.runners.docker_runner"
    "genoflow.cli"
)

for mod in "${imports[@]}"; do
    if PYTHONPATH="$SCRIPT_DIR" $PYTHON -c "import $mod" 2>/dev/null; then
        ok "$mod"
    else
        fail "$mod  (import failed)"
    fi
done

# ── 3. CLI entry point ────────────────────────────────────────────────────

header "3/4  CLI Check"

# Write a minimal test config that has NO database paths.
# This avoids the chicken-and-egg problem: the database only exists after
# the package is installed and the user runs bakta_db download.
# Database path checks are intentionally deferred to runtime (genoflow run).
TEST_CONFIG=$(mktemp /tmp/genoflow_test_XXXXXX.yaml)
cat > "$TEST_CONFIG" << 'YAML'
tools:
  - name: prokka
    version: "1.14.6"
    runtime: conda
    params:
      genus: "Mycoplasma"
      species: "genitalium"
  - name: bakta
    version: "1.9.3"
    runtime: docker
    image: "oschwengers/bakta:1.9.3"
    params: {}
output_dir: "/tmp/genoflow_test_output"
threads: 4
YAML

if command -v genoflow &>/dev/null; then
    if genoflow --help &>/dev/null; then
        ok "genoflow --help works"
    else
        fail "genoflow --help failed"
    fi

    if genoflow validate -c "$TEST_CONFIG" &>/dev/null; then
        ok "genoflow validate works (no database path required at build time)"
    else
        fail "genoflow validate failed on minimal test config"
    fi
else
    # CLI not on PATH — fall back to running as a Python module
    # This happens in some conda build environments before entry points are linked
    if PYTHONPATH="$SCRIPT_DIR" $PYTHON -m genoflow.cli --help &>/dev/null; then
        ok "genoflow CLI works (via python -m)"
    else
        fail "genoflow CLI not found on PATH and python -m fallback also failed"
    fi
fi

rm -f "$TEST_CONFIG"   # clean up temp config

# ── 4. Unit tests ─────────────────────────────────────────────────────────

header "4/4  Unit Tests"

if command -v pytest &>/dev/null; then
    echo ""
    # -p no:warnings keeps output clean
    # -q for quiet, --tb=short for compact tracebacks
    if PYTHONPATH="$SCRIPT_DIR" pytest tests/ -q --tb=short -p no:warnings; then
        ok "All pytest tests passed"
    else
        fail "pytest tests failed  (see output above)"
    fi
else
    echo "  pytest not found — running tests via Python directly..."
    if PYTHONPATH="$SCRIPT_DIR" $PYTHON -m pytest tests/ -q --tb=short -p no:warnings 2>/dev/null; then
        ok "All tests passed (via python -m pytest)"
    else
        fail "Tests failed or pytest unavailable"
    fi
fi

# ── Summary ───────────────────────────────────────────────────────────────

echo ""
echo "════════════════════════════════════════════"
echo "  Results: $PASS passed, $FAIL failed"
echo "════════════════════════════════════════════"

if [ ${#ERRORS[@]} -gt 0 ]; then
    echo ""
    echo "  Failed checks:"
    for err in "${ERRORS[@]}"; do
        echo "    ✗  $err"
    done
    echo ""
    exit 1
fi

echo ""
echo "  All checks passed ✓"
echo ""
