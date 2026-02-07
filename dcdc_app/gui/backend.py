"""GUI backend adapter – wraps PCSController for thread-safe Qt integration.

Bridges the existing CAN/controller layer with Qt signals/slots so the UI
thread never touches CAN I/O directly. All heavy work runs in a QThread.
"""

from __future__ import annotations

import time
import traceback
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QMutex, QMutexLocker, QObject, QThread, Signal

from dcdc_app.can_iface import CANInterface, PCAN_CHANNELS
from dcdc_app.controller import ControllerConfig, PCSController
from dcdc_app.logging_utils import FrameLogger
from dcdc_app.protocol import (
    CAN_BITRATE,
    FAULT_CODES,
    MODE_PARAMS,
    PCS_DEFAULT_ADDR,
    WorkingMode,
    RunningState,
    fault_description,
    parse_can_id,
    pf_name,
)
from dcdc_app.simulator import SimulatedPCS


# ── Data snapshot passed from worker → UI ───────────────────────────────────

@dataclass
class TelemetrySnapshot:
    """Thread-safe snapshot of all PCS telemetry for the UI."""
    # DC side
    dc_voltage: float = 0.0
    dc_current: float = 0.0
    dc_power: float = 0.0
    inlet_temp: float = 0.0
    outlet_temp: float = 0.0
    # Hi-res DC
    dc_voltage_hr: float = 0.0
    dc_current_hr: float = 0.0
    # Capacity / energy
    capacity_ah: float = 0.0
    energy_wh: float = 0.0
    # Status
    running_state: int = 0
    running_state_name: str = "UNKNOWN"
    fault_code: int = 0
    fault_description: str = "No fault"
    is_fault: bool = False
    # Grid
    grid_v_u: float = 0.0
    grid_v_v: float = 0.0
    grid_v_w: float = 0.0
    grid_i_u: float = 0.0
    grid_i_v: float = 0.0
    grid_i_w: float = 0.0
    power_factor: float = 0.0
    frequency: float = 0.0
    # System power
    active_power: float = 0.0
    reactive_power: float = 0.0
    apparent_power: float = 0.0
    # Timestamps
    seconds_since_rx: float = 999.0
    timestamp: float = 0.0
    # CAN stats
    tx_count: int = 0
    rx_count: int = 0
    error_count: int = 0


@dataclass
class RawCANFrame:
    """Single raw CAN frame for the table viewer."""
    timestamp: float
    direction: str
    can_id: int
    dlc: int
    data_hex: str
    pf_name: str


# ── Worker thread ────────────────────────────────────────────────────────────

class BackendWorker(QObject):
    """Runs in a QThread; manages CAN + controller lifecycle."""

    # Signals → UI
    telemetry_updated = Signal(TelemetrySnapshot)
    raw_frame = Signal(RawCANFrame)
    connection_state = Signal(str)          # "disconnected" | "connecting" | "online" | "error"
    event_log = Signal(str)                 # timestamped log messages
    command_result = Signal(str, bool)      # (command_name, success)
    error_occurred = Signal(str)            # user-visible error text

    def __init__(self, parent=None):
        super().__init__(parent)
        self._can: Optional[CANInterface] = None
        self._ctrl: Optional[PCSController] = None
        self._sim: Optional[SimulatedPCS] = None
        self._frame_logger: Optional[FrameLogger] = None
        self._mutex = QMutex()
        self._connected = False

    # ── Connection management ────────────────────────────────────────────

    def connect_pcs(
        self,
        interface: str,
        channel: str,
        bitrate: int,
        pcs_addr: int,
        simulated: bool,
    ) -> None:
        """Connect to PCS (called from UI thread via signal)."""
        self.connection_state.emit("connecting")
        self._log("Connecting...")

        try:
            # Disconnect if already active
            self._disconnect_internal()

            # Start simulator if needed
            if simulated:
                self._sim = SimulatedPCS(pcs_addr=pcs_addr)
                self._sim.start()
                time.sleep(0.3)
                self._log("Simulator started")

            # Create CAN interface
            self._can = CANInterface(
                interface=interface,
                channel=channel,
                bitrate=bitrate,
                simulated=simulated,
            )

            # Create controller
            config = ControllerConfig(pcs_addr=pcs_addr)
            self._ctrl = PCSController(self._can, config, self._frame_logger)

            # Register callback for raw frames
            self._ctrl.add_callback(self._on_frame_decoded)

            # Start controller (opens CAN + starts RX/HB threads)
            self._ctrl.start()

            with QMutexLocker(self._mutex):
                self._connected = True

            self.connection_state.emit("online")
            self._log(f"Connected ({'simulator' if simulated else f'{interface}/{channel}'})")

        except Exception as e:
            self.connection_state.emit("error")
            self.error_occurred.emit(str(e))
            self._log(f"Connection failed: {e}")
            self._disconnect_internal()

    def disconnect_pcs(self) -> None:
        """Disconnect from PCS."""
        self._disconnect_internal()
        self.connection_state.emit("disconnected")
        self._log("Disconnected")

    def _disconnect_internal(self) -> None:
        with QMutexLocker(self._mutex):
            self._connected = False
        if self._ctrl:
            try:
                self._ctrl.stop()
            except Exception:
                pass
        if self._can:
            try:
                self._can.disconnect()
            except Exception:
                pass
        if self._sim:
            try:
                self._sim.stop()
            except Exception:
                pass
        self._ctrl = None
        self._can = None
        self._sim = None

    # ── Telemetry polling (called by QTimer on UI side) ──────────────────

    def poll_telemetry(self) -> None:
        """Build a snapshot from the current controller state."""
        with QMutexLocker(self._mutex):
            if not self._connected or self._ctrl is None:
                return

        try:
            ctrl = self._ctrl
            s = ctrl.state
            snap = TelemetrySnapshot(
                dc_voltage=s.dc.voltage,
                dc_current=s.dc.current,
                dc_power=s.dc.power,
                inlet_temp=s.dc.inlet_temperature,
                outlet_temp=s.capacity_energy.outlet_temperature,
                dc_voltage_hr=s.dc_hires.voltage,
                dc_current_hr=s.dc_hires.current,
                capacity_ah=s.capacity_energy.capacity,
                energy_wh=s.capacity_energy.energy,
                running_state=s.status.running_state,
                running_state_name=s.status.state_name,
                fault_code=s.status.fault_code,
                fault_description=s.status.fault_description,
                is_fault=s.status.is_fault,
                grid_v_u=s.grid_voltage.u_voltage,
                grid_v_v=s.grid_voltage.v_voltage,
                grid_v_w=s.grid_voltage.w_voltage,
                grid_i_u=s.grid_current.u_current,
                grid_i_v=s.grid_current.v_current,
                grid_i_w=s.grid_current.w_current,
                power_factor=s.grid_current.power_factor,
                frequency=s.system_power.frequency,
                active_power=s.system_power.active_power,
                reactive_power=s.system_power.reactive_power,
                apparent_power=s.system_power.apparent_power,
                seconds_since_rx=ctrl.seconds_since_last_rx,
                timestamp=time.time(),
                tx_count=ctrl.can.stats["tx_count"] if ctrl.can else 0,
                rx_count=ctrl.can.stats["rx_count"] if ctrl.can else 0,
                error_count=ctrl.can.stats["error_count"] if ctrl.can else 0,
            )
            self.telemetry_updated.emit(snap)
        except Exception:
            pass  # Controller might be shutting down

    # ── Commands (run in worker thread context) ──────────────────────────

    def cmd_enable(self) -> None:
        if not self._ctrl:
            return
        try:
            ok = self._ctrl.enable(clear_faults=True)
            self.command_result.emit("enable", ok)
            self._log(f"Enable: {'OK' if ok else 'FAILED'}")
        except Exception as e:
            self.command_result.emit("enable", False)
            self.error_occurred.emit(str(e))

    def cmd_disable(self) -> None:
        if not self._ctrl:
            return
        try:
            ok = self._ctrl.disable()
            self.command_result.emit("disable", ok)
            self._log(f"Disable: {'OK' if ok else 'FAILED'}")
        except Exception as e:
            self.command_result.emit("disable", False)
            self.error_occurred.emit(str(e))

    def cmd_reset_faults(self) -> None:
        if not self._ctrl:
            return
        try:
            ok = self._ctrl.reset_faults()
            self.command_result.emit("reset_faults", ok)
            self._log(f"Reset faults: {'OK' if ok else 'FAILED'}")
        except Exception as e:
            self.command_result.emit("reset_faults", False)
            self.error_occurred.emit(str(e))

    def cmd_set_mode(self, mode: WorkingMode, params: List[float]) -> None:
        if not self._ctrl:
            return
        try:
            ok = self._ctrl.set_working_mode(mode)
            if ok and params:
                ok = self._ctrl.set_mode_parameters(mode, params)
            self.command_result.emit("set_mode", ok)
            self._log(f"Set mode {mode.name}: {'OK' if ok else 'FAILED'}")
        except Exception as e:
            self.command_result.emit("set_mode", False)
            self.error_occurred.emit(str(e))

    # ── Frame logging ────────────────────────────────────────────────────

    def start_recording(self, filepath: str) -> None:
        fmt = "jsonl" if filepath.endswith(".jsonl") else "csv"
        self._frame_logger = FrameLogger(filepath=filepath, fmt=fmt, console=False)
        self._frame_logger.open()
        self._log(f"Recording to {filepath}")

    def stop_recording(self) -> None:
        if self._frame_logger:
            self._frame_logger.close()
            self._frame_logger = None
            self._log("Recording stopped")

    # ── Internal helpers ─────────────────────────────────────────────────

    def _on_frame_decoded(self, name: str, decoded: Any) -> None:
        """Controller callback – runs in the RX thread."""
        try:
            # We don't emit raw frames from here since the controller
            # callback doesn't give us the raw CAN data. Raw frames
            # will be captured differently if needed.
            pass
        except Exception:
            pass

    def _log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.event_log.emit(f"[{ts}] {msg}")
