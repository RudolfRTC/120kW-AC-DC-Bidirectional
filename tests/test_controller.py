"""Tests for the PCS Controller with simulated CAN bus."""

import time
import struct
import threading
import pytest

try:
    import can
    CAN_AVAILABLE = True
except ImportError:
    CAN_AVAILABLE = False

from dcdc_app.can_iface import CANInterface
from dcdc_app.controller import ControllerConfig, PCSController
from dcdc_app.logging_utils import FrameLogger
from dcdc_app.protocol import (
    PCS_DEFAULT_ADDR,
    RunningState,
    WorkingMode,
    make_rx_id,
)
from dcdc_app.simulator import SimulatedPCS


pytestmark = pytest.mark.skipif(not CAN_AVAILABLE, reason="python-can not installed")


class TestCANInterface:
    def test_simulated_connect_disconnect(self):
        iface = CANInterface(simulated=True)
        iface.connect()
        assert iface.connected
        iface.disconnect()
        assert not iface.connected

    def test_simulated_send_recv(self):
        iface = CANInterface(simulated=True, receive_own_messages=True)
        iface.connect()
        try:
            success = iface.send(0x18010AB4, b"\x01\x00\x00\x00\x00\x00\x00\x00")
            assert success
            msg = iface.recv(timeout=1.0)
            assert msg is not None
            assert msg.arbitration_id == 0x18010AB4
        finally:
            iface.disconnect()

    def test_stats(self):
        iface = CANInterface(simulated=True, receive_own_messages=True)
        iface.connect()
        try:
            iface.send(0x18010000, b"\x00" * 8)
            iface.recv(timeout=0.5)
            stats = iface.stats
            assert stats["tx_count"] >= 1
            assert stats["rx_count"] >= 1
        finally:
            iface.disconnect()

    def test_context_manager(self):
        with CANInterface(simulated=True) as iface:
            assert iface.connected
        assert not iface.connected


class TestSimulatedPCS:
    def test_start_stop(self):
        sim = SimulatedPCS()
        sim.start()
        assert sim._running
        time.sleep(0.3)
        sim.stop()
        assert not sim._running

    def test_receives_periodic_frames(self):
        """Verify the simulator sends periodic status frames."""
        sim = SimulatedPCS()
        sim.start()

        # Create a receiver on the same virtual bus
        rx_bus = can.Bus(
            interface="virtual",
            channel="virtual_pcs",
            bitrate=250000,
            receive_own_messages=False,
        )

        try:
            time.sleep(0.5)  # Wait for at least 2 periodic cycles
            received_pfs = set()
            deadline = time.time() + 2.0
            while time.time() < deadline:
                msg = rx_bus.recv(timeout=0.1)
                if msg and msg.is_extended_id:
                    pf = (msg.arbitration_id >> 16) & 0xFF
                    received_pfs.add(pf)

            # Should have received at least DC data (0x11) and status (0x13)
            assert 0x11 in received_pfs, f"Missing DC data frame, got PFs: {[hex(x) for x in received_pfs]}"
            assert 0x13 in received_pfs, f"Missing status frame, got PFs: {[hex(x) for x in received_pfs]}"
        finally:
            rx_bus.shutdown()
            sim.stop()

    def test_start_command(self):
        """Verify the simulator responds to start command."""
        sim = SimulatedPCS()
        sim.start()

        tx_bus = can.Bus(
            interface="virtual",
            channel="virtual_pcs",
            bitrate=250000,
            receive_own_messages=False,
        )

        try:
            time.sleep(0.3)
            # Send start command (frame 15, PF=0x0F)
            from dcdc_app.protocol import encode_start_stop, make_tx_id
            can_id, data = encode_start_stop(start=True)
            msg = can.Message(arbitration_id=can_id, data=data, is_extended_id=True)
            tx_bus.send(msg)

            # Wait for reply (PF=0x10)
            deadline = time.time() + 2.0
            got_reply = False
            while time.time() < deadline:
                reply = tx_bus.recv(timeout=0.1)
                if reply and reply.is_extended_id:
                    pf = (reply.arbitration_id >> 16) & 0xFF
                    if pf == 0x10:
                        assert reply.data[0] == 0x01  # success
                        got_reply = True
                        break

            assert got_reply, "Did not receive start reply"
            assert sim.started
        finally:
            tx_bus.shutdown()
            sim.stop()


class TestPCSController:
    def test_controller_with_simulator(self):
        """Full integration test: controller + simulated PCS."""
        sim = SimulatedPCS()
        sim.start()
        time.sleep(0.3)

        can_if = CANInterface(simulated=True)
        config = ControllerConfig(pcs_addr=PCS_DEFAULT_ADDR)
        ctrl = PCSController(can_if, config)

        try:
            ctrl.start()
            time.sleep(1.5)  # Wait for periodic frames

            # Should have received some status data
            assert ctrl.state.dc.voltage > 0 or ctrl.state.status.running_state > 0

            # Enable the PCS
            success = ctrl.enable()
            assert success

            time.sleep(0.5)
            # After enable, state should be running
            assert ctrl.state.status.running_state in (
                RunningState.CONSTANT_VOLTAGE,
                RunningState.CONSTANT_CURRENT,
                RunningState.STANDBY,
            ) or ctrl.state.status.running_state > 0

            # Disable
            success = ctrl.disable()
            assert success

        finally:
            ctrl.stop()
            can_if.disconnect()
            sim.stop()

    def test_controller_fault_handling(self):
        """Test fault detection and clearing."""
        sim = SimulatedPCS()
        sim.fault_code = 0x800D
        sim.running_state = RunningState.FAULT
        sim.start()
        time.sleep(0.3)

        can_if = CANInterface(simulated=True)
        ctrl = PCSController(can_if, ControllerConfig())

        try:
            ctrl.start()
            time.sleep(1.0)

            # Should detect fault
            code, desc = ctrl.get_faults()
            assert code == 0x800D
            assert "CAN1" in desc

            # Clear fault
            success = ctrl.reset_faults()
            assert success

            time.sleep(0.5)
            # Fault should be cleared in simulator
            assert sim.fault_code == 0
        finally:
            ctrl.stop()
            can_if.disconnect()
            sim.stop()

    def test_controller_callbacks(self):
        """Test that status update callbacks are invoked."""
        sim = SimulatedPCS()
        sim.start()
        time.sleep(0.3)

        can_if = CANInterface(simulated=True)
        ctrl = PCSController(can_if, ControllerConfig())

        received_updates = []

        def on_update(name, data):
            received_updates.append(name)

        ctrl.add_callback(on_update)

        try:
            ctrl.start()
            time.sleep(1.5)
            assert len(received_updates) > 0
            assert "dc" in received_updates or "status" in received_updates
        finally:
            ctrl.stop()
            can_if.disconnect()
            sim.stop()


class TestFrameLogger:
    def test_csv_logging(self, tmp_path):
        log_file = str(tmp_path / "test.csv")
        logger = FrameLogger(filepath=log_file, fmt="csv", console=False)
        logger.open()
        logger.log_frame(0x18110AB4, b"\x00" * 8, "RX")
        logger.close()

        with open(log_file) as f:
            lines = f.readlines()
        assert len(lines) == 2  # header + 1 record
        assert "0x18110AB4" in lines[1] or "18110AB4" in lines[1].upper()

    def test_jsonl_logging(self, tmp_path):
        import json
        log_file = str(tmp_path / "test.jsonl")
        logger = FrameLogger(filepath=log_file, fmt="jsonl", console=False)
        logger.open()
        logger.log_frame(0x18110AB4, b"\x01\x02\x03\x04\x05\x06\x07\x08", "RX")
        logger.close()

        with open(log_file) as f:
            line = f.readline()
        record = json.loads(line)
        assert record["direction"] == "RX"
        assert "can_id" in record
