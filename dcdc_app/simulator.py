"""Simulated PCS device for dry-run / testing without hardware.

Creates a virtual CAN bus and periodically sends realistic PCS status frames,
responding to commands as a real PCS would.
"""

from __future__ import annotations

import logging
import random
import struct
import threading
import time
from typing import Optional

try:
    import can
except ImportError:
    can = None  # type: ignore

from dcdc_app.protocol import (
    CAN_BITRATE,
    CONTROLLER_ADDR,
    PCS_DEFAULT_ADDR,
    RunningState,
    WorkingMode,
    build_can_id,
    make_rx_id,
    parse_can_id,
)

logger = logging.getLogger(__name__)


class SimulatedPCS:
    """Simulated PCS device that runs on a virtual CAN bus.

    Generates periodic status frames (200ms) and responds to commands.
    """

    def __init__(
        self,
        pcs_addr: int = PCS_DEFAULT_ADDR,
        bus_channel: str = "virtual_pcs",
    ):
        self.pcs_addr = pcs_addr
        self.bus_channel = bus_channel
        self._bus: Optional[can.Bus] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Simulated PCS internal state
        self.running_state = RunningState.STANDBY
        self.working_mode = WorkingMode.IDLE
        self.fault_code = 0
        self.started = False

        # Simulated measurements
        self.dc_voltage = 400.0   # V
        self.dc_current = 0.0     # A
        self.dc_power = 0.0       # kW
        self.inlet_temp = 35.0    # °C
        self.outlet_temp = 40.0   # °C
        self.capacity = 0.0       # Ah
        self.energy = 0.0         # Wh
        self.grid_voltage_u = 230.0
        self.grid_voltage_v = 230.0
        self.grid_voltage_w = 230.0
        self.grid_current_u = 0.0
        self.grid_current_v = 0.0
        self.grid_current_w = 0.0
        self.power_factor = 0.98
        self.frequency = 50.0
        self.active_power = 0.0
        self.reactive_power = 0.0
        self.apparent_power = 0.0

        # Protection params
        self.max_output_voltage = 800.0
        self.min_output_voltage = 50.0
        self.max_charge_current = 150.0
        self.max_discharge_current = 150.0

        self._last_heartbeat = time.time()

    def start(self) -> None:
        """Start the simulated PCS on a virtual CAN bus."""
        if can is None:
            raise RuntimeError("python-can not installed")

        self._bus = can.Bus(
            interface="virtual",
            channel=self.bus_channel,
            bitrate=CAN_BITRATE,
            receive_own_messages=False,
        )
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Simulated PCS started (addr=0x%02X)", self.pcs_addr)

    def stop(self) -> None:
        """Stop the simulated PCS."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._bus:
            self._bus.shutdown()
            self._bus = None
        logger.info("Simulated PCS stopped")

    def _make_id(self, pf: int) -> int:
        """Build CAN ID for PCS -> controller message."""
        return build_can_id(pf, CONTROLLER_ADDR, self.pcs_addr)

    def _send(self, pf: int, data: bytes) -> None:
        """Send a frame from the simulated PCS."""
        if self._bus is None:
            return
        msg = can.Message(
            arbitration_id=self._make_id(pf),
            data=data[:8].ljust(8, b"\x00"),
            is_extended_id=True,
        )
        try:
            self._bus.send(msg)
        except Exception as e:
            logger.debug("Sim TX error: %s", e)

    def _add_noise(self, value: float, pct: float = 0.5) -> float:
        """Add small random noise to a value."""
        return value + value * random.uniform(-pct / 100, pct / 100)

    def _send_periodic_frames(self) -> None:
        """Send all periodic status frames (200ms cycle)."""
        # Update simulated measurements
        if self.started:
            self.dc_current = self._add_noise(self.dc_current if self.dc_current != 0 else 10.0)
            self.dc_power = self.dc_voltage * self.dc_current / 1000.0
            self.active_power = self.dc_power * 0.97
            self.apparent_power = abs(self.active_power) * 1.02
            self.inlet_temp = self._add_noise(35.0 + abs(self.dc_current) * 0.05)
            self.outlet_temp = self.inlet_temp + 5.0
            self.capacity += abs(self.dc_current) * 0.2 / 3600  # Ah
            self.energy += abs(self.dc_power) * 0.2 * 1000 / 3600  # Wh
            self.grid_current_u = self._add_noise(abs(self.active_power) * 1000 / 230 / 3)
            self.grid_current_v = self._add_noise(self.grid_current_u)
            self.grid_current_w = self._add_noise(self.grid_current_u)

        # Frame 17 (0x11): DC data
        v_raw = int(self._add_noise(self.dc_voltage) / 0.1)
        i_raw = int((self._add_noise(self.dc_current) + 1000.0) / 0.1)
        p_raw = int(self._add_noise(self.dc_power) / 0.1)
        t_raw = int((self._add_noise(self.inlet_temp) + 50.0) / 0.1)
        self._send(0x11, struct.pack(">HHHH", v_raw, i_raw, p_raw, t_raw))

        # Frame 18 (0x12): Capacity/energy
        cap_raw = int(self.capacity / 0.1)
        energy_raw = int(self.energy / 0.1)
        tout_raw = int((self._add_noise(self.outlet_temp) + 50.0) / 0.1)
        self._send(0x12, struct.pack(">HIH", cap_raw, energy_raw, tout_raw))

        # Frame 19 (0x13): Status
        self._send(0x13, struct.pack(">BxHxxxx", self.running_state, self.fault_code))

        # Frame 20 (0x14): Grid voltages
        vu = int(self._add_noise(self.grid_voltage_u) / 0.1)
        vv = int(self._add_noise(self.grid_voltage_v) / 0.1)
        vw = int(self._add_noise(self.grid_voltage_w) / 0.1)
        self._send(0x14, struct.pack(">HHHxx", vu, vv, vw))

        # Frame 21 (0x15): Grid currents + PF
        iu = int(self._add_noise(self.grid_current_u) / 0.1)
        iv = int(self._add_noise(self.grid_current_v) / 0.1)
        iw = int(self._add_noise(self.grid_current_w) / 0.1)
        pf_raw = int(self._add_noise(self.power_factor) / 0.1)
        self._send(0x15, struct.pack(">HHHh", iu, iv, iw, pf_raw))

        # Frame 22 (0x16): System power
        ap = int(self._add_noise(self.active_power) / 0.1)
        rp = int(self._add_noise(self.reactive_power) / 0.1)
        sp = int(self._add_noise(self.apparent_power) / 0.1)
        freq = int(self._add_noise(self.frequency) / 0.1)
        self._send(0x16, struct.pack(">HHHH", ap, rp, sp, freq))

        # Frame 0x1839: High-res DC
        v_hr = int(self._add_noise(self.dc_voltage) / 0.001)
        i_hr = int((self._add_noise(self.dc_current) + 1000.0) / 0.001)
        self._send(0x39, struct.pack(">II", v_hr, i_hr))

    def _handle_command(self, pf: int, data: bytes) -> None:
        """Handle an incoming command frame from the controller."""
        if pf == 0x01:
            # Read protection params
            param_type = data[0]
            if param_type == 0x01:
                reply = struct.pack(
                    ">HHHH",
                    int(self.max_output_voltage / 0.1),
                    int(self.min_output_voltage / 0.1),
                    int(self.max_charge_current / 0.1),
                    int(self.max_discharge_current / 0.1),
                )
                self._send(0x02, reply)
            elif param_type == 0x02:
                self._send(0x03, struct.pack(">HHHH", 1200, 1200, 2640, 1760))
            elif param_type == 0x03:
                self._send(0x04, struct.pack(">HHBBxx", 550, 450, 55, 45))

        elif pf == 0x05:
            # Set protection param 1
            self.max_output_voltage = struct.unpack_from(">H", data, 0)[0] * 0.1
            self.min_output_voltage = struct.unpack_from(">H", data, 2)[0] * 0.1
            self.max_charge_current = struct.unpack_from(">H", data, 4)[0] * 0.1
            self.max_discharge_current = struct.unpack_from(">H", data, 6)[0] * 0.1
            self._send(0x08, b"\x01\x01" + b"\x00" * 6)

        elif pf == 0x0B:
            # Set working mode
            mode = data[0]
            try:
                self.working_mode = WorkingMode(mode)
                self._send(0x0E, b"\x01" + b"\x00" * 7)
            except ValueError:
                self._send(0x0E, b"\x00" + b"\x00" * 7)

        elif pf == 0x0C:
            # Set params 1&2 - acknowledge
            self._send(0x0E, b"\x01" + b"\x00" * 7)

        elif pf == 0x0D:
            # Set params 3&4 - acknowledge
            self._send(0x0E, b"\x01" + b"\x00" * 7)

        elif pf == 0x0F:
            # Start/stop
            start_cmd = data[0]
            clear_fault = data[1]
            if clear_fault == 1:
                self.fault_code = 0
                if self.running_state == RunningState.FAULT:
                    self.running_state = RunningState.STANDBY
            if start_cmd == 1:
                self.started = True
                self.running_state = RunningState.CONSTANT_VOLTAGE
                self.dc_current = 50.0
            elif start_cmd == 0:
                self.started = False
                self.running_state = RunningState.STANDBY
                self.dc_current = 0.0
            self._send(0x10, b"\x01" + b"\x00" * 7)

        elif pf == 0x09:
            # Set time - acknowledge
            self._send(0x0A, b"\x01" + b"\x00" * 7)

        elif pf == 0x1A:
            # Heartbeat from controller
            self._last_heartbeat = time.time()

        elif pf == 0x1D:
            # Read special data
            data_type = data[0]
            if data_type == 0x0A:
                # Version info
                self._send(0x34, bytes([1, 2, 3, 2, 1, 38, 0, 0]))
                self._send(0x35, bytes([1, 2, 3, 2, 1, 38, 0, 0]))
            elif data_type == 0x0B:
                # Working mode
                self._send(0x36, bytes([self.working_mode]) + b"\x00" * 7)
            else:
                self._send(0x1C, bytes([data_type, 0x01]) + b"\x00" * 6)

    def _run_loop(self) -> None:
        """Main loop for the simulated PCS."""
        next_periodic = time.time()
        while self._running:
            # Check for incoming commands
            if self._bus:
                msg = self._bus.recv(timeout=0.01)
                if msg is not None and msg.is_extended_id:
                    fields = parse_can_id(msg.arbitration_id)
                    # Only process messages addressed to us (PS == our address)
                    if fields["sa"] == CONTROLLER_ADDR:
                        self._handle_command(fields["pf"], bytes(msg.data))

            # Check heartbeat timeout
            if time.time() - self._last_heartbeat > 5.0 and self.started:
                logger.warning("Simulated PCS: CAN heartbeat timeout!")
                self.fault_code = 0x800D
                self.running_state = RunningState.FAULT
                self.started = False

            # Send periodic frames at 200ms
            now = time.time()
            if now >= next_periodic:
                self._send_periodic_frames()
                next_periodic = now + 0.2

    def __enter__(self) -> SimulatedPCS:
        self.start()
        return self

    def __exit__(self, *args) -> None:
        self.stop()
