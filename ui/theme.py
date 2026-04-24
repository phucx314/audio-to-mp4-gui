"""
ui/theme.py — UI design tokens.

Single source of truth for all colors, sizes, and status display data.
No business logic; no imports from core.
"""

APP_TITLE    = "Audio \u2192 MP4 Converter"
WIN_W, WIN_H = 980, 700
WIN_MIN_W    = 820
WIN_MIN_H    = 560

# ── Color palette ─────────────────────────────────────────────────────────────
ACCENT       = "#4f8ef7"
ACCENT_HOVER = "#3d7ae0"
ACCENT2      = "#7c3aed"
BG_CARD      = "#1e1e2e"
BG_MAIN      = "#13131f"
BG_DROP      = "#1a1a2e"
TEXT_DIM     = "#8888aa"

# ── Status display ────────────────────────────────────────────────────────────
STATUS_COLORS: dict[str, str] = {
    "pending":    "#8888aa",
    "processing": "#f7c948",
    "done":       "#4ade80",
    "skipped":    "#64748b",
    "error":      "#f87171",
}

STATUS_ICONS: dict[str, str] = {
    "pending":    "\u23f3",   # ⏳
    "processing": "\u2699",   # ⚙
    "done":       "\u2713",   # ✓
    "skipped":    "\u23ed",   # ⏭
    "error":      "\u2715",   # ✕
}
