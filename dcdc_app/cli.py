"""CLI entry point for the YSTECH PCS CAN Communication Application.

Provides commands for monitoring, controlling, and logging PCS device data
over CAN bus using PEAK PCAN hardware or simulated bus.

Usage:
    python -m dcdc_app.cli [OPTIONS] COMMAND [ARGS]

Examples:
    python -m dcdc_app.cli --dry-run monitor
    python -m dcdc_app.cli --channel PCAN_USBBUS1 enable
    python -m dcdc_app.cli --dry-run record --duration 10 --out data.csv
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from typing import Any, Optional

from dcdc_app.can_iface import CANInterface, list_pcan_interfaces
from dcdc_app.controller import ControllerConfig, PCSController
from dcdc_app.logging_utils import FrameLogger, setup_logging
from dcdc_app.protocol import (
    CAN_BITRATE,
    FAULT_CODES,
    MODE_PARAMS,
    PCS_DEFAULT_ADDR,
    RunningState,
    WorkingMode,
    fault_description,
)
from dcdc_app.simulator import SimulatedPCS


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dcdc-pcs",
        description="YSTECH PCS (30-120kW) CAN Communication Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Protocol: CAN 2.0B extended frame, J1939-based, 250 kbps
Reference: YSTECH CAN communication protocol v1.11 (2023-11-27)

Examples:
  %(prog)s --dry-run monitor                  Monitor PCS in simulation mode
  %(prog)s --channel PCAN_USBBUS1 enable      Start the PCS device
  %(prog)s --dry-run set cv 400               Set DC constant voltage to 400V
  %(prog)s record --duration 60 --out log.csv Record 60 seconds to CSV
""",
    )

    # Global options
    parser.add_argument(
        "--interface", default="pcan",
        help="python-can interface (default: pcan)",
    )
    parser.add_argument(
        "--channel", default="PCAN_USBBUS1",
        help="CAN channel name (default: PCAN_USBBUS1)",
    )
    parser.add_argument(
        "--bitrate", type=int, default=CAN_BITRATE,
        help=f"CAN bitrate in bps (default: {CAN_BITRATE} from protocol spec)",
    )
    parser.add_argument(
        "--pcs-addr", type=lambda x: int(x, 0), default=PCS_DEFAULT_ADDR,
        help=f"PCS device CAN address (default: 0x{PCS_DEFAULT_ADDR:02X})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Use simulated CAN bus (no hardware required)",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    parser.add_argument(
        "--log-file", default=None,
        help="Application log file path",
    )

    sub = parser.add_subparsers(dest="command", help="Available commands")

    # list-interfaces
    sub.add_parser("list-interfaces", help="List available PCAN interfaces")

    # monitor
    mon = sub.add_parser("monitor", help="Monitor PCS real-time data")
    mon.add_argument(
        "--log-frames", default=None,
        help="Log all frames to file (CSV or JSONL based on extension)",
    )
    mon.add_argument(
        "--raw", action="store_true",
        help="Show raw hex data without decoding",
    )

    # enable
    sub.add_parser("enable", help="Enable (start) the PCS device")

    # disable
    sub.add_parser("disable", help="Disable (stop) the PCS device")

    # set
    set_cmd = sub.add_parser("set", help="Set PCS parameter or working mode")
    set_cmd.add_argument(
        "parameter",
        help="Parameter to set (e.g. 'mode', 'cv', 'cc', 'cp', 'start', 'stop')",
    )
    set_cmd.add_argument(
        "value", nargs="*",
        help="Value(s) for the parameter",
    )

    # dump-faults
    sub.add_parser("dump-faults", help="Show all known fault codes")

    # reset-faults
    sub.add_parser("reset-faults", help="Clear fault state on PCS device")

    # record
    rec = sub.add_parser("record", help="Record CAN frames to file")
    rec.add_argument(
        "--duration", "-d", type=float, required=True,
        help="Recording duration in seconds",
    )
    rec.add_argument(
        "--out", "-o", required=True,
        help="Output file path (.csv or .jsonl)",
    )

    # status
    sub.add_parser("status", help="Read and display current PCS status")

    # version
    sub.add_parser("version", help="Read PCS firmware version")

    # read-params
    rp = sub.add_parser("read-params", help="Read PCS protection parameters")
    rp.add_argument(
        "--type", type=int, default=1, choices=[1, 2, 3],
        help="Parameter type: 1=V/I limits, 2=power/AC limits, 3=frequency limits",
    )

    return parser


def _make_can(args) -> CANInterface:
    """Create CAN interface from parsed args."""
    return CANInterface(
        interface=args.interface,
        channel=args.channel,
        bitrate=args.bitrate,
        simulated=args.dry_run,
    )


def _make_controller(args, frame_logger: Optional[FrameLogger] = None) -> PCSController:
    """Create PCS controller from parsed args."""
    can_if = _make_can(args)
    config = ControllerConfig(pcs_addr=args.pcs_addr)
    return PCSController(can_if, config, frame_logger)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_list_interfaces(args) -> int:
    print("Scanning for PCAN interfaces...")
    interfaces = list_pcan_interfaces()
    for iface in interfaces:
        print(f"  {iface}")
    return 0


def cmd_monitor(args) -> int:
    log_path = getattr(args, "log_frames", None)
    fmt = "jsonl" if log_path and log_path.endswith(".jsonl") else "csv"
    frame_logger = FrameLogger(filepath=log_path, fmt=fmt, console=True)

    sim = None
    if args.dry_run:
        sim = SimulatedPCS(pcs_addr=args.pcs_addr)
        sim.start()

    ctrl = _make_controller(args, frame_logger)
    stop_event = [False]

    def on_signal(sig, frame):
        stop_event[0] = True
        print("\nStopping monitor...")

    signal.signal(signal.SIGINT, on_signal)

    try:
        frame_logger.open()
        ctrl.start()
        print(f"Monitoring PCS (addr=0x{args.pcs_addr:02X})... Press Ctrl+C to stop.\n")

        while not stop_event[0]:
            time.sleep(0.5)
    finally:
        ctrl.stop()
        ctrl.can.disconnect()
        frame_logger.close()
        if sim:
            sim.stop()

    return 0


def cmd_enable(args) -> int:
    sim = None
    if args.dry_run:
        sim = SimulatedPCS(pcs_addr=args.pcs_addr)
        sim.start()
        time.sleep(0.3)

    ctrl = _make_controller(args)
    try:
        ctrl.start()
        time.sleep(0.5)  # Let heartbeat establish
        success = ctrl.enable()
        time.sleep(0.5)
        if success:
            print("PCS enabled successfully")
            print(f"  State: {ctrl.state.status.state_name}")
        else:
            print("PCS enable FAILED - check connection and fault status")
            return 1
    finally:
        ctrl.stop()
        ctrl.can.disconnect()
        if sim:
            sim.stop()
    return 0


def cmd_disable(args) -> int:
    sim = None
    if args.dry_run:
        sim = SimulatedPCS(pcs_addr=args.pcs_addr)
        sim.start()
        time.sleep(0.3)

    ctrl = _make_controller(args)
    try:
        ctrl.start()
        time.sleep(0.5)
        success = ctrl.disable()
        time.sleep(0.5)
        if success:
            print("PCS disabled successfully")
        else:
            print("PCS disable FAILED")
            return 1
    finally:
        ctrl.stop()
        ctrl.can.disconnect()
        if sim:
            sim.stop()
    return 0


def cmd_set(args) -> int:
    param = args.parameter.lower()
    values = args.value

    sim = None
    if args.dry_run:
        sim = SimulatedPCS(pcs_addr=args.pcs_addr)
        sim.start()
        time.sleep(0.3)

    ctrl = _make_controller(args)
    try:
        ctrl.start()
        time.sleep(0.5)

        if param == "mode":
            if not values:
                print("Usage: set mode <MODE_NAME_OR_HEX>")
                print("Available modes:")
                for m in WorkingMode:
                    print(f"  0x{m.value:02X}  {m.name}")
                return 1
            mode_str = values[0].upper()
            # Try name first, then hex
            mode = None
            for m in WorkingMode:
                if m.name == mode_str:
                    mode = m
                    break
            if mode is None:
                try:
                    mode = WorkingMode(int(values[0], 0))
                except (ValueError, KeyError):
                    print(f"Unknown mode: {values[0]}")
                    return 1

            success = ctrl.set_working_mode(mode)
            if success:
                print(f"Working mode set to {mode.name} (0x{mode.value:02X})")
                # Set parameters if provided
                if len(values) > 1:
                    params = [float(v) for v in values[1:]]
                    ctrl.set_mode_parameters(mode, params)
                    print(f"Mode parameters set: {params}")
            else:
                print("Failed to set working mode")
                return 1

        elif param in ("cv", "voltage"):
            if not values:
                print("Usage: set cv <voltage_V>")
                return 1
            voltage = float(values[0])
            ctrl.set_working_mode(WorkingMode.DC_CONSTANT_VOLTAGE)
            time.sleep(0.2)
            ctrl.set_mode_parameters(WorkingMode.DC_CONSTANT_VOLTAGE, [voltage])
            print(f"Set DC constant voltage: {voltage} V")

        elif param in ("cc", "current"):
            if not values:
                print("Usage: set cc <current_A>")
                return 1
            current = float(values[0])
            ctrl.set_working_mode(WorkingMode.DC_CONSTANT_CURRENT)
            time.sleep(0.2)
            ctrl.set_mode_parameters(WorkingMode.DC_CONSTANT_CURRENT, [current])
            print(f"Set DC constant current: {current} A")

        elif param in ("cp", "power"):
            if not values:
                print("Usage: set cp <power_W>")
                return 1
            power = float(values[0])
            ctrl.set_working_mode(WorkingMode.DC_CONSTANT_POWER)
            time.sleep(0.2)
            ctrl.set_mode_parameters(WorkingMode.DC_CONSTANT_POWER, [power])
            print(f"Set DC constant power: {power} W")

        elif param in ("cccv",):
            if len(values) < 3:
                print("Usage: set cccv <voltage_V> <current_A> <end_current_A>")
                return 1
            v, i, ei = float(values[0]), float(values[1]), float(values[2])
            ctrl.set_working_mode(WorkingMode.DC_CC_CV)
            time.sleep(0.2)
            ctrl.set_mode_parameters(WorkingMode.DC_CC_CV, [v, i, ei])
            print(f"Set DC CC-CV: V={v}V, I={i}A, end_I={ei}A")

        else:
            print(f"Unknown parameter: {param}")
            print("Available: mode, cv, cc, cp, cccv")
            return 1

    finally:
        ctrl.stop()
        ctrl.can.disconnect()
        if sim:
            sim.stop()

    return 0


def cmd_dump_faults(args) -> int:
    print("YSTECH PCS Fault Code Table")
    print("=" * 65)
    print(f"{'Code (hex)':<14} {'Code (dec)':<12} {'Description'}")
    print("-" * 65)
    for code, desc in sorted(FAULT_CODES.items()):
        print(f"0x{code:04X}        {code:<12d} {desc}")
    print("-" * 65)
    print("Other codes: Internal failure - contact factory")
    return 0


def cmd_reset_faults(args) -> int:
    sim = None
    if args.dry_run:
        sim = SimulatedPCS(pcs_addr=args.pcs_addr)
        sim.start()
        time.sleep(0.3)

    ctrl = _make_controller(args)
    try:
        ctrl.start()
        time.sleep(0.5)
        success = ctrl.reset_faults()
        if success:
            print("Faults cleared successfully")
        else:
            print("Fault clear FAILED")
            return 1
    finally:
        ctrl.stop()
        ctrl.can.disconnect()
        if sim:
            sim.stop()
    return 0


def cmd_record(args) -> int:
    duration = args.duration
    out_path = args.out
    fmt = "jsonl" if out_path.endswith(".jsonl") else "csv"
    frame_logger = FrameLogger(filepath=out_path, fmt=fmt, console=False)

    sim = None
    if args.dry_run:
        sim = SimulatedPCS(pcs_addr=args.pcs_addr)
        sim.start()

    ctrl = _make_controller(args, frame_logger)
    stop_event = [False]

    def on_signal(sig, frame):
        stop_event[0] = True

    signal.signal(signal.SIGINT, on_signal)

    try:
        frame_logger.open()
        ctrl.start()
        print(f"Recording to {out_path} for {duration}s... Press Ctrl+C to stop early.")

        start_time = time.time()
        while not stop_event[0] and (time.time() - start_time) < duration:
            elapsed = time.time() - start_time
            remaining = duration - elapsed
            print(f"\r  Elapsed: {elapsed:.1f}s / {duration:.1f}s  "
                  f"TX={ctrl.can.stats['tx_count']} RX={ctrl.can.stats['rx_count']}", end="")
            time.sleep(0.5)

        print()
    finally:
        ctrl.stop()
        ctrl.can.disconnect()
        frame_logger.close()
        if sim:
            sim.stop()

    print(f"Recording complete: {out_path}")
    print(f"  TX: {ctrl.can.stats['tx_count']}, RX: {ctrl.can.stats['rx_count']}")
    return 0


def cmd_status(args) -> int:
    sim = None
    if args.dry_run:
        sim = SimulatedPCS(pcs_addr=args.pcs_addr)
        sim.start()

    ctrl = _make_controller(args)
    try:
        ctrl.start()
        # Wait for a few status frames
        print("Reading PCS status...")
        time.sleep(1.5)

        s = ctrl.state
        print(f"\n{'='*50}")
        print(f"YSTECH PCS Status (addr=0x{args.pcs_addr:02X})")
        print(f"{'='*50}")
        print(f"  Running State : {s.status.state_name}")
        print(f"  Fault Code    : 0x{s.status.fault_code:04X} ({s.status.fault_description})")
        print(f"\n  DC Voltage    : {s.dc.voltage:.1f} V")
        print(f"  DC Current    : {s.dc.current:.1f} A")
        print(f"  DC Power      : {s.dc.power:.1f} kW")
        print(f"  Inlet Temp    : {s.dc.inlet_temperature:.1f} °C")
        print(f"  Outlet Temp   : {s.capacity_energy.outlet_temperature:.1f} °C")
        print(f"\n  Grid U/V/W    : {s.grid_voltage.u_voltage:.1f} / {s.grid_voltage.v_voltage:.1f} / {s.grid_voltage.w_voltage:.1f} V")
        print(f"  Grid I U/V/W  : {s.grid_current.u_current:.1f} / {s.grid_current.v_current:.1f} / {s.grid_current.w_current:.1f} A")
        print(f"  Power Factor  : {s.grid_current.power_factor:.2f}")
        print(f"  Frequency     : {s.system_power.frequency:.1f} Hz")
        print(f"\n  Active Power  : {s.system_power.active_power:.1f} kW")
        print(f"  Reactive Power: {s.system_power.reactive_power:.1f} kVar")
        print(f"  Apparent Power: {s.system_power.apparent_power:.1f} kVA")
        print(f"\n  Capacity      : {s.capacity_energy.capacity:.1f} Ah")
        print(f"  Energy        : {s.capacity_energy.energy:.1f} Wh")

        if s.dc_hires.voltage > 0:
            print(f"\n  Hi-Res DC V   : {s.dc_hires.voltage:.3f} V")
            print(f"  Hi-Res DC I   : {s.dc_hires.current:.3f} A")
        print(f"{'='*50}")

    finally:
        ctrl.stop()
        ctrl.can.disconnect()
        if sim:
            sim.stop()
    return 0


def cmd_version(args) -> int:
    sim = None
    if args.dry_run:
        sim = SimulatedPCS(pcs_addr=args.pcs_addr)
        sim.start()
        time.sleep(0.3)

    ctrl = _make_controller(args)
    try:
        ctrl.start()
        time.sleep(0.5)
        version = ctrl.read_version()
        if version:
            print(f"ARM Version: HW={version.hw_v}.{version.hw_b}.{version.hw_d}  "
                  f"SW={version.sw_v}.{version.sw_b}.{version.sw_d}")
        else:
            print("Failed to read version (no reply)")
            return 1
    finally:
        ctrl.stop()
        ctrl.can.disconnect()
        if sim:
            sim.stop()
    return 0


def cmd_read_params(args) -> int:
    param_type = getattr(args, "type", 1)
    sim = None
    if args.dry_run:
        sim = SimulatedPCS(pcs_addr=args.pcs_addr)
        sim.start()
        time.sleep(0.3)

    ctrl = _make_controller(args)
    try:
        ctrl.start()
        time.sleep(0.5)
        result = ctrl.read_protection_params(param_type)
        if result:
            print(f"Protection Parameters (type {param_type}):")
            if hasattr(result, "__dataclass_fields__"):
                for f_name, f_val in result.__dataclass_fields__.items():
                    print(f"  {f_name}: {getattr(result, f_name)}")
            else:
                print(f"  {result}")
        else:
            print("Failed to read parameters (no reply)")
            return 1
    finally:
        ctrl.stop()
        ctrl.can.disconnect()
        if sim:
            sim.stop()
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

COMMANDS = {
    "list-interfaces": cmd_list_interfaces,
    "monitor": cmd_monitor,
    "enable": cmd_enable,
    "disable": cmd_disable,
    "set": cmd_set,
    "dump-faults": cmd_dump_faults,
    "reset-faults": cmd_reset_faults,
    "record": cmd_record,
    "status": cmd_status,
    "version": cmd_version,
    "read-params": cmd_read_params,
}


def main(argv: Optional[list] = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    setup_logging(level=args.log_level, logfile=args.log_file)

    handler = COMMANDS.get(args.command)
    if handler is None:
        print(f"Unknown command: {args.command}")
        return 1

    try:
        return handler(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.log_level == "DEBUG":
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
