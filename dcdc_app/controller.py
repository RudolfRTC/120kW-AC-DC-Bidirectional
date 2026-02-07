"""PCS Controller: high-level state machine for startup, run, shutdown, and fault handling.

Manages the lifecycle of communication with a YSTECH PCS device including:
- Heartbeat transmission (every 200ms)
- Periodic status frame reception and decoding
- Command sequencing (mode set, start/stop, parameter changes)
- Fault detection and safe shutdown
- Reconnect logic
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from dcdc_app.can_iface import CANInterface
from dcdc_app.logging_utils import FrameLogger
from dcdc_app.protocol import (
    CAN_TIMEOUT_S,
    HEARTBEAT_INTERVAL_MS,
    PCS_DEFAULT_ADDR,
    PCSState,
    RunningState,
    WorkingMode,
    decode_rx_message,
    encode_heartbeat,
    encode_read_protection_params,
    encode_read_special_data,
    encode_set_mode_params12,
    encode_set_mode_params34,
    encode_set_protection_params1,
    encode_set_working_mode,
    encode_start_stop,
    fault_description,
    parse_can_id,
    pf_name,
)

logger = logging.getLogger(__name__)


class ControllerError(Exception):
    """Raised when a controller operation fails."""


@dataclass
class ControllerConfig:
    """Configuration for the PCS controller."""
    pcs_addr: int = PCS_DEFAULT_ADDR
    heartbeat_interval: float = HEARTBEAT_INTERVAL_MS / 1000.0  # seconds
    rx_timeout: float = 1.0  # seconds per recv call
    command_timeout: float = 3.0  # seconds to wait for command reply
    auto_heartbeat: bool = True
    auto_reconnect: bool = True


class PCSController:
    """High-level controller for YSTECH PCS device communication."""

    def __init__(
        self,
        can_iface: CANInterface,
        config: Optional[ControllerConfig] = None,
        frame_logger: Optional[FrameLogger] = None,
    ):
        self.can = can_iface
        self.config = config or ControllerConfig()
        self.frame_logger = frame_logger
        self.state = PCSState()

        self._running = False
        self._rx_thread: Optional[threading.Thread] = None
        self._hb_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._last_rx_time: float = 0.0
        self._callbacks: List[Callable[[str, Any], None]] = []
        self._pending_replies: Dict[int, threading.Event] = {}
        self._last_reply_data: Dict[int, Any] = {}

    @property
    def connected(self) -> bool:
        return self.can.connected

    @property
    def seconds_since_last_rx(self) -> float:
        if self._last_rx_time == 0:
            return float("inf")
        return time.time() - self._last_rx_time

    def add_callback(self, callback: Callable[[str, Any], None]) -> None:
        """Register a callback for decoded status updates.

        Callback receives (field_name, decoded_data) for each received frame.
        """
        self._callbacks.append(callback)

    def start(self) -> None:
        """Start the controller (RX loop + heartbeat loop)."""
        if not self.can.connected:
            self.can.connect()

        self._running = True

        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True, name="pcs-rx")
        self._rx_thread.start()

        if self.config.auto_heartbeat:
            self._hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True, name="pcs-hb")
            self._hb_thread.start()

        logger.info("PCS Controller started (PCS addr=0x%02X)", self.config.pcs_addr)

    def stop(self) -> None:
        """Stop the controller gracefully."""
        self._running = False
        if self._rx_thread:
            self._rx_thread.join(timeout=3.0)
        if self._hb_thread:
            self._hb_thread.join(timeout=1.0)
        logger.info("PCS Controller stopped")

    def send_command(self, can_id: int, data: bytes) -> bool:
        """Send a raw CAN command and log it."""
        success = self.can.send(can_id, data)
        if self.frame_logger:
            self.frame_logger.log_frame(can_id, data, direction="TX")
        return success

    def _wait_for_reply(self, pf: int, timeout: Optional[float] = None) -> Optional[Any]:
        """Wait for a reply with a specific PF code."""
        timeout = timeout or self.config.command_timeout
        event = threading.Event()
        self._pending_replies[pf] = event
        try:
            if event.wait(timeout):
                return self._last_reply_data.get(pf)
            else:
                logger.warning("Timeout waiting for reply PF=0x%02X", pf)
                return None
        finally:
            self._pending_replies.pop(pf, None)

    # -----------------------------------------------------------------------
    # High-level commands
    # -----------------------------------------------------------------------

    def enable(self, clear_faults: bool = True) -> bool:
        """Enable (start) the PCS device.

        If device is in fault state and clear_faults is True, clears faults first.
        """
        if clear_faults and self.state.status.is_fault:
            logger.info("Clearing faults before enable...")
            self.reset_faults()
            time.sleep(0.5)

        can_id, data = encode_start_stop(start=True, pcs_addr=self.config.pcs_addr)
        self.send_command(can_id, data)
        reply = self._wait_for_reply(0x10)
        if reply is True:
            logger.info("PCS enabled successfully")
            return True
        logger.warning("PCS enable failed or no reply")
        return False

    def disable(self) -> bool:
        """Disable (stop) the PCS device."""
        can_id, data = encode_start_stop(start=False, pcs_addr=self.config.pcs_addr)
        self.send_command(can_id, data)
        reply = self._wait_for_reply(0x10)
        if reply is True:
            logger.info("PCS disabled successfully")
            return True
        logger.warning("PCS disable failed or no reply")
        return False

    def reset_faults(self) -> bool:
        """Clear fault state on PCS device."""
        can_id, data = encode_start_stop(
            start=False, clear_fault=True, pcs_addr=self.config.pcs_addr,
        )
        self.send_command(can_id, data)
        reply = self._wait_for_reply(0x10)
        if reply is True:
            logger.info("Faults cleared successfully")
            return True
        logger.warning("Fault clear failed or no reply")
        return False

    def set_working_mode(self, mode: WorkingMode) -> bool:
        """Set the PCS working mode (requires device to be stopped first)."""
        can_id, data = encode_set_working_mode(mode.value, pcs_addr=self.config.pcs_addr)
        self.send_command(can_id, data)
        reply = self._wait_for_reply(0x0E)
        if reply is True:
            logger.info("Working mode set to %s", mode.name)
            return True
        logger.warning("Set working mode failed or no reply")
        return False

    def set_mode_parameters(
        self,
        mode: WorkingMode,
        params: List[float],
    ) -> bool:
        """Set mode parameters (up to 4 values).

        Must set working mode first with set_working_mode().
        """
        # Send params 1&2 (frame 12)
        p1 = params[0] if len(params) > 0 else 0.0
        p2 = params[1] if len(params) > 1 else 0.0
        can_id, data = encode_set_mode_params12(p1, p2, mode.value, self.config.pcs_addr)
        self.send_command(can_id, data)

        # Send params 3&4 (frame 13) if needed
        if len(params) > 2:
            p3 = params[2] if len(params) > 2 else 0.0
            p4 = params[3] if len(params) > 3 else 0.0
            can_id, data = encode_set_mode_params34(p3, p4, mode.value, self.config.pcs_addr)
            self.send_command(can_id, data)

        reply = self._wait_for_reply(0x0E)
        if reply is True:
            logger.info("Mode parameters set successfully")
            return True
        logger.warning("Set mode parameters failed or no reply")
        return False

    def read_protection_params(self, param_type: int = 0x01) -> Optional[Any]:
        """Read protection parameters from PCS.

        param_type: 0x01=voltage/current, 0x02=power/AC, 0x03=frequency.
        """
        reply_pf = {0x01: 0x02, 0x02: 0x03, 0x03: 0x04}.get(param_type, 0x02)
        can_id, data = encode_read_protection_params(param_type, self.config.pcs_addr)
        self.send_command(can_id, data)
        return self._wait_for_reply(reply_pf)

    def read_version(self) -> Optional[Any]:
        """Read ARM and DSP version from PCS."""
        can_id, data = encode_read_special_data(0x0A, self.config.pcs_addr)
        self.send_command(can_id, data)
        return self._wait_for_reply(0x34)

    def read_working_mode(self) -> Optional[Any]:
        """Read current working mode from PCS."""
        can_id, data = encode_read_special_data(0x0B, self.config.pcs_addr)
        self.send_command(can_id, data)
        return self._wait_for_reply(0x36)

    def get_faults(self) -> Tuple[int, str]:
        """Get current fault code and description from cached state."""
        code = self.state.status.fault_code
        return code, fault_description(code)

    def send_heartbeat(self, running_state: int = 0x02) -> None:
        """Send heartbeat (frame 26) to PCS to prevent timeout."""
        can_id, data = encode_heartbeat(
            dc_voltage=0.0,
            dc_current=0.0,
            running_state=running_state,
            pcs_addr=self.config.pcs_addr,
        )
        self.can.send(can_id, data)

    # -----------------------------------------------------------------------
    # Internal loops
    # -----------------------------------------------------------------------

    def _rx_loop(self) -> None:
        """Receive and decode CAN messages continuously."""
        while self._running:
            msg = self.can.recv(timeout=self.config.rx_timeout)
            if msg is None:
                # Check for RX timeout
                if self.seconds_since_last_rx > CAN_TIMEOUT_S and self._last_rx_time > 0:
                    logger.warning(
                        "No data from PCS for %.1fs (timeout=%ds)",
                        self.seconds_since_last_rx, CAN_TIMEOUT_S,
                    )
                continue

            if not msg.is_extended_id:
                continue

            self._last_rx_time = time.time()

            # Decode the message
            try:
                name, decoded = decode_rx_message(msg.arbitration_id, bytes(msg.data))
            except Exception as e:
                logger.debug("Decode error for ID=0x%08X: %s", msg.arbitration_id, e)
                name, decoded = None, None

            # Log the frame
            if self.frame_logger:
                self.frame_logger.log_frame(
                    msg.arbitration_id, bytes(msg.data),
                    direction="RX", decoded=decoded,
                )

            if name is None:
                continue

            # Update aggregated state
            with self._lock:
                if hasattr(self.state, name) and decoded is not None:
                    setattr(self.state, name, decoded)

            # Check for pending reply waiters
            fields = parse_can_id(msg.arbitration_id)
            pf = fields["pf"]
            if pf in self._pending_replies:
                self._last_reply_data[pf] = decoded
                self._pending_replies[pf].set()

            # Notify callbacks
            for cb in self._callbacks:
                try:
                    cb(name, decoded)
                except Exception as e:
                    logger.debug("Callback error: %s", e)

    def _heartbeat_loop(self) -> None:
        """Send heartbeat frames at the configured interval."""
        while self._running:
            try:
                self.send_heartbeat()
            except Exception as e:
                logger.debug("Heartbeat error: %s", e)
            time.sleep(self.config.heartbeat_interval)

    # -----------------------------------------------------------------------
    # Context manager
    # -----------------------------------------------------------------------

    def __enter__(self) -> PCSController:
        self.start()
        return self

    def __exit__(self, *args) -> None:
        # Try graceful shutdown
        try:
            if self.state.status.running_state in (
                RunningState.CONSTANT_VOLTAGE,
                RunningState.CONSTANT_CURRENT,
                RunningState.AC_CONSTANT_POWER,
                RunningState.OFF_GRID_INVERTER,
            ):
                logger.info("Graceful shutdown: disabling PCS...")
                self.disable()
                time.sleep(0.5)
        except Exception:
            pass
        self.stop()
