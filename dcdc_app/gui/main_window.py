"""Main application window – DC/DC Mission Console.

Implements the full GUI with:
- Left sidebar: connection, controls, setpoints
- Centre: live telemetry dashboard
- Right: faults, events, heartbeat
- Bottom: trend plots + raw CAN table
"""

from __future__ import annotations

import time
from collections import deque
from functools import partial
from typing import List, Optional

import numpy as np

from PySide6.QtCore import QMetaObject, QSize, Qt, QTimer, Q_ARG, Slot
from PySide6.QtGui import QAction, QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
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
    FAULT_CODES,
    MODE_PARAMS,
    PCS_DEFAULT_ADDR,
    WorkingMode,
    fault_description,
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

        # Backend worker (lives in main thread for simplicity; CAN I/O is in
        # controller's own threads – the worker just wraps calls).
        self._backend = BackendWorker()
        self._backend.telemetry_updated.connect(self._on_telemetry)
        self._backend.connection_state.connect(self._on_connection_state)
        self._backend.event_log.connect(self._on_event_log)
        self._backend.command_result.connect(self._on_command_result)
        self._backend.error_occurred.connect(self._on_error)

        # Trend data buffers
        self._trend_time: deque = deque(maxlen=_PLOT_POINTS)
        self._trend_voltage: deque = deque(maxlen=_PLOT_POINTS)
        self._trend_current: deque = deque(maxlen=_PLOT_POINTS)
        self._trend_power: deque = deque(maxlen=_PLOT_POINTS)
        self._trend_temp: deque = deque(maxlen=_PLOT_POINTS)
        self._trend_start_time: float = time.time()

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
        # ── Central widget ───────────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Header bar
        root_layout.addWidget(self._build_header())

        # Main body: sidebar | centre | faults
        body_splitter = QSplitter(Qt.Orientation.Horizontal)

        body_splitter.addWidget(self._build_sidebar())
        body_splitter.addWidget(self._build_centre())
        body_splitter.addWidget(self._build_faults_panel())

        body_splitter.setStretchFactor(0, 0)  # sidebar fixed
        body_splitter.setStretchFactor(1, 1)  # centre stretches
        body_splitter.setStretchFactor(2, 0)  # faults fixed
        body_splitter.setSizes([260, 800, 290])

        root_layout.addWidget(body_splitter, 1)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready — Connect to a PCS device or start simulator")

    # ── Header ───────────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("headerBar")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 8, 16, 8)

        title = QLabel("DC/DC  MISSION  CONSOLE")
        title.setObjectName("headerTitle")
        layout.addWidget(title)

        layout.addStretch()

        self._status_indicator = StatusIndicator()
        layout.addWidget(self._status_indicator)

        return header

    # ── Left Sidebar ─────────────────────────────────────────────────────

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebarPanel")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        # ── Connection section ───────────────────────────────────────────
        layout.addWidget(SectionLabel("CONNECTION"))

        form = QFormLayout()
        form.setSpacing(6)

        self._cmb_interface = QComboBox()
        self._cmb_interface.addItems(["simulator", "pcan", "socketcan"])
        self._cmb_interface.currentTextChanged.connect(self._on_interface_changed)
        form.addRow("Interface", self._cmb_interface)

        self._cmb_channel = QComboBox()
        self._cmb_channel.addItems(PCAN_CHANNELS)
        self._cmb_channel.setCurrentText("PCAN_USBBUS1")
        form.addRow("Channel", self._cmb_channel)

        self._edt_bitrate = QLineEdit(str(CAN_BITRATE))
        self._edt_bitrate.setToolTip("CAN bitrate (bps). Protocol default: 250000")
        form.addRow("Bitrate", self._edt_bitrate)

        self._edt_pcs_addr = QLineEdit(f"0x{PCS_DEFAULT_ADDR:02X}")
        self._edt_pcs_addr.setToolTip("PCS CAN address (hex). Default: 0xFA")
        form.addRow("PCS Addr", self._edt_pcs_addr)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
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
        layout.addSpacing(8)
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
        layout.addSpacing(8)
        layout.addWidget(SectionLabel("SETPOINTS"))

        sp_form = QFormLayout()
        sp_form.setSpacing(6)

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

        wrapper = QVBoxLayout()
        wrapper.setContentsMargins(0, 0, 0, 0)
        w = QWidget()
        w.setObjectName("sidebarPanel")
        w.setLayout(wrapper)
        wrapper.addWidget(scroll)
        return w

    # ── Centre: Telemetry + Bottom Tabs ──────────────────────────────────

    def _build_centre(self) -> QWidget:
        centre = QWidget()
        layout = QVBoxLayout(centre)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Telemetry cards grid
        layout.addWidget(self._build_telemetry_grid())

        # Bottom tabs: Trends | Raw CAN
        tabs = QTabWidget()
        tabs.addTab(self._build_trends_tab(), "Trends")
        tabs.addTab(self._build_raw_can_tab(), "Raw CAN")
        layout.addWidget(tabs, 1)

        return centre

    def _build_telemetry_grid(self) -> QWidget:
        container = QWidget()
        grid = QGridLayout(container)
        grid.setSpacing(8)
        grid.setContentsMargins(0, 0, 0, 0)

        # Row 0: Main DC readouts (large)
        self._card_dc_voltage = TelemetryCard("DC Voltage", "V", ".1f")
        grid.addWidget(self._card_dc_voltage, 0, 0)

        self._card_dc_current = TelemetryCard("DC Current", "A", ".1f")
        grid.addWidget(self._card_dc_current, 0, 1)

        self._card_dc_power = TelemetryCard("DC Power", "kW", ".1f")
        grid.addWidget(self._card_dc_power, 0, 2)

        self._card_state = TelemetryCard("State", "", ".0f", large=True)
        grid.addWidget(self._card_state, 0, 3)

        # Row 1: Temperatures, frequency, power factor, energy
        self._card_inlet_temp = TelemetryCard("Inlet Temp", "°C", ".1f", large=False)
        grid.addWidget(self._card_inlet_temp, 1, 0)

        self._card_outlet_temp = TelemetryCard("Outlet Temp", "°C", ".1f", large=False)
        grid.addWidget(self._card_outlet_temp, 1, 1)

        self._card_frequency = TelemetryCard("Frequency", "Hz", ".1f", large=False)
        grid.addWidget(self._card_frequency, 1, 2)

        self._card_pf = TelemetryCard("Power Factor", "", ".2f", large=False)
        grid.addWidget(self._card_pf, 1, 3)

        # Row 2: System power + 3-phase
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

    # ── Trends tab ───────────────────────────────────────────────────────

    def _build_trends_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 4, 0, 0)

        theme = pyqtgraph_theme()
        pg.setConfigOptions(
            background=theme["background"],
            foreground=theme["foreground"],
            antialias=True,
        )

        self._plot_widget = pg.GraphicsLayoutWidget()
        layout.addWidget(self._plot_widget)

        colors = theme["accent_colors"]
        pen_width = 2

        # Voltage plot
        self._plot_v = self._plot_widget.addPlot(row=0, col=0, title="DC Voltage (V)")
        self._plot_v.showGrid(x=True, y=True, alpha=0.15)
        self._plot_v.setLabel("bottom", "Time", "s")
        self._curve_v = self._plot_v.plot(pen=pg.mkPen(colors[0], width=pen_width))

        # Current plot
        self._plot_i = self._plot_widget.addPlot(row=0, col=1, title="DC Current (A)")
        self._plot_i.showGrid(x=True, y=True, alpha=0.15)
        self._plot_i.setLabel("bottom", "Time", "s")
        self._curve_i = self._plot_i.plot(pen=pg.mkPen(colors[1], width=pen_width))

        # Power plot
        self._plot_p = self._plot_widget.addPlot(row=1, col=0, title="DC Power (kW)")
        self._plot_p.showGrid(x=True, y=True, alpha=0.15)
        self._plot_p.setLabel("bottom", "Time", "s")
        self._curve_p = self._plot_p.plot(pen=pg.mkPen(colors[2], width=pen_width))

        # Temperature plot
        self._plot_t = self._plot_widget.addPlot(row=1, col=1, title="Inlet Temp (°C)")
        self._plot_t.showGrid(x=True, y=True, alpha=0.15)
        self._plot_t.setLabel("bottom", "Time", "s")
        self._curve_t = self._plot_t.plot(pen=pg.mkPen(colors[3], width=pen_width))

        return widget

    # ── Raw CAN tab ──────────────────────────────────────────────────────

    def _build_raw_can_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 4, 0, 0)

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
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Heartbeat indicator
        layout.addWidget(SectionLabel("HEARTBEAT"))
        self._heartbeat = HeartbeatIndicator()
        layout.addWidget(self._heartbeat)

        # CAN stats
        self._lbl_can_stats = QLabel("TX: 0  RX: 0  ERR: 0")
        self._lbl_can_stats.setStyleSheet(
            f"color: {TEXT_DIM}; font-family: {FONT_MONO}; font-size: 11px;"
        )
        layout.addWidget(self._lbl_can_stats)

        # Active faults
        layout.addSpacing(4)
        layout.addWidget(SectionLabel("ACTIVE FAULTS"))

        self._lbl_fault_code = QLabel("No fault")
        self._lbl_fault_code.setStyleSheet(
            f"color: {ACCENT_GREEN}; font-family: {FONT_MONO}; font-size: 14px; font-weight: 700;"
        )
        self._lbl_fault_code.setWordWrap(True)
        layout.addWidget(self._lbl_fault_code)

        self._btn_reset_faults = QPushButton("Reset Faults")
        self._btn_reset_faults.setEnabled(False)
        self._btn_reset_faults.clicked.connect(self._on_reset_faults)
        layout.addWidget(self._btn_reset_faults)

        # Event log
        layout.addSpacing(4)
        layout.addWidget(SectionLabel("EVENT LOG"))

        self._txt_events = QTextBrowser()
        self._txt_events.setOpenExternalLinks(False)
        layout.addWidget(self._txt_events, 1)

        return panel

    # =====================================================================
    #  Timers
    # =====================================================================

    def _setup_timers(self) -> None:
        # Poll telemetry from backend at ~10 Hz
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(int(1000 / _UI_REFRESH_HZ))
        self._poll_timer.timeout.connect(self._backend.poll_telemetry)
        # Don't start until connected

        # Trend plot update at 4 Hz (lighter than telemetry)
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
                f"font-size: 14px; font-weight: 700;"
            )
        else:
            self._lbl_fault_code.setText("No fault")
            self._lbl_fault_code.setStyleSheet(
                f"color: {ACCENT_GREEN}; font-family: {FONT_MONO}; "
                f"font-size: 14px; font-weight: 700;"
            )

        # Trend buffers
        t = snap.timestamp - self._trend_start_time
        self._trend_time.append(t)
        self._trend_voltage.append(snap.dc_voltage)
        self._trend_current.append(snap.dc_current)
        self._trend_power.append(snap.dc_power)
        self._trend_temp.append(snap.inlet_temp)

    @staticmethod
    def _color_by_range(card: TelemetryCard, val: float, warn: float, crit: float) -> None:
        if val >= crit:
            card.set_color(ACCENT_RED)
        elif val >= warn:
            card.set_color(ACCENT_YELLOW)
        else:
            card.reset_color()

    # =====================================================================
    #  Trend plots
    # =====================================================================

    def _update_plots(self) -> None:
        if not self._trend_time:
            return
        t = np.array(self._trend_time)
        self._curve_v.setData(t, np.array(self._trend_voltage))
        self._curve_i.setData(t, np.array(self._trend_current))
        self._curve_p.setData(t, np.array(self._trend_power))
        self._curve_t.setData(t, np.array(self._trend_temp))

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

        # Collect params based on mode definition
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
