"""Reusable GUI widgets for the aerospace-themed PCS console."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from dcdc_app.gui.theme import (
    ACCENT_CYAN,
    ACCENT_GREEN,
    ACCENT_ORANGE,
    ACCENT_RED,
    ACCENT_YELLOW,
    BG_CARD,
    BORDER_GLOW,
    BORDER_SUBTLE,
    FONT_MONO,
    TEXT_DIM,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)


class TelemetryCard(QFrame):
    """A single telemetry readout card with label, value, and unit."""

    def __init__(
        self,
        label: str,
        unit: str = "",
        fmt: str = ".1f",
        large: bool = True,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setProperty("class", "TelemetryCard")
        self._fmt = fmt
        self._value = 0.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(1)

        # Label
        self._label = QLabel(label.upper())
        self._label.setProperty("class", "CardLabel")
        self._label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._label)

        # Value + Unit row
        val_row = QHBoxLayout()
        val_row.setSpacing(3)
        val_row.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft)

        self._val_label = QLabel("—")
        cls = "CardValue" if large else "CardValueSmall"
        self._val_label.setProperty("class", cls)
        self._val_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        val_row.addWidget(self._val_label)

        self._unit_label = QLabel(unit)
        self._unit_label.setProperty("class", "CardUnit")
        self._unit_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        val_row.addWidget(self._unit_label)
        val_row.addStretch()

        layout.addLayout(val_row)

    def set_value(self, value: float) -> None:
        self._value = value
        txt = f"{value:{self._fmt}}"
        self._val_label.setText(txt)

    def set_text(self, text: str) -> None:
        self._val_label.setText(text)

    def set_color(self, color: str) -> None:
        self._val_label.setStyleSheet(f"color: {color};")

    def reset_color(self) -> None:
        self._val_label.setStyleSheet("")

    @property
    def value(self) -> float:
        return self._value


class StatusIndicator(QFrame):
    """A small round status LED with label."""

    _COLORS = {
        "disconnected": TEXT_DIM,
        "connecting": ACCENT_YELLOW,
        "online": ACCENT_GREEN,
        "error": ACCENT_RED,
    }

    _LABELS = {
        "disconnected": "OFFLINE",
        "connecting": "CONNECTING…",
        "online": "ONLINE",
        "error": "ERROR",
    }

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._led = QLabel()
        self._led.setFixedSize(12, 12)
        layout.addWidget(self._led)

        self._text = QLabel("OFFLINE")
        self._text.setObjectName("headerStatus")
        layout.addWidget(self._text)
        layout.addStretch()

        self.set_state("disconnected")

    def set_state(self, state: str) -> None:
        color = self._COLORS.get(state, TEXT_DIM)
        label = self._LABELS.get(state, state.upper())
        self._led.setStyleSheet(
            f"background-color: {color}; border-radius: 6px; "
            f"border: 1px solid {color};"
        )
        self._text.setText(label)
        self._text.setStyleSheet(f"color: {color};")


class SectionLabel(QLabel):
    """A styled section header label used in sidebar panels."""

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setObjectName("sectionLabel")


class HeartbeatIndicator(QFrame):
    """Shows a pulsing dot and message age for CAN heartbeat."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._dot = QLabel("●")
        self._dot.setStyleSheet(f"color: {TEXT_DIM}; font-size: 16px;")
        layout.addWidget(self._dot)

        self._age_label = QLabel("No data")
        self._age_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-family: {FONT_MONO}; font-size: 11px;"
        )
        layout.addWidget(self._age_label)
        layout.addStretch()

    def update_age(self, seconds: float) -> None:
        if seconds > 100:
            self._dot.setStyleSheet(f"color: {TEXT_DIM}; font-size: 16px;")
            self._age_label.setText("No data")
            return

        if seconds < 1.0:
            color = ACCENT_GREEN
            text = "< 1s"
        elif seconds < 3.0:
            color = ACCENT_YELLOW
            text = f"{seconds:.1f}s"
        else:
            color = ACCENT_RED
            text = f"{seconds:.1f}s  STALE"

        self._dot.setStyleSheet(f"color: {color}; font-size: 16px;")
        self._age_label.setText(f"Last RX: {text}")
        self._age_label.setStyleSheet(
            f"color: {color}; font-family: {FONT_MONO}; font-size: 11px;"
        )


class ThreePhaseCard(QFrame):
    """Compact 3-phase display (U/V/W) with label."""

    def __init__(self, label: str, unit: str = "V", parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("class", "TelemetryCard")
        self._unit = unit

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        header = QLabel(label.upper())
        header.setProperty("class", "CardLabel")
        layout.addWidget(header)

        grid = QGridLayout()
        grid.setSpacing(2)

        self._labels = {}
        self._values = {}
        for i, phase in enumerate(["U", "V", "W"]):
            ph_lbl = QLabel(phase)
            ph_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; font-weight: 700;")
            grid.addWidget(ph_lbl, i, 0)

            val = QLabel("—")
            val.setProperty("class", "CardValueSmall")
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(val, i, 1)

            u = QLabel(unit)
            u.setProperty("class", "CardUnit")
            grid.addWidget(u, i, 2)

            self._labels[phase] = ph_lbl
            self._values[phase] = val

        layout.addLayout(grid)

    def set_values(self, u: float, v: float, w: float, fmt: str = ".1f") -> None:
        self._values["U"].setText(f"{u:{fmt}}")
        self._values["V"].setText(f"{v:{fmt}}")
        self._values["W"].setText(f"{w:{fmt}}")
