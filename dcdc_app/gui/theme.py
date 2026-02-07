"""Space / Aerospace mission-control QSS theme for the PCS GUI.

Dark background, high-contrast cyan/blue accents, subtle glow borders,
monospace telemetry digits, clean sans-serif labels.
"""

# ── Colour Palette ───────────────────────────────────────────────────────────
BG_DARK       = "#0a0e17"
BG_PANEL      = "#111827"
BG_CARD       = "#1a2234"
BG_INPUT      = "#0f1729"
BG_HOVER      = "#1e2d4a"
BG_PRESSED    = "#253550"

ACCENT_CYAN   = "#00e5ff"
ACCENT_BLUE   = "#2979ff"
ACCENT_PURPLE = "#7c4dff"
ACCENT_GREEN  = "#00e676"
ACCENT_YELLOW = "#ffd740"
ACCENT_RED    = "#ff1744"
ACCENT_ORANGE = "#ff9100"

TEXT_PRIMARY   = "#e0e6f0"
TEXT_SECONDARY = "#8899aa"
TEXT_DIM       = "#556677"
BORDER_SUBTLE  = "#1e2d4a"
BORDER_GLOW    = "#00e5ff44"

# ── Fonts ────────────────────────────────────────────────────────────────────
FONT_MONO     = "JetBrains Mono, Consolas, Courier New, monospace"
FONT_SANS     = "Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"

AEROSPACE_QSS = f"""
/* ─── Global ─────────────────────────────────────────────────────────────── */
QWidget {{
    background-color: {BG_DARK};
    color: {TEXT_PRIMARY};
    font-family: {FONT_SANS};
    font-size: 13px;
}}

QMainWindow {{
    background-color: {BG_DARK};
}}

/* ─── Header Bar ─────────────────────────────────────────────────────────── */
#headerBar {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {BG_PANEL}, stop:0.5 #0d1a2e, stop:1 {BG_PANEL});
    border-bottom: 1px solid {BORDER_GLOW};
    min-height: 32px;
    max-height: 38px;
    padding: 0 12px;
}}

#headerTitle {{
    color: {ACCENT_CYAN};
    font-family: {FONT_SANS};
    font-size: 18px;
    font-weight: 700;
    letter-spacing: 2px;
}}

#headerStatus {{
    font-family: {FONT_MONO};
    font-size: 12px;
    padding: 4px 12px;
    border-radius: 4px;
}}

/* ─── Sidebar / Panel ────────────────────────────────────────────────────── */
#sidebarPanel {{
    background-color: {BG_PANEL};
    border-right: 1px solid {BORDER_SUBTLE};
    min-width: 210px;
    max-width: 230px;
}}

#faultsPanel {{
    background-color: {BG_PANEL};
    border-left: 1px solid {BORDER_SUBTLE};
    min-width: 200px;
    max-width: 240px;
}}

/* ─── Telemetry Cards ────────────────────────────────────────────────────── */
.TelemetryCard {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 6px;
    padding: 6px;
}}

.TelemetryCard:hover {{
    border: 1px solid {BORDER_GLOW};
}}

.CardLabel {{
    color: {TEXT_SECONDARY};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
}}

.CardValue {{
    color: {TEXT_PRIMARY};
    font-family: {FONT_MONO};
    font-size: 20px;
    font-weight: 700;
}}

.CardUnit {{
    color: {TEXT_DIM};
    font-family: {FONT_MONO};
    font-size: 11px;
}}

.CardValueSmall {{
    color: {TEXT_PRIMARY};
    font-family: {FONT_MONO};
    font-size: 15px;
    font-weight: 600;
}}

/* ─── Buttons ────────────────────────────────────────────────────────────── */
QPushButton {{
    background-color: {BG_CARD};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
    font-size: 13px;
    min-height: 20px;
}}

QPushButton:hover {{
    background-color: {BG_HOVER};
    border-color: {ACCENT_CYAN};
}}

QPushButton:pressed {{
    background-color: {BG_PRESSED};
}}

QPushButton:disabled {{
    color: {TEXT_DIM};
    border-color: {BG_CARD};
}}

QPushButton#btnConnect {{
    background-color: #0d3b2e;
    border-color: {ACCENT_GREEN};
    color: {ACCENT_GREEN};
}}

QPushButton#btnConnect:hover {{
    background-color: #145239;
}}

QPushButton#btnDisconnect {{
    background-color: #3b0d1a;
    border-color: {ACCENT_RED};
    color: {ACCENT_RED};
}}

QPushButton#btnDisconnect:hover {{
    background-color: #52142a;
}}

QPushButton#btnEnable {{
    background-color: #0d3b2e;
    border-color: {ACCENT_GREEN};
    color: {ACCENT_GREEN};
    font-size: 13px;
    padding: 6px 12px;
}}

QPushButton#btnEnable:hover {{
    background-color: #145239;
}}

QPushButton#btnDisable {{
    background-color: #3b2900;
    border-color: {ACCENT_ORANGE};
    color: {ACCENT_ORANGE};
    font-size: 13px;
    padding: 6px 12px;
}}

QPushButton#btnDisable:hover {{
    background-color: #523a00;
}}

QPushButton#btnEmergencyStop {{
    background-color: #5c0a0a;
    border: 2px solid {ACCENT_RED};
    color: {ACCENT_RED};
    font-size: 13px;
    font-weight: 800;
    padding: 6px 12px;
    border-radius: 6px;
}}

QPushButton#btnEmergencyStop:hover {{
    background-color: #7a1010;
}}

/* ─── Inputs ─────────────────────────────────────────────────────────────── */
QComboBox {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 5px;
    padding: 6px 10px;
    font-size: 13px;
    min-height: 20px;
}}

QComboBox:hover {{
    border-color: {ACCENT_CYAN};
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {TEXT_SECONDARY};
    margin-right: 8px;
}}

QComboBox QAbstractItemView {{
    background-color: {BG_PANEL};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_SUBTLE};
    selection-background-color: {BG_HOVER};
    selection-color: {ACCENT_CYAN};
}}

QLineEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 5px;
    padding: 6px 10px;
    font-family: {FONT_MONO};
    font-size: 13px;
    min-height: 20px;
}}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {ACCENT_CYAN};
}}

/* ─── Labels ─────────────────────────────────────────────────────────────── */
QLabel {{
    background: transparent;
    border: none;
}}

QLabel#sectionLabel {{
    color: {ACCENT_CYAN};
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 1.5px;
    padding: 8px 0 4px 0;
    border-bottom: 1px solid {BORDER_SUBTLE};
}}

/* ─── Tab Widget ─────────────────────────────────────────────────────────── */
QTabWidget::pane {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER_SUBTLE};
    border-top: none;
    border-radius: 0 0 6px 6px;
}}

QTabBar::tab {{
    background-color: {BG_CARD};
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER_SUBTLE};
    border-bottom: none;
    padding: 8px 20px;
    margin-right: 2px;
    border-radius: 6px 6px 0 0;
    font-weight: 600;
}}

QTabBar::tab:selected {{
    background-color: {BG_PANEL};
    color: {ACCENT_CYAN};
    border-bottom: 2px solid {ACCENT_CYAN};
}}

QTabBar::tab:hover:!selected {{
    background-color: {BG_HOVER};
    color: {TEXT_PRIMARY};
}}

/* ─── Table (Raw CAN) ───────────────────────────────────────────────────── */
QTableWidget, QTableView {{
    background-color: {BG_DARK};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_SUBTLE};
    gridline-color: {BORDER_SUBTLE};
    font-family: {FONT_MONO};
    font-size: 12px;
    selection-background-color: {BG_HOVER};
    selection-color: {ACCENT_CYAN};
}}

QTableWidget::item {{
    padding: 3px 6px;
}}

QHeaderView::section {{
    background-color: {BG_CARD};
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER_SUBTLE};
    padding: 5px 8px;
    font-weight: 700;
    font-size: 11px;
    text-transform: uppercase;
}}

/* ─── Scrollbars ─────────────────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: {BG_DARK};
    width: 10px;
    margin: 0;
    border: none;
}}

QScrollBar::handle:vertical {{
    background: {BORDER_SUBTLE};
    min-height: 30px;
    border-radius: 5px;
}}

QScrollBar::handle:vertical:hover {{
    background: {TEXT_DIM};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    background: {BG_DARK};
    height: 10px;
    border: none;
}}

QScrollBar::handle:horizontal {{
    background: {BORDER_SUBTLE};
    min-width: 30px;
    border-radius: 5px;
}}

/* ─── Text Browser (Event Log) ───────────────────────────────────────────── */
QTextBrowser, QPlainTextEdit {{
    background-color: {BG_DARK};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 4px;
    font-family: {FONT_MONO};
    font-size: 12px;
    padding: 4px;
}}

/* ─── Group Boxes ────────────────────────────────────────────────────────── */
QGroupBox {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 8px;
    margin-top: 16px;
    padding-top: 20px;
    font-weight: 700;
    color: {TEXT_SECONDARY};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 4px 12px;
    color: {ACCENT_CYAN};
    font-size: 12px;
    letter-spacing: 1px;
}}

/* ─── Status bar ─────────────────────────────────────────────────────────── */
QStatusBar {{
    background-color: {BG_PANEL};
    color: {TEXT_SECONDARY};
    border-top: 1px solid {BORDER_SUBTLE};
    font-family: {FONT_MONO};
    font-size: 11px;
}}

/* ─── Tooltips ───────────────────────────────────────────────────────────── */
QToolTip {{
    background-color: {BG_CARD};
    color: {TEXT_PRIMARY};
    border: 1px solid {ACCENT_CYAN};
    border-radius: 4px;
    padding: 6px;
    font-size: 12px;
}}

/* ─── Splitter ───────────────────────────────────────────────────────────── */
QSplitter::handle {{
    background-color: {BORDER_SUBTLE};
}}

QSplitter::handle:horizontal {{
    width: 2px;
}}

QSplitter::handle:vertical {{
    height: 2px;
}}

/* ─── Check Box ──────────────────────────────────────────────────────────── */
QCheckBox {{
    color: {TEXT_PRIMARY};
    spacing: 8px;
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 3px;
    border: 1px solid {BORDER_SUBTLE};
    background-color: {BG_INPUT};
}}

QCheckBox::indicator:checked {{
    background-color: {ACCENT_CYAN};
    border-color: {ACCENT_CYAN};
}}
"""


def pyqtgraph_theme() -> dict:
    """Return configuration dict for pyqtgraph plot styling."""
    return {
        "background": BG_PANEL,
        "foreground": TEXT_SECONDARY,
        "accent_colors": [ACCENT_CYAN, ACCENT_GREEN, ACCENT_YELLOW, ACCENT_PURPLE,
                          ACCENT_ORANGE, ACCENT_RED, ACCENT_BLUE, "#ff80ab"],
    }
