"""
bactowise/utils/console.py

Shared Rich console and print helpers for consistent, coloured CLI output.

All pipeline and runner output should go through this module so that:
  - Tool name prefixes are always the same colour per tool
  - Stage headings are visually distinct from body text
  - Warnings, errors, and success lines share a consistent palette

Usage:
    from bactowise.utils.console import console, cprint_tool, stage_rule

    cprint_tool("bakta", "Starting annotation inside Singularity...")
    stage_rule(2, ["prokka", "bakta", "pgap"])
    console.print("[success]✓  All preflight checks passed.[/success]")
"""

from __future__ import annotations

from rich.console import Console
from rich.theme import Theme

# ── Per-tool colours ──────────────────────────────────────────────────────────
# Each tool has a fixed colour so its output is instantly recognisable across
# a parallel run where lines from different tools are interleaved.

_TOOL_COLOURS: dict[str, str] = {
    "checkm":        "steel_blue1",
    "prokka":        "bright_blue",
    "bakta":         "medium_purple1",
    "pgap":          "hot_pink",
    "consensus":     "deep_sky_blue1",
    "amrfinderplus": "orange3",
    "phigaro":       "medium_spring_green",
}
_DEFAULT_TOOL_COLOUR = "bright_blue"


def tool_colour(tool_name: str) -> str:
    """Return the Rich colour string for a given tool name."""
    return _TOOL_COLOURS.get(tool_name.lower(), _DEFAULT_TOOL_COLOUR)


# ── Shared console ────────────────────────────────────────────────────────────

_theme = Theme({
    "success":    "bold green",
    "warning":    "bold yellow",
    "error":      "bold red",
    "user_error": "bold red",
    "skip":       "white",
    "bypass":     "bold cyan",
    "info":       "bright_blue",
    "muted":      "white",        # paths and commands — visible but not bold
    "label":      "bold white",   # key labels like 'Command:', 'Logging to:'
})

console = Console(theme=_theme, highlight=False)


# ── Helper functions ──────────────────────────────────────────────────────────

def cprint_tool(tool_name: str, message: str) -> None:
    """
    Print a line prefixed with a coloured [tool_name] tag.

    Example output (in colour):
        [bakta] Starting annotation inside Singularity...
    """
    colour = tool_colour(tool_name)
    console.print(f"[bold {colour}]\\[{tool_name}][/bold {colour}] {message}")


def stage_rule(stage_num: int, tool_names: list[str]) -> None:
    """
    Print a full-width horizontal rule with the stage number and tool names
    centred inside it. Visually separates pipeline stages.

    Example output:
        ────────────────── Stage 1: checkm ──────────────────
    """
    label = f"  Stage {stage_num}: {', '.join(tool_names)}  "
    console.print()
    console.rule(f"[bold white]{label}[/bold white]", style="magenta")
    console.print()
