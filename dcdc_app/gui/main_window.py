"""Main application window – DC/DC Mission Console.

Implements the full GUI with:
- Left sidebar: connection, controls, setpoints (fixed width)
- Centre: live telemetry dashboard (compact cards)
- Right: faults, events, heartbeat (fixed width)
- Bottom tabs: Trends | DC Side | AC Grid | Power & Energy | Thermal | Raw CAN
"""

from __future__ import annotations

import time
from collections import deque
from functools import partial
from typing import Dict, List, Optional

import numpy as np

from PySide6.QtCore import QSize, Qt, QTimer, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

import pyqtgraph as pg

from dcdc_app.gui.backend import BackendWorker, RawCANFrame, TelemetrySnapshot
from dcdc_app.gui.theme import (
    ACCENT_CYAN,
    ACCENT_GREEN,
    ACCENT_ORANGE,
    ACCENT_RED,
    ACCENT_YELLOW,
    BG_CARD,
    BG_DARK,
    BG_PANEL,
    BORDER_SUBTLE,
    FONT_MONO,
    TEXT_DIM,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    pyqtgraph_theme,
)
from dcdc_app.gui.widgets import (
    HeartbeatIndicator,
    SectionLabel,
    StatusIndicator,
    TelemetryCard,
    ThreePhaseCard,
)
from dcdc_app.protocol import (
    CAN_BITRATE,
    MODE_PARAMS,
    PCS_DEFAULT_ADDR,
    WorkingMode,
)
from dcdc_app.can_iface import PCAN_CHANNELS


# ── Constants ────────────────────────────────────────────────────────────────

_PLOT_WINDOW_S = 60       # Seconds of data to show in trend plots
_PLOT_POINTS   = 300      # Data points in sliding window
_UI_REFRESH_HZ = 10       # Telemetry poll rate
_RAW_CAN_MAX   = 500      # Max rows in raw CAN table


class MainWindow(QMainWindow):
    """Aerospace-themed PCS Mission Console."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("DC/DC Mission Console — YSTECH PCS")
        self.setMinimumSize(1280, 800)
        self.resize(1500, 900)

        # Backend worker
        self._backend = BackendWorker()
        self._backend.telemetry_updated.connect(self._on_telemetry)
        self._backend.connection_state.connect(self._on_connection_state)
        self._backend.event_log.connect(self._on_event_log)
        self._backend.command_result.connect(self._on_command_result)
        self._backend.error_occurred.connect(self._on_error)

        # ── All trend data buffers ──
        self._trend_time: deque = deque(maxlen=_PLOT_POINTS)
        self._trend_start_time: float = time.time()

        # Trends (overview)
        self._buf_dc_voltage: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_dc_current: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_dc_power: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_inlet_temp: deque = deque(maxlen=_PLOT_POINTS)

        # DC Side
        self._buf_dc_voltage_hr: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_dc_current_hr: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_capacity: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_energy: deque = deque(maxlen=_PLOT_POINTS)

        # AC Grid
        self._buf_grid_v_u: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_grid_v_v: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_grid_v_w: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_grid_i_u: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_grid_i_v: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_grid_i_w: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_frequency: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_power_factor: deque = deque(maxlen=_PLOT_POINTS)

        # Power & Energy
        self._buf_active_power: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_reactive_power: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_apparent_power: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_load_active: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_load_reactive: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_load_apparent: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_phase_a: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_phase_b: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_phase_c: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_phase_a_q: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_phase_b_q: deque = deque(maxlen=_PLOT_POINTS)
        self._buf_phase_c_q: deque = deque(maxlen=_PLOT_POINTS)

        # Thermal
        self._buf_outlet_temp: deque = deque(maxlen=_PLOT_POINTS)

        # Raw CAN frame buffer
        self._raw_frames: deque = deque(maxlen=_RAW_CAN_MAX)

        # State
        self._connection_state = "disconnected"

        self._build_ui()
        self._setup_timers()

    # =====================================================================
    #  UI Construction
    # =====================================================================

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Header bar
        root_layout.addWidget(self._build_header())

        # Main body: sidebar | centre | faults  (fixed widths for sides)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        sidebar = self._build_sidebar()
        sidebar.setFixedWidth(230)
        body.addWidget(sidebar)

        body.addWidget(self._build_centre(), 1)  # stretches

        faults = self._build_faults_panel()
        faults.setFixedWidth(220)
        body.addWidget(faults)

        root_layout.addLayout(body, 1)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready — Connect to a PCS device or start simulator")

    # ── Header ───────────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("headerBar")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(12, 4, 12, 4)

        title = QLabel("DC/DC  MISSION  CONSOLE")
        title.setObjectName("headerTitle")
        layout.addWidget(title)

        layout.addStretch()

        self._status_indicator = StatusIndicator()
        layout.addWidget(self._status_indicator)

        return header

    # ── Left Sidebar ─────────────────────────────────────────────────────

    def _build_sidebar(self) -> QWidget:
        w = QWidget()
        w.setObjectName("sidebarPanel")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # ── Connection section ───────────────────────────────────────────
        layout.addWidget(SectionLabel("CONNECTION"))

        form = QFormLayout()
        form.setSpacing(4)

        self._cmb_interface = QComboBox()
        self._cmb_interface.addItems(["simulator", "pcan", "socketcan"])
        self._cmb_interface.currentTextChanged.connect(self._on_interface_changed)
        form.addRow("Interface", self._cmb_interface)

        self._cmb_channel = QComboBox()
        self._cmb_channel.addItems(PCAN_CHANNELS)
        self._cmb_channel.setCurrentText("PCAN_USBBUS1")
        form.addRow("Channel", self._cmb_channel)

        self._edt_bitrate = QLineEdit(str(CAN_BITRATE))
        form.addRow("Bitrate", self._edt_bitrate)

        self._edt_pcs_addr = QLineEdit(f"0x{PCS_DEFAULT_ADDR:02X}")
        form.addRow("PCS Addr", self._edt_pcs_addr)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self._btn_connect = QPushButton("Connect")
        self._btn_connect.setObjectName("btnConnect")
        self._btn_connect.clicked.connect(self._on_connect)
        btn_row.addWidget(self._btn_connect)

        self._btn_disconnect = QPushButton("Disconnect")
        self._btn_disconnect.setObjectName("btnDisconnect")
        self._btn_disconnect.setEnabled(False)
        self._btn_disconnect.clicked.connect(self._on_disconnect)
        btn_row.addWidget(self._btn_disconnect)

        layout.addLayout(btn_row)

        # ── Controls section ─────────────────────────────────────────────
        layout.addSpacing(4)
        layout.addWidget(SectionLabel("POWER CONTROL"))

        self._btn_enable = QPushButton("▶  ENABLE")
        self._btn_enable.setObjectName("btnEnable")
        self._btn_enable.setEnabled(False)
        self._btn_enable.clicked.connect(self._on_enable)
        layout.addWidget(self._btn_enable)

        self._btn_disable = QPushButton("■  DISABLE")
        self._btn_disable.setObjectName("btnDisable")
        self._btn_disable.setEnabled(False)
        self._btn_disable.clicked.connect(self._on_disable)
        layout.addWidget(self._btn_disable)

        self._btn_estop = QPushButton("⚠  EMERGENCY STOP")
        self._btn_estop.setObjectName("btnEmergencyStop")
        self._btn_estop.setEnabled(False)
        self._btn_estop.clicked.connect(self._on_emergency_stop)
        layout.addWidget(self._btn_estop)

        # ── Setpoints ────────────────────────────────────────────────────
        layout.addSpacing(4)
        layout.addWidget(SectionLabel("SETPOINTS"))

        sp_form = QFormLayout()
        sp_form.setSpacing(4)

        self._cmb_mode = QComboBox()
        for m in WorkingMode:
            self._cmb_mode.addItem(m.name, m.value)
        self._cmb_mode.currentIndexChanged.connect(self._on_mode_changed)
        sp_form.addRow("Mode", self._cmb_mode)

        self._spn_param1 = QDoubleSpinBox()
        self._spn_param1.setRange(-999999, 999999)
        self._spn_param1.setDecimals(3)
        self._lbl_param1 = QLabel("Param 1")
        sp_form.addRow(self._lbl_param1, self._spn_param1)

        self._spn_param2 = QDoubleSpinBox()
        self._spn_param2.setRange(-999999, 999999)
        self._spn_param2.setDecimals(3)
        self._lbl_param2 = QLabel("Param 2")
        sp_form.addRow(self._lbl_param2, self._spn_param2)

        self._spn_param3 = QDoubleSpinBox()
        self._spn_param3.setRange(-999999, 999999)
        self._spn_param3.setDecimals(3)
        self._lbl_param3 = QLabel("Param 3")
        sp_form.addRow(self._lbl_param3, self._spn_param3)

        self._spn_param4 = QDoubleSpinBox()
        self._spn_param4.setRange(-999999, 999999)
        self._spn_param4.setDecimals(3)
        self._lbl_param4 = QLabel("Param 4")
        sp_form.addRow(self._lbl_param4, self._spn_param4)

        layout.addLayout(sp_form)

        self._btn_apply = QPushButton("Apply Setpoints")
        self._btn_apply.setEnabled(False)
        self._btn_apply.clicked.connect(self._on_apply_setpoints)
        layout.addWidget(self._btn_apply)

        self._on_mode_changed()  # Initialize param labels

        layout.addStretch()

        scroll.setWidget(container)

        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        return w

    # ── Centre: Telemetry + Bottom Tabs ──────────────────────────────────

    def _build_centre(self) -> QWidget:
        centre = QWidget()
        layout = QVBoxLayout(centre)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Telemetry cards in a scroll area so they never push tabs off
        telem_scroll = QScrollArea()
        telem_scroll.setWidgetResizable(True)
        telem_scroll.setFrameShape(QFrame.Shape.NoFrame)
        telem_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        telem_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        telem_scroll.setMaximumHeight(260)
        telem_scroll.setWidget(self._build_telemetry_grid())
        layout.addWidget(telem_scroll)

        # Bottom tabs: Trends | DC Side | AC Grid | Power & Energy | Thermal | Raw CAN
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_trends_tab(), "Trends")
        self._tabs.addTab(self._build_dc_side_tab(), "DC Side")
        self._tabs.addTab(self._build_ac_grid_tab(), "AC Grid")
        self._tabs.addTab(self._build_power_tab(), "Power & Energy")
        self._tabs.addTab(self._build_thermal_tab(), "Thermal")
        self._tabs.addTab(self._build_raw_can_tab(), "Raw CAN")
        layout.addWidget(self._tabs, 1)

        return centre

    def _build_telemetry_grid(self) -> QWidget:
        container = QWidget()
        grid = QGridLayout(container)
        grid.setSpacing(4)
        grid.setContentsMargins(0, 0, 0, 0)

        # Row 0: Main DC readouts
        self._card_dc_voltage = TelemetryCard("DC Voltage", "V", ".1f")
        grid.addWidget(self._card_dc_voltage, 0, 0)

        self._card_dc_current = TelemetryCard("DC Current", "A", ".1f")
        grid.addWidget(self._card_dc_current, 0, 1)

        self._card_dc_power = TelemetryCard("DC Power", "kW", ".1f")
        grid.addWidget(self._card_dc_power, 0, 2)

        self._card_state = TelemetryCard("State", "", ".0f", large=True)
        grid.addWidget(self._card_state, 0, 3)

        # Row 1: Temps, freq, PF
        self._card_inlet_temp = TelemetryCard("Inlet Temp", "°C", ".1f", large=False)
        grid.addWidget(self._card_inlet_temp, 1, 0)

        self._card_outlet_temp = TelemetryCard("Outlet Temp", "°C", ".1f", large=False)
        grid.addWidget(self._card_outlet_temp, 1, 1)

        self._card_frequency = TelemetryCard("Frequency", "Hz", ".1f", large=False)
        grid.addWidget(self._card_frequency, 1, 2)

        self._card_pf = TelemetryCard("Power Factor", "", ".2f", large=False)
        grid.addWidget(self._card_pf, 1, 3)

        # Row 2: Power + 3-phase
        self._card_active_p = TelemetryCard("Active Power", "kW", ".1f", large=False)
        grid.addWidget(self._card_active_p, 2, 0)

        self._card_reactive_p = TelemetryCard("Reactive Power", "kVar", ".1f", large=False)
        grid.addWidget(self._card_reactive_p, 2, 1)

        self._card_grid_v = ThreePhaseCard("Grid Voltage", "V")
        grid.addWidget(self._card_grid_v, 2, 2)

        self._card_grid_i = ThreePhaseCard("Grid Current", "A")
        grid.addWidget(self._card_grid_i, 2, 3)

        # Row 3: capacity, energy, hi-res
        self._card_capacity = TelemetryCard("Capacity", "Ah", ".1f", large=False)
        grid.addWidget(self._card_capacity, 3, 0)

        self._card_energy = TelemetryCard("Energy", "Wh", ".1f", large=False)
        grid.addWidget(self._card_energy, 3, 1)

        self._card_hires_v = TelemetryCard("Hi-Res V", "V", ".3f", large=False)
        grid.addWidget(self._card_hires_v, 3, 2)

        self._card_hires_i = TelemetryCard("Hi-Res I", "A", ".3f", large=False)
        grid.addWidget(self._card_hires_i, 3, 3)

        return container

    # ── Tab: Trends (Overview) ───────────────────────────────────────────

    def _build_trends_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 2, 0, 0)

        theme = pyqtgraph_theme()
        pg.setConfigOptions(
            background=theme["background"],
            foreground=theme["foreground"],
            antialias=True,
        )
        colors = theme["accent_colors"]
        pw = 2  # pen width

        self._plot_trends = pg.GraphicsLayoutWidget()
        layout.addWidget(self._plot_trends)

        self._plot_v = self._plot_trends.addPlot(row=0, col=0, title="DC Voltage (V)")
        self._plot_v.showGrid(x=True, y=True, alpha=0.15)
        self._plot_v.setLabel("bottom", "Time", "s")
        self._curve_v = self._plot_v.plot(pen=pg.mkPen(colors[0], width=pw))

        self._plot_i = self._plot_trends.addPlot(row=0, col=1, title="DC Current (A)")
        self._plot_i.showGrid(x=True, y=True, alpha=0.15)
        self._plot_i.setLabel("bottom", "Time", "s")
        self._curve_i = self._plot_i.plot(pen=pg.mkPen(colors[1], width=pw))

        self._plot_p = self._plot_trends.addPlot(row=1, col=0, title="DC Power (kW)")
        self._plot_p.showGrid(x=True, y=True, alpha=0.15)
        self._plot_p.setLabel("bottom", "Time", "s")
        self._curve_p = self._plot_p.plot(pen=pg.mkPen(colors[2], width=pw))

        self._plot_t = self._plot_trends.addPlot(row=1, col=1, title="Inlet Temp (°C)")
        self._plot_t.showGrid(x=True, y=True, alpha=0.15)
        self._plot_t.setLabel("bottom", "Time", "s")
        self._curve_t = self._plot_t.plot(pen=pg.mkPen(colors[3], width=pw))

        return widget

    # ── Tab: DC Side ─────────────────────────────────────────────────────

    def _build_dc_side_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 2, 0, 0)

        colors = pyqtgraph_theme()["accent_colors"]
        pw = 2

        self._plot_dc = pg.GraphicsLayoutWidget()
        layout.addWidget(self._plot_dc)

        # Row 0: Voltage (standard + hi-res overlaid)
        p = self._plot_dc.addPlot(row=0, col=0, title="DC Voltage (V)")
        p.showGrid(x=True, y=True, alpha=0.15)
        p.setLabel("bottom", "Time", "s")
        p.addLegend(offset=(60, 10))
        self._dc_curve_v = p.plot(pen=pg.mkPen(colors[0], width=pw), name="Standard")
        self._dc_curve_v_hr = p.plot(pen=pg.mkPen(colors[4], width=pw, style=Qt.PenStyle.DashLine), name="Hi-Res")

        # Row 0: Current (standard + hi-res overlaid)
        p = self._plot_dc.addPlot(row=0, col=1, title="DC Current (A)")
        p.showGrid(x=True, y=True, alpha=0.15)
        p.setLabel("bottom", "Time", "s")
        p.addLegend(offset=(60, 10))
        self._dc_curve_i = p.plot(pen=pg.mkPen(colors[1], width=pw), name="Standard")
        self._dc_curve_i_hr = p.plot(pen=pg.mkPen(colors[4], width=pw, style=Qt.PenStyle.DashLine), name="Hi-Res")

        # Row 1: Power
        p = self._plot_dc.addPlot(row=1, col=0, title="DC Power (kW)")
        p.showGrid(x=True, y=True, alpha=0.15)
        p.setLabel("bottom", "Time", "s")
        self._dc_curve_power = p.plot(pen=pg.mkPen(colors[2], width=pw))

        # Row 1: Capacity & Energy (dual axis)
        p = self._plot_dc.addPlot(row=1, col=1, title="Capacity (Ah) & Energy (Wh)")
        p.showGrid(x=True, y=True, alpha=0.15)
        p.setLabel("bottom", "Time", "s")
        p.addLegend(offset=(60, 10))
        self._dc_curve_cap = p.plot(pen=pg.mkPen(colors[3], width=pw), name="Capacity Ah")
        self._dc_curve_energy = p.plot(pen=pg.mkPen(colors[6], width=pw), name="Energy Wh")

        return widget

    # ── Tab: AC Grid ─────────────────────────────────────────────────────

    def _build_ac_grid_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 2, 0, 0)

        colors = pyqtgraph_theme()["accent_colors"]
        pw = 2

        self._plot_ac = pg.GraphicsLayoutWidget()
        layout.addWidget(self._plot_ac)

        # Row 0: Grid Voltage U/V/W
        p = self._plot_ac.addPlot(row=0, col=0, title="Grid Voltage (V)")
        p.showGrid(x=True, y=True, alpha=0.15)
        p.setLabel("bottom", "Time", "s")
        p.addLegend(offset=(60, 10))
        self._ac_curve_vu = p.plot(pen=pg.mkPen(colors[0], width=pw), name="U")
        self._ac_curve_vv = p.plot(pen=pg.mkPen(colors[1], width=pw), name="V")
        self._ac_curve_vw = p.plot(pen=pg.mkPen(colors[2], width=pw), name="W")

        # Row 0: Grid Current U/V/W
        p = self._plot_ac.addPlot(row=0, col=1, title="Grid Current (A)")
        p.showGrid(x=True, y=True, alpha=0.15)
        p.setLabel("bottom", "Time", "s")
        p.addLegend(offset=(60, 10))
        self._ac_curve_iu = p.plot(pen=pg.mkPen(colors[0], width=pw), name="U")
        self._ac_curve_iv = p.plot(pen=pg.mkPen(colors[1], width=pw), name="V")
        self._ac_curve_iw = p.plot(pen=pg.mkPen(colors[2], width=pw), name="W")

        # Row 1: Frequency
        p = self._plot_ac.addPlot(row=1, col=0, title="Frequency (Hz)")
        p.showGrid(x=True, y=True, alpha=0.15)
        p.setLabel("bottom", "Time", "s")
        self._ac_curve_freq = p.plot(pen=pg.mkPen(colors[3], width=pw))

        # Row 1: Power Factor
        p = self._plot_ac.addPlot(row=1, col=1, title="Power Factor")
        p.showGrid(x=True, y=True, alpha=0.15)
        p.setLabel("bottom", "Time", "s")
        self._ac_curve_pf = p.plot(pen=pg.mkPen(colors[6], width=pw))

        return widget

    # ── Tab: Power & Energy ──────────────────────────────────────────────

    def _build_power_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 2, 0, 0)

        colors = pyqtgraph_theme()["accent_colors"]
        pw = 2

        self._plot_power = pg.GraphicsLayoutWidget()
        layout.addWidget(self._plot_power)

        # Row 0: System Power (Active/Reactive/Apparent)
        p = self._plot_power.addPlot(row=0, col=0, title="System Power")
        p.showGrid(x=True, y=True, alpha=0.15)
        p.setLabel("bottom", "Time", "s")
        p.addLegend(offset=(60, 10))
        self._pwr_curve_active = p.plot(pen=pg.mkPen(colors[0], width=pw), name="Active kW")
        self._pwr_curve_reactive = p.plot(pen=pg.mkPen(colors[2], width=pw), name="Reactive kVar")
        self._pwr_curve_apparent = p.plot(pen=pg.mkPen(colors[3], width=pw), name="Apparent kVA")

        # Row 0: Load Power (Active/Reactive/Apparent)
        p = self._plot_power.addPlot(row=0, col=1, title="Load Power")
        p.showGrid(x=True, y=True, alpha=0.15)
        p.setLabel("bottom", "Time", "s")
        p.addLegend(offset=(60, 10))
        self._pwr_curve_load_active = p.plot(pen=pg.mkPen(colors[0], width=pw), name="Active kW")
        self._pwr_curve_load_reactive = p.plot(pen=pg.mkPen(colors[2], width=pw), name="Reactive kVar")
        self._pwr_curve_load_apparent = p.plot(pen=pg.mkPen(colors[3], width=pw), name="Apparent kVA")

        # Row 1: Per-phase Active Power (A/B/C)
        p = self._plot_power.addPlot(row=1, col=0, title="Per-Phase Active Power (kW)")
        p.showGrid(x=True, y=True, alpha=0.15)
        p.setLabel("bottom", "Time", "s")
        p.addLegend(offset=(60, 10))
        self._pwr_curve_ph_a = p.plot(pen=pg.mkPen(colors[0], width=pw), name="Phase A")
        self._pwr_curve_ph_b = p.plot(pen=pg.mkPen(colors[1], width=pw), name="Phase B")
        self._pwr_curve_ph_c = p.plot(pen=pg.mkPen(colors[2], width=pw), name="Phase C")

        # Row 1: Per-phase Reactive Power (A/B/C)
        p = self._plot_power.addPlot(row=1, col=1, title="Per-Phase Reactive Power (kVar)")
        p.showGrid(x=True, y=True, alpha=0.15)
        p.setLabel("bottom", "Time", "s")
        p.addLegend(offset=(60, 10))
        self._pwr_curve_ph_a_q = p.plot(pen=pg.mkPen(colors[0], width=pw), name="Phase A")
        self._pwr_curve_ph_b_q = p.plot(pen=pg.mkPen(colors[1], width=pw), name="Phase B")
        self._pwr_curve_ph_c_q = p.plot(pen=pg.mkPen(colors[2], width=pw), name="Phase C")

        return widget

    # ── Tab: Thermal ─────────────────────────────────────────────────────

    def _build_thermal_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 2, 0, 0)

        colors = pyqtgraph_theme()["accent_colors"]
        pw = 2

        self._plot_thermal = pg.GraphicsLayoutWidget()
        layout.addWidget(self._plot_thermal)

        # Full-width: Inlet + Outlet overlaid
        p = self._plot_thermal.addPlot(row=0, col=0, title="Temperature (°C)")
        p.showGrid(x=True, y=True, alpha=0.15)
        p.setLabel("bottom", "Time", "s")
        p.addLegend(offset=(60, 10))
        self._therm_curve_inlet = p.plot(pen=pg.mkPen(colors[0], width=pw), name="Inlet")
        self._therm_curve_outlet = p.plot(pen=pg.mkPen(colors[5], width=pw), name="Outlet")

        # Add warning threshold lines
        p.addLine(y=60, pen=pg.mkPen(ACCENT_YELLOW, width=1, style=Qt.PenStyle.DashLine))
        p.addLine(y=80, pen=pg.mkPen(ACCENT_RED, width=1, style=Qt.PenStyle.DashLine))

        return widget

    # ── Tab: Raw CAN ─────────────────────────────────────────────────────

    def _build_raw_can_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 2, 0, 0)

        # Filter row
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:"))
        self._edt_can_filter = QLineEdit()
        self._edt_can_filter.setPlaceholderText("Type to filter by ID or name…")
        self._edt_can_filter.textChanged.connect(self._apply_can_filter)
        filter_row.addWidget(self._edt_can_filter)

        self._btn_clear_can = QPushButton("Clear")
        self._btn_clear_can.clicked.connect(self._clear_raw_can)
        filter_row.addWidget(self._btn_clear_can)

        self._lbl_can_count = QLabel("0 frames")
        self._lbl_can_count.setStyleSheet(f"color: {TEXT_DIM};")
        filter_row.addWidget(self._lbl_can_count)

        layout.addLayout(filter_row)

        self._tbl_raw = QTableWidget(0, 6)
        self._tbl_raw.setHorizontalHeaderLabels(
            ["Time", "Dir", "CAN ID", "DLC", "Data", "Message"]
        )
        header = self._tbl_raw.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self._tbl_raw.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tbl_raw.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._tbl_raw.verticalHeader().setVisible(False)
        layout.addWidget(self._tbl_raw)

        return widget

    # ── Right Panel: Faults + Events ─────────────────────────────────────

    def _build_faults_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("faultsPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Heartbeat indicator
        layout.addWidget(SectionLabel("HEARTBEAT"))
        self._heartbeat = HeartbeatIndicator()
        layout.addWidget(self._heartbeat)

        # CAN stats
        self._lbl_can_stats = QLabel("TX: 0  RX: 0  ERR: 0")
        self._lbl_can_stats.setStyleSheet(
            f"color: {TEXT_DIM}; font-family: {FONT_MONO}; font-size: 10px;"
        )
        layout.addWidget(self._lbl_can_stats)

        # Active faults
        layout.addSpacing(2)
        layout.addWidget(SectionLabel("ACTIVE FAULTS"))

        self._lbl_fault_code = QLabel("No fault")
        self._lbl_fault_code.setStyleSheet(
            f"color: {ACCENT_GREEN}; font-family: {FONT_MONO}; font-size: 12px; font-weight: 700;"
        )
        self._lbl_fault_code.setWordWrap(True)
        layout.addWidget(self._lbl_fault_code)

        self._btn_reset_faults = QPushButton("Reset Faults")
        self._btn_reset_faults.setEnabled(False)
        self._btn_reset_faults.clicked.connect(self._on_reset_faults)
        layout.addWidget(self._btn_reset_faults)

        # Event log
        layout.addSpacing(2)
        layout.addWidget(SectionLabel("EVENT LOG"))

        self._txt_events = QTextBrowser()
        self._txt_events.setOpenExternalLinks(False)
        layout.addWidget(self._txt_events, 1)

        return panel

    # =====================================================================
    #  Timers
    # =====================================================================

    def _setup_timers(self) -> None:
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(int(1000 / _UI_REFRESH_HZ))
        self._poll_timer.timeout.connect(self._backend.poll_telemetry)

        self._plot_timer = QTimer(self)
        self._plot_timer.setInterval(250)
        self._plot_timer.timeout.connect(self._update_plots)

    # =====================================================================
    #  Event handlers – Connection
    # =====================================================================

    def _on_interface_changed(self, text: str) -> None:
        is_sim = text == "simulator"
        self._cmb_channel.setEnabled(not is_sim)
        self._edt_bitrate.setEnabled(not is_sim)

    def _on_connect(self) -> None:
        iface = self._cmb_interface.currentText()
        simulated = iface == "simulator"
        channel = self._cmb_channel.currentText()
        try:
            bitrate = int(self._edt_bitrate.text())
        except ValueError:
            bitrate = CAN_BITRATE
        try:
            pcs_addr = int(self._edt_pcs_addr.text(), 0)
        except ValueError:
            pcs_addr = PCS_DEFAULT_ADDR

        self._backend.connect_pcs(
            interface="virtual" if simulated else iface,
            channel=channel,
            bitrate=bitrate,
            pcs_addr=pcs_addr,
            simulated=simulated,
        )

    def _on_disconnect(self) -> None:
        self._backend.disconnect_pcs()

    @Slot(str)
    def _on_connection_state(self, state: str) -> None:
        self._connection_state = state
        self._status_indicator.set_state(state)

        online = state == "online"
        self._btn_connect.setEnabled(not online)
        self._btn_disconnect.setEnabled(online)
        self._btn_enable.setEnabled(online)
        self._btn_disable.setEnabled(online)
        self._btn_estop.setEnabled(online)
        self._btn_apply.setEnabled(online)
        self._btn_reset_faults.setEnabled(online)

        if online:
            self._poll_timer.start()
            self._plot_timer.start()
            self._trend_start_time = time.time()
            self._status_bar.showMessage("Connected to PCS")
        else:
            self._poll_timer.stop()
            self._plot_timer.stop()
            self._status_bar.showMessage(f"Status: {state}")

    # =====================================================================
    #  Event handlers – Telemetry updates
    # =====================================================================

    @Slot(TelemetrySnapshot)
    def _on_telemetry(self, snap: TelemetrySnapshot) -> None:
        # DC readouts
        self._card_dc_voltage.set_value(snap.dc_voltage)
        self._card_dc_current.set_value(snap.dc_current)
        self._card_dc_power.set_value(snap.dc_power)

        # State card
        self._card_state.set_text(snap.running_state_name)
        if snap.is_fault:
            self._card_state.set_color(ACCENT_RED)
        elif snap.running_state_name in ("CONSTANT_VOLTAGE", "CONSTANT_CURRENT", "AC_CONSTANT_POWER"):
            self._card_state.set_color(ACCENT_GREEN)
        elif snap.running_state_name == "STANDBY":
            self._card_state.set_color(ACCENT_CYAN)
        else:
            self._card_state.set_color(TEXT_PRIMARY)

        # Temps
        self._card_inlet_temp.set_value(snap.inlet_temp)
        self._color_by_range(self._card_inlet_temp, snap.inlet_temp, 60, 80)
        self._card_outlet_temp.set_value(snap.outlet_temp)
        self._color_by_range(self._card_outlet_temp, snap.outlet_temp, 65, 85)

        # Frequency, PF
        self._card_frequency.set_value(snap.frequency)
        self._card_pf.set_value(snap.power_factor)

        # System power
        self._card_active_p.set_value(snap.active_power)
        self._card_reactive_p.set_value(snap.reactive_power)

        # 3-phase
        self._card_grid_v.set_values(snap.grid_v_u, snap.grid_v_v, snap.grid_v_w)
        self._card_grid_i.set_values(snap.grid_i_u, snap.grid_i_v, snap.grid_i_w)

        # Capacity / energy / hi-res
        self._card_capacity.set_value(snap.capacity_ah)
        self._card_energy.set_value(snap.energy_wh)
        self._card_hires_v.set_value(snap.dc_voltage_hr)
        self._card_hires_i.set_value(snap.dc_current_hr)

        # Heartbeat
        self._heartbeat.update_age(snap.seconds_since_rx)

        # CAN stats
        self._lbl_can_stats.setText(
            f"TX: {snap.tx_count}  RX: {snap.rx_count}  ERR: {snap.error_count}"
        )

        # Faults
        if snap.is_fault:
            self._lbl_fault_code.setText(
                f"⚠ FAULT 0x{snap.fault_code:04X}\n{snap.fault_description}"
            )
            self._lbl_fault_code.setStyleSheet(
                f"color: {ACCENT_RED}; font-family: {FONT_MONO}; "
                f"font-size: 12px; font-weight: 700;"
            )
        else:
            self._lbl_fault_code.setText("No fault")
            self._lbl_fault_code.setStyleSheet(
                f"color: {ACCENT_GREEN}; font-family: {FONT_MONO}; "
                f"font-size: 12px; font-weight: 700;"
            )

        # ── Fill ALL trend buffers ──
        t = snap.timestamp - self._trend_start_time
        self._trend_time.append(t)

        # Overview trends
        self._buf_dc_voltage.append(snap.dc_voltage)
        self._buf_dc_current.append(snap.dc_current)
        self._buf_dc_power.append(snap.dc_power)
        self._buf_inlet_temp.append(snap.inlet_temp)

        # DC Side
        self._buf_dc_voltage_hr.append(snap.dc_voltage_hr)
        self._buf_dc_current_hr.append(snap.dc_current_hr)
        self._buf_capacity.append(snap.capacity_ah)
        self._buf_energy.append(snap.energy_wh)

        # AC Grid
        self._buf_grid_v_u.append(snap.grid_v_u)
        self._buf_grid_v_v.append(snap.grid_v_v)
        self._buf_grid_v_w.append(snap.grid_v_w)
        self._buf_grid_i_u.append(snap.grid_i_u)
        self._buf_grid_i_v.append(snap.grid_i_v)
        self._buf_grid_i_w.append(snap.grid_i_w)
        self._buf_frequency.append(snap.frequency)
        self._buf_power_factor.append(snap.power_factor)

        # Power & Energy
        self._buf_active_power.append(snap.active_power)
        self._buf_reactive_power.append(snap.reactive_power)
        self._buf_apparent_power.append(snap.apparent_power)
        self._buf_load_active.append(snap.load_active_power)
        self._buf_load_reactive.append(snap.load_reactive_power)
        self._buf_load_apparent.append(snap.load_apparent_power)
        self._buf_phase_a.append(snap.phase_a_active)
        self._buf_phase_b.append(snap.phase_b_active)
        self._buf_phase_c.append(snap.phase_c_active)
        self._buf_phase_a_q.append(snap.phase_a_reactive)
        self._buf_phase_b_q.append(snap.phase_b_reactive)
        self._buf_phase_c_q.append(snap.phase_c_reactive)

        # Thermal
        self._buf_outlet_temp.append(snap.outlet_temp)

    @staticmethod
    def _color_by_range(card: TelemetryCard, val: float, warn: float, crit: float) -> None:
        if val >= crit:
            card.set_color(ACCENT_RED)
        elif val >= warn:
            card.set_color(ACCENT_YELLOW)
        else:
            card.reset_color()

    # =====================================================================
    #  Trend / Graph plots – update all curves
    # =====================================================================

    def _update_plots(self) -> None:
        if not self._trend_time:
            return
        t = np.array(self._trend_time)

        # Only update the currently visible tab to save CPU
        current_tab = self._tabs.currentIndex()

        if current_tab == 0:  # Trends (overview)
            self._curve_v.setData(t, np.array(self._buf_dc_voltage))
            self._curve_i.setData(t, np.array(self._buf_dc_current))
            self._curve_p.setData(t, np.array(self._buf_dc_power))
            self._curve_t.setData(t, np.array(self._buf_inlet_temp))

        elif current_tab == 1:  # DC Side
            self._dc_curve_v.setData(t, np.array(self._buf_dc_voltage))
            self._dc_curve_v_hr.setData(t, np.array(self._buf_dc_voltage_hr))
            self._dc_curve_i.setData(t, np.array(self._buf_dc_current))
            self._dc_curve_i_hr.setData(t, np.array(self._buf_dc_current_hr))
            self._dc_curve_power.setData(t, np.array(self._buf_dc_power))
            self._dc_curve_cap.setData(t, np.array(self._buf_capacity))
            self._dc_curve_energy.setData(t, np.array(self._buf_energy))

        elif current_tab == 2:  # AC Grid
            self._ac_curve_vu.setData(t, np.array(self._buf_grid_v_u))
            self._ac_curve_vv.setData(t, np.array(self._buf_grid_v_v))
            self._ac_curve_vw.setData(t, np.array(self._buf_grid_v_w))
            self._ac_curve_iu.setData(t, np.array(self._buf_grid_i_u))
            self._ac_curve_iv.setData(t, np.array(self._buf_grid_i_v))
            self._ac_curve_iw.setData(t, np.array(self._buf_grid_i_w))
            self._ac_curve_freq.setData(t, np.array(self._buf_frequency))
            self._ac_curve_pf.setData(t, np.array(self._buf_power_factor))

        elif current_tab == 3:  # Power & Energy
            self._pwr_curve_active.setData(t, np.array(self._buf_active_power))
            self._pwr_curve_reactive.setData(t, np.array(self._buf_reactive_power))
            self._pwr_curve_apparent.setData(t, np.array(self._buf_apparent_power))
            self._pwr_curve_load_active.setData(t, np.array(self._buf_load_active))
            self._pwr_curve_load_reactive.setData(t, np.array(self._buf_load_reactive))
            self._pwr_curve_load_apparent.setData(t, np.array(self._buf_load_apparent))
            self._pwr_curve_ph_a.setData(t, np.array(self._buf_phase_a))
            self._pwr_curve_ph_b.setData(t, np.array(self._buf_phase_b))
            self._pwr_curve_ph_c.setData(t, np.array(self._buf_phase_c))
            self._pwr_curve_ph_a_q.setData(t, np.array(self._buf_phase_a_q))
            self._pwr_curve_ph_b_q.setData(t, np.array(self._buf_phase_b_q))
            self._pwr_curve_ph_c_q.setData(t, np.array(self._buf_phase_c_q))

        elif current_tab == 4:  # Thermal
            self._therm_curve_inlet.setData(t, np.array(self._buf_inlet_temp))
            self._therm_curve_outlet.setData(t, np.array(self._buf_outlet_temp))

    # =====================================================================
    #  Raw CAN table
    # =====================================================================

    def _add_raw_frame(self, frame: RawCANFrame) -> None:
        row = self._tbl_raw.rowCount()
        if row >= _RAW_CAN_MAX:
            self._tbl_raw.removeRow(0)
            row = self._tbl_raw.rowCount()
        self._tbl_raw.insertRow(row)

        ts_str = time.strftime("%H:%M:%S", time.localtime(frame.timestamp))
        items = [
            ts_str,
            frame.direction,
            f"0x{frame.can_id:08X}",
            str(frame.dlc),
            frame.data_hex,
            frame.pf_name,
        ]
        for col, text in enumerate(items):
            item = QTableWidgetItem(text)
            if frame.direction == "TX":
                item.setForeground(pg.mkColor(ACCENT_CYAN))
            self._tbl_raw.setItem(row, col, item)

        self._tbl_raw.scrollToBottom()
        self._lbl_can_count.setText(f"{self._tbl_raw.rowCount()} frames")

    def _apply_can_filter(self, text: str) -> None:
        text_lower = text.lower()
        for row in range(self._tbl_raw.rowCount()):
            match = False
            if not text_lower:
                match = True
            else:
                for col in range(self._tbl_raw.columnCount()):
                    item = self._tbl_raw.item(row, col)
                    if item and text_lower in item.text().lower():
                        match = True
                        break
            self._tbl_raw.setRowHidden(row, not match)

    def _clear_raw_can(self) -> None:
        self._tbl_raw.setRowCount(0)
        self._lbl_can_count.setText("0 frames")

    # =====================================================================
    #  Event handlers – Commands
    # =====================================================================

    def _on_enable(self) -> None:
        reply = QMessageBox.question(
            self,
            "Enable PCS",
            "Are you sure you want to ENABLE the power stage?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._backend.cmd_enable()

    def _on_disable(self) -> None:
        self._backend.cmd_disable()

    def _on_emergency_stop(self) -> None:
        self._backend.cmd_disable()

    def _on_reset_faults(self) -> None:
        self._backend.cmd_reset_faults()

    def _on_apply_setpoints(self) -> None:
        mode_val = self._cmb_mode.currentData()
        try:
            mode = WorkingMode(mode_val)
        except ValueError:
            return

        params_def = MODE_PARAMS.get(mode_val, [])
        params: List[float] = []
        spinners = [self._spn_param1, self._spn_param2, self._spn_param3, self._spn_param4]
        for i, _ in enumerate(params_def):
            if i < len(spinners):
                params.append(spinners[i].value())

        if params:
            reply = QMessageBox.question(
                self,
                "Apply Setpoints",
                f"Set mode to {mode.name} with parameters:\n{params}\n\nProceed?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._backend.cmd_set_mode(mode, params)

    def _on_mode_changed(self) -> None:
        mode_val = self._cmb_mode.currentData()
        params_def = MODE_PARAMS.get(mode_val, [])

        labels = [self._lbl_param1, self._lbl_param2, self._lbl_param3, self._lbl_param4]
        spinners = [self._spn_param1, self._spn_param2, self._spn_param3, self._spn_param4]

        for i in range(4):
            if i < len(params_def):
                name, unit, resolution = params_def[i]
                labels[i].setText(f"{name} ({unit})")
                spinners[i].setEnabled(True)
                spinners[i].setDecimals(3)
                spinners[i].setSingleStep(resolution * 100)
                spinners[i].setVisible(True)
                labels[i].setVisible(True)
            else:
                spinners[i].setVisible(False)
                labels[i].setVisible(False)

    # =====================================================================
    #  Event handlers – Logging / Errors
    # =====================================================================

    @Slot(str)
    def _on_event_log(self, msg: str) -> None:
        self._txt_events.append(msg)

    @Slot(str, bool)
    def _on_command_result(self, cmd: str, success: bool) -> None:
        icon = "✓" if success else "✗"
        color = ACCENT_GREEN if success else ACCENT_RED
        ts = time.strftime("%H:%M:%S")
        self._txt_events.append(
            f'<span style="color:{color}">[{ts}] {icon} {cmd}: '
            f'{"OK" if success else "FAILED"}</span>'
        )

    @Slot(str)
    def _on_error(self, msg: str) -> None:
        self._status_bar.showMessage(f"Error: {msg}", 10000)
        ts = time.strftime("%H:%M:%S")
        self._txt_events.append(
            f'<span style="color:{ACCENT_RED}">[{ts}] ERROR: {msg}</span>'
        )

    # =====================================================================
    #  Cleanup
    # =====================================================================

    def closeEvent(self, event: QCloseEvent) -> None:
        self._poll_timer.stop()
        self._plot_timer.stop()
        self._backend.disconnect_pcs()
        super().closeEvent(event)
