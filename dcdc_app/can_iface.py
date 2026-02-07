"""CAN bus interface layer for PEAK PCAN and simulated bus.

Provides a unified interface for sending/receiving CAN messages using python-can
with PCAN backend (Windows/Linux) or a virtual/simulated bus for dry-run mode.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, List, Optional

try:
    import can
    from can import Bus, Message
    CAN_AVAILABLE = True
except ImportError:
    CAN_AVAILABLE = False

from dcdc_app.protocol import CAN_BITRATE

logger = logging.getLogger(__name__)

# Common PCAN channel names
PCAN_CHANNELS = [
    "PCAN_USBBUS1",
    "PCAN_USBBUS2",
    "PCAN_USBBUS3",
    "PCAN_USBBUS4",
    "PCAN_PCIBUS1",
    "PCAN_PCIBUS2",
]


class CANInterface:
    """Wrapper around python-can Bus for PCS communication."""

    def __init__(
        self,
        interface: str = "pcan",
        channel: str = "PCAN_USBBUS1",
        bitrate: int = CAN_BITRATE,
        simulated: bool = False,
        receive_own_messages: bool = False,
    ):
        """Initialize CAN interface.

        Args:
            interface: python-can interface name ('pcan', 'socketcan', 'virtual', etc.)
            channel: Channel name (e.g. 'PCAN_USBBUS1', 'can0').
            bitrate: CAN bus bitrate (default 250000 from protocol spec).
            simulated: If True, use virtual bus instead of real hardware.
            receive_own_messages: If True, receive messages sent by this node.
        """
        self.interface = interface
        self.channel = channel
        self.bitrate = bitrate
        self.simulated = simulated
        self._bus: Optional[Bus] = None
        self._connected = False
        self._receive_own = receive_own_messages
        self._tx_count = 0
        self._rx_count = 0
        self._error_count = 0

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def stats(self) -> dict:
        return {
            "tx_count": self._tx_count,
            "rx_count": self._rx_count,
            "error_count": self._error_count,
        }

    def connect(self) -> None:
        """Open the CAN bus connection."""
        if not CAN_AVAILABLE:
            raise RuntimeError(
                "python-can is not installed. Install with: pip install python-can"
            )

        if self._connected:
            logger.warning("Already connected, disconnecting first")
            self.disconnect()

        try:
            if self.simulated:
                self._bus = can.Bus(
                    interface="virtual",
                    channel="virtual_pcs",
                    bitrate=self.bitrate,
                    receive_own_messages=self._receive_own,
                )
                logger.info("Connected to simulated (virtual) CAN bus")
            else:
                self._bus = can.Bus(
                    interface=self.interface,
                    channel=self.channel,
                    bitrate=self.bitrate,
                    receive_own_messages=self._receive_own,
                )
                logger.info(
                    "Connected to %s on %s at %d bps",
                    self.interface, self.channel, self.bitrate,
                )
            self._connected = True
        except Exception as e:
            self._error_count += 1
            logger.error("Failed to connect: %s", e)
            raise

    def disconnect(self) -> None:
        """Close the CAN bus connection."""
        if self._bus is not None:
            try:
                self._bus.shutdown()
            except Exception as e:
                logger.warning("Error during shutdown: %s", e)
            finally:
                self._bus = None
                self._connected = False
                logger.info("CAN bus disconnected")

    def send(self, can_id: int, data: bytes, is_extended: bool = True) -> bool:
        """Send a CAN message.

        Args:
            can_id: CAN arbitration ID.
            data: Message data (up to 8 bytes).
            is_extended: Use extended (29-bit) frame format.

        Returns:
            True if sent successfully.
        """
        if not self._connected or self._bus is None:
            logger.error("Cannot send: not connected")
            return False

        msg = can.Message(
            arbitration_id=can_id,
            data=data[:8],
            is_extended_id=is_extended,
            dlc=len(data[:8]),
        )

        try:
            self._bus.send(msg)
            self._tx_count += 1
            logger.debug(
                "TX  ID=0x%08X DLC=%d Data=%s",
                can_id, msg.dlc, data[:8].hex(" "),
            )
            return True
        except can.CanError as e:
            self._error_count += 1
            logger.error("TX error: %s", e)
            return False

    def recv(self, timeout: float = 1.0) -> Optional[can.Message]:
        """Receive a CAN message.

        Args:
            timeout: Receive timeout in seconds (None for blocking).

        Returns:
            Received Message or None on timeout.
        """
        if not self._connected or self._bus is None:
            return None

        try:
            msg = self._bus.recv(timeout=timeout)
            if msg is not None:
                self._rx_count += 1
                logger.debug(
                    "RX  ID=0x%08X DLC=%d Data=%s",
                    msg.arbitration_id, msg.dlc, msg.data.hex(" "),
                )
            return msg
        except can.CanError as e:
            self._error_count += 1
            logger.error("RX error: %s", e)
            return None

    def set_filters(self, filters: Optional[List[dict]] = None) -> None:
        """Set CAN message filters.

        Args:
            filters: List of filter dicts with 'can_id', 'can_mask', 'extended' keys.
                     If None, accept all messages.
        """
        if self._bus is not None:
            self._bus.set_filters(filters)
            if filters:
                logger.info("Set %d CAN filters", len(filters))
            else:
                logger.info("Cleared CAN filters (accept all)")

    def reconnect(self, max_retries: int = 4, base_delay: float = 2.0) -> bool:
        """Attempt to reconnect with exponential backoff.

        Args:
            max_retries: Maximum number of retry attempts.
            base_delay: Base delay in seconds (doubled each retry).

        Returns:
            True if reconnected successfully.
        """
        self.disconnect()
        delay = base_delay
        for attempt in range(1, max_retries + 1):
            logger.info("Reconnect attempt %d/%d...", attempt, max_retries)
            try:
                self.connect()
                return True
            except Exception as e:
                logger.warning("Reconnect failed: %s, retrying in %.1fs", e, delay)
                time.sleep(delay)
                delay *= 2
        logger.error("Failed to reconnect after %d attempts", max_retries)
        return False

    def __enter__(self) -> CANInterface:
        self.connect()
        return self

    def __exit__(self, *args) -> None:
        self.disconnect()


def list_pcan_interfaces() -> List[str]:
    """List available PCAN interfaces (best-effort detection).

    Returns:
        List of channel names that may be available.
    """
    available = []
    if not CAN_AVAILABLE:
        return ["(python-can not installed)"]

    for ch in PCAN_CHANNELS:
        try:
            bus = can.Bus(interface="pcan", channel=ch, bitrate=250000)
            bus.shutdown()
            available.append(ch)
        except Exception:
            pass

    if not available:
        return ["(no PCAN interfaces detected - check drivers and connections)"]
    return available
