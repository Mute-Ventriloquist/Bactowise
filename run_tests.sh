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
#   - CLI entry point (bactowise) is available
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
echo "  BactoWise — Test Suite"
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
    "bactowise"
    "bactowise.pipeline"
    "bactowise.models.config"
    "bactowise.utils.config_loader"
    "bactowise.runners.factory"
    "bactowise.runners.conda_runner"
    "bactowise.runners.docker_runner"
    "bactowise.cli"
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

if command -v bactowise &>/dev/null; then
    if bactowise --help &>/dev/null; then
        ok "bactowise --help works"
    else
        fail "bactowise --help failed"
    fi

    # bactowise init installs the bundled config to ~/.bactowise/config/.
    # We use --reset so the test is idempotent regardless of prior state.
    if bactowise init --reset &>/dev/null; then
        ok "bactowise init --reset works"
    else
        fail "bactowise init --reset failed"
    fi

    if bactowise validate &>/dev/null; then
        ok "bactowise validate works (reads installed config)"
    else
        fail "bactowise validate failed on installed config"
    fi
else
    # CLI not on PATH — fall back to running as a Python module
    # This happens in some conda build environments before entry points are linked
    if PYTHONPATH="$SCRIPT_DIR" $PYTHON -m bactowise.cli --help &>/dev/null; then
        ok "bactowise CLI works (via python -m)"
    else
        fail "bactowise CLI not found on PATH and python -m fallback also failed"
    fi
fi

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
