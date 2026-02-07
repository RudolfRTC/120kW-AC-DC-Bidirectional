"""YSTECH PCS CAN Protocol: Message IDs, signal encoding/decoding, data structures.

Reference: YSTECH_PCS battery test system external CAN communication protocol v1.11
CAN 2.0B extended frame, J1939-based, 250 kbps.

Address allocation:
  0xB4 (180) = Other devices (this controller)
  0xFA (250) = PCS device (default)
  0x00       = Broadcast

CAN ID structure (29-bit extended):
  [28:26] Priority (3 bits)
  [25]    Reserved (1 bit)
  [24]    Data Page (1 bit)
  [23:16] PF - PDU Format (8 bits)
  [15:8]  PS - PDU Specific / target address (8 bits)
  [7:0]   SA - Source Address (8 bits)

All periodic status frames from PCS are sent at 200ms intervals.
CAN timeout: 5 seconds without data from controller triggers CAN1 fault + shutdown.
Data encoding: Big-endian (high byte first) for all multi-byte fields.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CAN_BITRATE = 250_000  # 250 kbps
CAN_PRIORITY = 6
CONTROLLER_ADDR = 0xB4  # "Other devices" (our address)
PCS_DEFAULT_ADDR = 0xFA  # PCS default CAN address
BROADCAST_ADDR = 0x00
HEARTBEAT_INTERVAL_MS = 200  # Frame 26 must be sent every 200ms
CAN_TIMEOUT_S = 5  # PCS reports fault after 5s without RX


# ---------------------------------------------------------------------------
# CAN ID helpers
# ---------------------------------------------------------------------------

def build_can_id(pf: int, ps: int, sa: int, priority: int = CAN_PRIORITY) -> int:
    """Build a 29-bit extended CAN ID from J1939 fields.

    Args:
        pf: PDU Format (8-bit command code).
        ps: PDU Specific / target address (8-bit).
        sa: Source Address (8-bit).
        priority: Message priority (3-bit, default 6).

    Returns:
        29-bit extended CAN arbitration ID.
    """
    return ((priority & 0x07) << 26) | (pf << 16) | (ps << 8) | (sa & 0xFF)


def parse_can_id(can_id: int) -> Dict[str, int]:
    """Parse a 29-bit extended CAN ID into J1939 fields."""
    return {
        "priority": (can_id >> 26) & 0x07,
        "reserved": (can_id >> 25) & 0x01,
        "data_page": (can_id >> 24) & 0x01,
        "pf": (can_id >> 16) & 0xFF,
        "ps": (can_id >> 8) & 0xFF,
        "sa": can_id & 0xFF,
    }


def make_tx_id(pf: int, pcs_addr: int = PCS_DEFAULT_ADDR) -> int:
    """Build CAN ID for a message FROM controller TO PCS."""
    return build_can_id(pf, pcs_addr, CONTROLLER_ADDR)


def make_rx_id(pf: int, pcs_addr: int = PCS_DEFAULT_ADDR) -> int:
    """Build CAN ID for a message FROM PCS TO controller."""
    return build_can_id(pf, CONTROLLER_ADDR, pcs_addr)


# ---------------------------------------------------------------------------
# Working modes (Appendix 1)
# ---------------------------------------------------------------------------

class WorkingMode(IntEnum):
    DC_CONSTANT_VOLTAGE = 0x02
    DC_CONSTANT_VOLTAGE_CURRENT_LIMITING = 0x08
    DC_CONSTANT_CURRENT = 0x21
    DC_CONSTANT_POWER = 0x22
    DC_CONSTANT_RESISTANCE = 0x23
    DC_RAMP_CURRENT = 0x24
    DC_RAMP_POWER = 0x25
    DC_CONSTANT_MAGNIFICATION = 0x26
    DC_RAMP_VOLTAGE = 0x27
    DC_PULSE_CURRENT = 0x28
    DC_CC_CV = 0x29
    DC_PULSE_RESISTANCE = 0x2A
    DC_PULSE_POWER = 0x2B
    DC_INTERNAL_RESISTANCE_TEST = 0x2C
    AC_CONSTANT_POWER = 0x40
    INDEPENDENT_INVERTER = 0x41
    DC_PULSE_VOLTAGE = 0x61
    IDLE = 0x91
    STANDBY = 0x94


# Parameter descriptions per mode: (name, unit, resolution) for params 1-4
MODE_PARAMS: Dict[int, List[Tuple[str, str, float]]] = {
    0x02: [("voltage_setpoint", "V", 0.001)],
    0x08: [
        ("voltage_setpoint", "V", 0.001),
        ("max_charge_current", "A", 0.001),
        ("max_discharge_current", "A", 0.001),
    ],
    0x21: [("current_setpoint", "A", 0.001)],
    0x22: [("power_setpoint", "W", 0.001)],
    0x23: [("resistance_setpoint", "ohm", 0.001)],
    0x24: [
        ("start_current", "A", 0.001),
        ("end_current", "A", 0.001),
        ("cycle_time", "s", 0.001),
    ],
    0x25: [
        ("start_power", "W", 0.001),
        ("end_power", "W", 0.001),
        ("cycle_time", "s", 0.001),
    ],
    0x26: [("magnification", "", 0.001)],
    0x27: [
        ("start_voltage", "V", 0.001),
        ("end_voltage", "V", 0.001),
        ("cycle_time", "s", 0.001),
    ],
    0x28: [
        ("current_1", "A", 0.001),
        ("current_2", "A", 0.001),
        ("cycle_time", "s", 0.01),
        ("duty_cycle", "%", 0.01),
    ],
    0x29: [
        ("voltage_setpoint", "V", 0.001),
        ("current_setpoint", "A", 0.001),
        ("end_current", "A", 0.001),
    ],
    0x2A: [
        ("resistance_1", "ohm", 0.001),
        ("resistance_2", "ohm", 0.001),
        ("cycle_time", "s", 0.01),
        ("duty_cycle", "%", 0.01),
    ],
    0x2B: [
        ("power_1", "W", 0.001),
        ("power_2", "W", 0.001),
        ("cycle_time", "s", 0.01),
        ("duty_cycle", "%", 0.01),
    ],
    0x2C: [
        ("current_setpoint", "A", 0.001),
        ("time_1", "s", 0.001),
        ("time_2", "s", 0.001),
        ("time_3", "s", 0.001),
    ],
    0x40: [
        ("active_power", "W", 0.001),
        ("reactive_power", "Var", 0.001),
    ],
    0x41: [
        ("inverter_voltage", "V", 0.001),
        ("inverter_frequency", "Hz", 0.001),
    ],
    0x61: [
        ("voltage_1", "V", 0.001),
        ("voltage_2", "V", 0.001),
        ("cycle_time", "s", 0.01),
        ("duty_cycle", "%", 0.01),
    ],
    0x91: [],
    0x94: [],
}


# ---------------------------------------------------------------------------
# Running states (from frame 19 documentation)
# ---------------------------------------------------------------------------

class RunningState(IntEnum):
    LONG_PAUSE = 1
    SHORT_STOP = 2
    LONG_IDLE = 3
    SHORT_IDLE = 4
    STOP = 5
    FAULT = 6
    AC_CONSTANT_POWER = 7
    POWER_FAILURE = 8
    SELF_CHECK = 9
    SOFT_START = 10
    CONSTANT_VOLTAGE = 11
    CONSTANT_CURRENT = 12
    STANDBY = 13
    OFF_GRID_INVERTER = 14


# ---------------------------------------------------------------------------
# Fault codes (Appendix 2)
# ---------------------------------------------------------------------------

FAULT_CODES: Dict[int, str] = {
    0x800D: "CAN1 equipment failure",
    0x800E: "CAN2 equipment failure",
    0x800F: "485-1 communication failure",
    0x8010: "485-2 communication failure",
    0x8011: "DSP soft start timeout",
    0x8012: "Emergency stop button pressed",
    0x8013: "Gun head temperature exceeds limit",
    0x8014: "Detection point 1 voltage abnormality",
    0x8015: "Network disconnection",
    # Battery / DC side faults
    1: "Battery voltage too high / over limit",
    2: "Battery voltage low / over limit",
    3: "Battery reverse connection",
    4: "Current over limit",
    5: "Overtemperature fault (>90C)",
    6: "Soft start timeout (>10s)",
    15: "Overcurrent count exceeds limit",
    16: "Overvoltage count exceeds limit",
    17: "Power limit exceeded",
    18: "Emergency stop button pressed",
    26: "Slave failure",
    # AC / grid side faults
    257: "High grid voltage fault (>264V)",
    258: "Low grid voltage fault (<176V)",
    265: "Input voltage negative phase sequence",
    280: "Radiator temperature high fault (>90C)",
}


def fault_description(code: int) -> str:
    """Return human-readable fault description for a code."""
    if code == 0:
        return "No fault"
    return FAULT_CODES.get(code, f"Internal failure (code 0x{code:04X}) - contact factory")


# ---------------------------------------------------------------------------
# Data structures for decoded messages
# ---------------------------------------------------------------------------

@dataclass
class ProtectionParams1:
    """Frame 2 / Frame 5: DC voltage and current limits."""
    max_output_voltage: float = 0.0   # V, resolution 0.1V
    min_output_voltage: float = 0.0   # V, resolution 0.1V
    max_charge_current: float = 0.0   # A, resolution 0.1A
    max_discharge_current: float = 0.0  # A, resolution 0.1A


@dataclass
class ProtectionParams2:
    """Frame 3 / Frame 6: Power and AC voltage limits."""
    max_charge_power: float = 0.0      # kW, resolution 0.1kW
    max_discharge_power: float = 0.0   # kW, resolution 0.1kW
    ac_voltage_upper: float = 0.0      # V, resolution 0.1V
    ac_voltage_lower: float = 0.0      # V, resolution 0.1V


@dataclass
class ProtectionParams3:
    """Frame 4 / Frame 7: Frequency limits."""
    discharge_freq_upper: float = 0.0  # Hz, resolution 0.1Hz
    charge_freq_lower: float = 0.0     # Hz, resolution 0.1Hz
    ac_freq_upper: float = 0.0         # Hz, resolution 1Hz
    ac_freq_lower: float = 0.0         # Hz, resolution 1Hz


@dataclass
class DCData:
    """Frame 17 (0x1811): Real-time DC data."""
    voltage: float = 0.0         # V, resolution 0.1V, offset 0
    current: float = 0.0         # A, resolution 0.1A, offset -1000A
    power: float = 0.0           # kW, resolution 0.1kW, offset 0
    inlet_temperature: float = 0.0  # °C, resolution 0.1°C, offset -50°C


@dataclass
class CapacityEnergy:
    """Frame 18 (0x1812): Ampere-hour and watt-hour data."""
    capacity: float = 0.0            # Ah, resolution 0.1Ah
    energy: float = 0.0              # Wh, resolution 0.1Wh (4 bytes)
    outlet_temperature: float = 0.0  # °C, resolution 0.1°C, offset -50°C


@dataclass
class StatusData:
    """Frame 19 (0x1813): Running state and fault code."""
    running_state: int = 0
    fault_code: int = 0

    @property
    def state_name(self) -> str:
        try:
            return RunningState(self.running_state).name
        except ValueError:
            return f"UNKNOWN({self.running_state})"

    @property
    def fault_description(self) -> str:
        return fault_description(self.fault_code)

    @property
    def is_fault(self) -> bool:
        return self.running_state == RunningState.FAULT or self.fault_code != 0


@dataclass
class GridVoltage:
    """Frame 20 (0x1814): Three-phase grid voltages."""
    u_voltage: float = 0.0  # V, resolution 0.1V
    v_voltage: float = 0.0  # V
    w_voltage: float = 0.0  # V


@dataclass
class GridCurrent:
    """Frame 21 (0x1815): Three-phase grid currents + power factor."""
    u_current: float = 0.0  # A, resolution 0.1A
    v_current: float = 0.0  # A
    w_current: float = 0.0  # A
    power_factor: float = 0.0  # resolution 0.1


@dataclass
class SystemPower:
    """Frame 22 (0x1816): System power data."""
    active_power: float = 0.0    # kW, resolution 0.1kW
    reactive_power: float = 0.0  # kVar, resolution 0.1kVar
    apparent_power: float = 0.0  # kVA, resolution 0.1kVA
    frequency: float = 0.0      # Hz, resolution 0.1Hz


@dataclass
class LoadVoltage:
    """Frame 23 (0x1817): Three-phase load voltages."""
    u_voltage: float = 0.0  # V, resolution 0.1V
    v_voltage: float = 0.0
    w_voltage: float = 0.0


@dataclass
class LoadCurrent:
    """Frame 24 (0x1818): Three-phase load currents."""
    u_current: float = 0.0  # A, resolution 0.1A
    v_current: float = 0.0
    w_current: float = 0.0


@dataclass
class LoadPower:
    """Frame 25 (0x1819): Load side power data."""
    active_power: float = 0.0    # kW
    reactive_power: float = 0.0  # kVar
    apparent_power: float = 0.0  # kVA


@dataclass
class PhasePower:
    """Frames 0x1823/0x1824/0x1825: Per-phase power data."""
    phase: str = ""
    active_power: float = 0.0    # kW, resolution 0.1kW
    reactive_power: float = 0.0  # kVar, resolution 0.1kVar
    apparent_power: float = 0.0  # kVA, resolution 0.1kVA


@dataclass
class HighResDC:
    """Frame 0x1839: High-resolution DC voltage and current."""
    voltage: float = 0.0  # V, resolution 0.001V (4 bytes)
    current: float = 0.0  # A, resolution 0.001A, offset -1000A (4 bytes)


@dataclass
class IOAndAD:
    """Frame 32 (0x1820): IO signals and AD sample values."""
    io1: int = 0
    io2: int = 0
    io3: int = 0
    io4: int = 0
    ad1_voltage: float = 0.0  # V, resolution 0.001V
    ad2_voltage: float = 0.0  # V, resolution 0.001V


@dataclass
class VersionInfo:
    """Frames 0x1834/0x1835: ARM and DSP version information."""
    hw_v: int = 0
    hw_b: int = 0
    hw_d: int = 0
    sw_v: int = 0
    sw_b: int = 0
    sw_d: int = 0


@dataclass
class PCSState:
    """Aggregated PCS state from all periodic frames."""
    dc: DCData = field(default_factory=DCData)
    dc_hires: HighResDC = field(default_factory=HighResDC)
    capacity_energy: CapacityEnergy = field(default_factory=CapacityEnergy)
    status: StatusData = field(default_factory=StatusData)
    grid_voltage: GridVoltage = field(default_factory=GridVoltage)
    grid_current: GridCurrent = field(default_factory=GridCurrent)
    system_power: SystemPower = field(default_factory=SystemPower)
    load_voltage: LoadVoltage = field(default_factory=LoadVoltage)
    load_current: LoadCurrent = field(default_factory=LoadCurrent)
    load_power: LoadPower = field(default_factory=LoadPower)
    phase_a_power: PhasePower = field(default_factory=lambda: PhasePower(phase="A"))
    phase_b_power: PhasePower = field(default_factory=lambda: PhasePower(phase="B"))
    phase_c_power: PhasePower = field(default_factory=lambda: PhasePower(phase="C"))
    io_ad: IOAndAD = field(default_factory=IOAndAD)


# ---------------------------------------------------------------------------
# Encoding helpers (controller -> PCS)
# ---------------------------------------------------------------------------

def _u16_be(value: int) -> bytes:
    """Encode unsigned 16-bit big-endian."""
    return struct.pack(">H", value & 0xFFFF)


def _i32_be(value: int) -> bytes:
    """Encode signed 32-bit big-endian."""
    return struct.pack(">i", value)


def _u32_be(value: int) -> bytes:
    """Encode unsigned 32-bit big-endian."""
    return struct.pack(">I", value & 0xFFFFFFFF)


def _pad8(data: bytes) -> bytes:
    """Pad data to 8 bytes with zeros."""
    return data.ljust(8, b"\x00")


def encode_read_protection_params(param_type: int, pcs_addr: int = PCS_DEFAULT_ADDR) -> Tuple[int, bytes]:
    """Frame 1: Read PCS protection parameters.

    Args:
        param_type: 0x01=voltage/current limits, 0x02=power/AC limits, 0x03=frequency limits.
        pcs_addr: Target PCS address.

    Returns:
        Tuple of (CAN ID, 8-byte data).
    """
    can_id = make_tx_id(0x01, pcs_addr)
    data = _pad8(bytes([param_type]))
    return can_id, data


def encode_set_protection_params1(
    max_output_v: float,
    min_output_v: float,
    max_charge_a: float,
    max_discharge_a: float,
    pcs_addr: int = PCS_DEFAULT_ADDR,
) -> Tuple[int, bytes]:
    """Frame 5: Set protection parameter 1 (DC voltage/current limits).

    All values in engineering units, converted internally with 0.1 resolution.
    """
    can_id = make_tx_id(0x05, pcs_addr)
    data = (
        _u16_be(int(max_output_v / 0.1))
        + _u16_be(int(min_output_v / 0.1))
        + _u16_be(int(max_charge_a / 0.1))
        + _u16_be(int(max_discharge_a / 0.1))
    )
    return can_id, data


def encode_set_protection_params2(
    max_charge_kw: float,
    max_discharge_kw: float,
    ac_v_upper: float,
    ac_v_lower: float,
    pcs_addr: int = PCS_DEFAULT_ADDR,
) -> Tuple[int, bytes]:
    """Frame 6: Set protection parameter 2 (power/AC voltage limits)."""
    can_id = make_tx_id(0x06, pcs_addr)
    data = (
        _u16_be(int(max_charge_kw / 0.1))
        + _u16_be(int(max_discharge_kw / 0.1))
        + _u16_be(int(ac_v_upper / 0.1))
        + _u16_be(int(ac_v_lower / 0.1))
    )
    return can_id, data


def encode_set_protection_params3(
    discharge_freq_upper: float,
    charge_freq_lower: float,
    ac_freq_upper: float,
    ac_freq_lower: float,
    pcs_addr: int = PCS_DEFAULT_ADDR,
) -> Tuple[int, bytes]:
    """Frame 7: Set protection parameter 3 (frequency limits)."""
    can_id = make_tx_id(0x07, pcs_addr)
    data = (
        _u16_be(int(discharge_freq_upper / 0.1))
        + _u16_be(int(charge_freq_lower / 0.1))
        + bytes([int(ac_freq_upper), int(ac_freq_lower)])
        + b"\x00\x00"
    )
    return can_id, data


def encode_set_time(
    year: int, month: int, day: int,
    hour: int, minute: int, second: int,
    pcs_addr: int = PCS_DEFAULT_ADDR,
) -> Tuple[int, bytes]:
    """Frame 9: Set PCS device time."""
    can_id = make_tx_id(0x09, pcs_addr)
    data = _u16_be(year) + bytes([month, day, hour, minute, second, 0])
    return can_id, data


def encode_set_working_mode(mode: int, pcs_addr: int = PCS_DEFAULT_ADDR) -> Tuple[int, bytes]:
    """Frame 11: Set working mode (mode change requires shutdown first)."""
    can_id = make_tx_id(0x0B, pcs_addr)
    data = _pad8(bytes([mode]))
    return can_id, data


def encode_set_mode_params12(
    param1: float,
    param2: float,
    mode: int,
    pcs_addr: int = PCS_DEFAULT_ADDR,
) -> Tuple[int, bytes]:
    """Frame 12: Set mode parameters 1 and 2 (each 32-bit, resolution per mode)."""
    params_info = MODE_PARAMS.get(mode, [])
    res1 = params_info[0][2] if len(params_info) > 0 else 0.001
    res2 = params_info[1][2] if len(params_info) > 1 else 0.001
    can_id = make_tx_id(0x0C, pcs_addr)
    raw1 = int(param1 / res1)
    raw2 = int(param2 / res2)
    data = _i32_be(raw1) + _i32_be(raw2)
    return can_id, data


def encode_set_mode_params34(
    param3: float,
    param4: float,
    mode: int,
    pcs_addr: int = PCS_DEFAULT_ADDR,
) -> Tuple[int, bytes]:
    """Frame 13: Set mode parameters 3 and 4 (each 32-bit, resolution per mode)."""
    params_info = MODE_PARAMS.get(mode, [])
    res3 = params_info[2][2] if len(params_info) > 2 else 0.001
    res4 = params_info[3][2] if len(params_info) > 3 else 0.001
    can_id = make_tx_id(0x0D, pcs_addr)
    raw3 = int(param3 / res3)
    raw4 = int(param4 / res4)
    data = _i32_be(raw3) + _i32_be(raw4)
    return can_id, data


def encode_start_stop(
    start: bool,
    clear_fault: bool = False,
    auto_start: bool = False,
    pcs_addr: int = PCS_DEFAULT_ADDR,
) -> Tuple[int, bytes]:
    """Frame 15: Start/stop command, fault clearing, power-on self-start flag.

    NOTE: When modifying one field, others must keep their original values.
    """
    can_id = make_tx_id(0x0F, pcs_addr)
    data = _pad8(bytes([
        1 if start else 0,
        1 if clear_fault else 0,
        1 if auto_start else 0,
    ]))
    return can_id, data


def encode_heartbeat(
    dc_voltage: float = 0.0,
    dc_current: float = 0.0,
    running_state: int = 0x02,
    pcs_addr: int = PCS_DEFAULT_ADDR,
) -> Tuple[int, bytes]:
    """Frame 26 (0x181A): Heartbeat / external device data sent to PCS every 200ms.

    Args:
        dc_voltage: DC voltage in V (0 if not measured), resolution 0.1V.
        dc_current: DC current in A, resolution 0.1A, offset +1000A.
        running_state: 0x01=shutdown, 0x02=running, 0x03=fault.
    """
    can_id = make_tx_id(0x1A, pcs_addr)
    raw_v = int(dc_voltage / 0.1)
    raw_i = int((dc_current + 1000.0) / 0.1)  # offset +1000A
    data = _u16_be(raw_v) + _u16_be(raw_i) + bytes([running_state]) + b"\x00\x00\x00"
    return can_id, data


def encode_set_bus_voltage_reactive(
    bus_voltage: float,
    reactive_power: float,
    pcs_addr: int = PCS_DEFAULT_ADDR,
) -> Tuple[int, bytes]:
    """Frame 27 (0x181B): Set bus voltage and reactive power."""
    can_id = make_tx_id(0x1B, pcs_addr)
    raw_v = int(bus_voltage / 0.1)
    raw_q = int(reactive_power / 0.1)
    data = _u16_be(raw_v) + _u16_be(raw_q) + b"\x00\x00\x00\x00"
    return can_id, data


def encode_set_io(
    io1: int, io2: int, io3: int, io4: int,
    pcs_addr: int = PCS_DEFAULT_ADDR,
) -> Tuple[int, bytes]:
    """Frame 28 (0x181F): Set IOBUS output (each 0 or 1)."""
    can_id = make_tx_id(0x1F, pcs_addr)
    data = bytes([io1 & 1, io2 & 1, io3 & 1, io4 & 1]) + b"\x00\x00\x00\x00"
    return can_id, data


def encode_set_split_phase_enable(
    enable: bool,
    pcs_addr: int = PCS_DEFAULT_ADDR,
) -> Tuple[int, bytes]:
    """Frame 0x1826: Enable/disable split phase power control."""
    can_id = make_tx_id(0x26, pcs_addr)
    data = _pad8(bytes([1 if enable else 0]))
    return can_id, data


def encode_set_inverter_phase(
    phase: int,
    pcs_addr: int = PCS_DEFAULT_ADDR,
) -> Tuple[int, bytes]:
    """Frame 0x1828: Set inverter phase selection.

    Values: 7=A-host, 8=B-host, 9=C-host, 10=A-slave, 11=B-slave, 12=C-slave.
    """
    can_id = make_tx_id(0x28, pcs_addr)
    data = _pad8(bytes([phase]))
    return can_id, data


def encode_set_reactive_control(
    mode: int,
    power_factor: float = 1.0,
    pcs_addr: int = PCS_DEFAULT_ADDR,
) -> Tuple[int, bytes]:
    """Frame 0x182A: Set reactive power control mode and power factor.

    mode: 0=reactive power, 1=power factor.
    power_factor: -0.999 to 1.000, resolution 0.001.
    """
    can_id = make_tx_id(0x2A, pcs_addr)
    raw_pf = int(power_factor / 0.001)
    data = bytes([mode]) + struct.pack(">h", raw_pf) + b"\x00\x00\x00\x00\x00"
    return can_id, data


def encode_set_grid_mode(
    mode: int,
    pcs_addr: int = PCS_DEFAULT_ADDR,
) -> Tuple[int, bytes]:
    """Frame 0x182C: Set on/off grid mode. 0=disable, 1=automatic switching."""
    can_id = make_tx_id(0x2C, pcs_addr)
    data = _pad8(bytes([mode]))
    return can_id, data


def encode_set_module_parallel(
    mode: int,
    num_modules: int,
    hall_ratio: int,
    pcs_addr: int = PCS_DEFAULT_ADDR,
) -> Tuple[int, bytes]:
    """Frame 0x182E: Set module parallel mode.

    mode: 0=single, 1=host, 2=slave.
    num_modules: 1-10.
    hall_ratio: Hall current sensor variable ratio.
    """
    can_id = make_tx_id(0x2E, pcs_addr)
    data = bytes([mode, num_modules]) + _u16_be(hall_ratio) + b"\x00\x00\x00\x00"
    return can_id, data


def encode_set_phase_power(
    phase_a_kw: float,
    phase_b_kw: float,
    phase_c_kw: float,
    pcs_addr: int = PCS_DEFAULT_ADDR,
) -> Tuple[int, bytes]:
    """Frame 0x1821: Set A/B/C phase active power (resolution 0.1kW)."""
    can_id = make_tx_id(0x21, pcs_addr)
    data = (
        _u16_be(int(phase_a_kw / 0.1))
        + _u16_be(int(phase_b_kw / 0.1))
        + _u16_be(int(phase_c_kw / 0.1))
        + b"\x00\x00"
    )
    return can_id, data


def encode_read_special_data(
    data_type: int,
    pcs_addr: int = PCS_DEFAULT_ADDR,
) -> Tuple[int, bytes]:
    """Frame 30 (0x181D): Read special data from PCS.

    data_type: 0x01-0x0B (bus voltage, IO, split phase, inverter phase, etc.)
    """
    can_id = make_tx_id(0x1D, pcs_addr)
    data = _pad8(bytes([data_type]))
    return can_id, data


# ---------------------------------------------------------------------------
# Decoding helpers (PCS -> controller)
# ---------------------------------------------------------------------------

def _u16(data: bytes, offset: int) -> int:
    """Decode unsigned 16-bit big-endian from data at offset."""
    return struct.unpack_from(">H", data, offset)[0]


def _i16(data: bytes, offset: int) -> int:
    """Decode signed 16-bit big-endian from data at offset."""
    return struct.unpack_from(">h", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    """Decode unsigned 32-bit big-endian from data at offset."""
    return struct.unpack_from(">I", data, offset)[0]


def _i32(data: bytes, offset: int) -> int:
    """Decode signed 32-bit big-endian from data at offset."""
    return struct.unpack_from(">i", data, offset)[0]


def decode_protection_params1(data: bytes) -> ProtectionParams1:
    """Decode Frame 2 (0x1802): Protection parameter 1 reply."""
    return ProtectionParams1(
        max_output_voltage=_u16(data, 0) * 0.1,
        min_output_voltage=_u16(data, 2) * 0.1,
        max_charge_current=_u16(data, 4) * 0.1,
        max_discharge_current=_u16(data, 6) * 0.1,
    )


def decode_protection_params2(data: bytes) -> ProtectionParams2:
    """Decode Frame 3 (0x1803): Protection parameter 2 reply."""
    return ProtectionParams2(
        max_charge_power=_u16(data, 0) * 0.1,
        max_discharge_power=_u16(data, 2) * 0.1,
        ac_voltage_upper=_u16(data, 4) * 0.1,
        ac_voltage_lower=_u16(data, 6) * 0.1,
    )


def decode_protection_params3(data: bytes) -> ProtectionParams3:
    """Decode Frame 4 (0x1804): Protection parameter 3 reply."""
    return ProtectionParams3(
        discharge_freq_upper=_u16(data, 0) * 0.1,
        charge_freq_lower=_u16(data, 2) * 0.1,
        ac_freq_upper=data[4] * 1.0,
        ac_freq_lower=data[5] * 1.0,
    )


def decode_dc_data(data: bytes) -> DCData:
    """Decode Frame 17 (0x1811): Real-time DC data."""
    return DCData(
        voltage=_u16(data, 0) * 0.1,
        current=_u16(data, 2) * 0.1 - 1000.0,
        power=_u16(data, 4) * 0.1,
        inlet_temperature=_u16(data, 6) * 0.1 - 50.0,
    )


def decode_capacity_energy(data: bytes) -> CapacityEnergy:
    """Decode Frame 18 (0x1812): Capacity and energy data."""
    return CapacityEnergy(
        capacity=_u16(data, 0) * 0.1,
        energy=_u32(data, 2) * 0.1,
        outlet_temperature=_u16(data, 6) * 0.1 - 50.0,
    )


def decode_status(data: bytes) -> StatusData:
    """Decode Frame 19 (0x1813): Running state and fault code."""
    return StatusData(
        running_state=data[0],
        fault_code=_u16(data, 2),
    )


def decode_grid_voltage(data: bytes) -> GridVoltage:
    """Decode Frame 20 (0x1814): Grid side three-phase voltages."""
    return GridVoltage(
        u_voltage=_u16(data, 0) * 0.1,
        v_voltage=_u16(data, 2) * 0.1,
        w_voltage=_u16(data, 4) * 0.1,
    )


def decode_grid_current(data: bytes) -> GridCurrent:
    """Decode Frame 21 (0x1815): Grid side three-phase currents + PF."""
    return GridCurrent(
        u_current=_u16(data, 0) * 0.1,
        v_current=_u16(data, 2) * 0.1,
        w_current=_u16(data, 4) * 0.1,
        power_factor=_i16(data, 6) * 0.1,
    )


def decode_system_power(data: bytes) -> SystemPower:
    """Decode Frame 22 (0x1816): System power data."""
    return SystemPower(
        active_power=_u16(data, 0) * 0.1,
        reactive_power=_u16(data, 2) * 0.1,
        apparent_power=_u16(data, 4) * 0.1,
        frequency=_u16(data, 6) * 0.1,
    )


def decode_load_voltage(data: bytes) -> LoadVoltage:
    """Decode Frame 23 (0x1817): Load side three-phase voltages."""
    return LoadVoltage(
        u_voltage=_u16(data, 0) * 0.1,
        v_voltage=_u16(data, 2) * 0.1,
        w_voltage=_u16(data, 4) * 0.1,
    )


def decode_load_current(data: bytes) -> LoadCurrent:
    """Decode Frame 24 (0x1818): Load side three-phase currents."""
    return LoadCurrent(
        u_current=_u16(data, 0) * 0.1,
        v_current=_u16(data, 2) * 0.1,
        w_current=_u16(data, 4) * 0.1,
    )


def decode_load_power(data: bytes) -> LoadPower:
    """Decode Frame 25 (0x1819): Load side power data."""
    return LoadPower(
        active_power=_u16(data, 0) * 0.1,
        reactive_power=_u16(data, 2) * 0.1,
        apparent_power=_u16(data, 4) * 0.1,
    )


def decode_phase_power(data: bytes, phase: str) -> PhasePower:
    """Decode Frames 0x1823/0x1824/0x1825: Per-phase power data."""
    return PhasePower(
        phase=phase,
        active_power=_u16(data, 0) * 0.1,
        reactive_power=_u16(data, 2) * 0.1,
        apparent_power=_u16(data, 4) * 0.1,
    )


def decode_high_res_dc(data: bytes) -> HighResDC:
    """Decode Frame 0x1839: High-resolution DC voltage and current (4 bytes each)."""
    return HighResDC(
        voltage=_u32(data, 0) * 0.001,
        current=_u32(data, 4) * 0.001 - 1000.0,
    )


def decode_io_ad(data: bytes) -> IOAndAD:
    """Decode Frame 32 (0x1820): IO signals and AD sample values."""
    return IOAndAD(
        io1=data[0],
        io2=data[1],
        io3=data[2],
        io4=data[3],
        ad1_voltage=_u16(data, 4) * 0.001,
        ad2_voltage=_u16(data, 6) * 0.001,
    )


def decode_set_reply(data: bytes) -> bool:
    """Decode generic set-command reply (Frames 8, 10, 14, 16, 29).

    Returns True if success (byte[0] or byte[1] == 0x01 depending on frame).
    """
    # Frame 8/29: byte[0]=type, byte[1]=result; Frame 10/14/16: byte[0]=result
    # For simplicity check both positions for 0x01
    return data[0] == 0x01 or (len(data) > 1 and data[1] == 0x01)


def decode_version(data: bytes) -> VersionInfo:
    """Decode Frames 0x1834/0x1835: Version information."""
    return VersionInfo(
        hw_v=data[0],
        hw_b=data[1],
        hw_d=data[2],
        sw_v=data[3],
        sw_b=data[4],
        sw_d=data[5],
    )


# ---------------------------------------------------------------------------
# Message dispatcher: decode any RX message by PF
# ---------------------------------------------------------------------------

# Map of PF code -> (decoder_function, field_name_in_PCSState_or_None)
_RX_DECODERS: Dict[int, tuple] = {
    0x02: (decode_protection_params1, None),
    0x03: (decode_protection_params2, None),
    0x04: (decode_protection_params3, None),
    0x08: (decode_set_reply, None),
    0x0A: (decode_set_reply, None),
    0x0E: (decode_set_reply, None),
    0x10: (decode_set_reply, None),
    0x11: (decode_dc_data, "dc"),
    0x12: (decode_capacity_energy, "capacity_energy"),
    0x13: (decode_status, "status"),
    0x14: (decode_grid_voltage, "grid_voltage"),
    0x15: (decode_grid_current, "grid_current"),
    0x16: (decode_system_power, "system_power"),
    0x17: (decode_load_voltage, "load_voltage"),
    0x18: (decode_load_current, "load_current"),
    0x19: (decode_load_power, "load_power"),
    0x1C: (decode_set_reply, None),
    0x20: (decode_io_ad, "io_ad"),
    0x39: (decode_high_res_dc, "dc_hires"),
}


def decode_rx_message(can_id: int, data: bytes) -> Tuple[Optional[str], Any]:
    """Decode a received CAN message.

    Args:
        can_id: 29-bit extended CAN ID.
        data: 8-byte message data.

    Returns:
        Tuple of (pf_name_string, decoded_data_object).
        Returns (None, None) if PF is not recognized.
    """
    fields = parse_can_id(can_id)
    pf = fields["pf"]

    # Phase power frames
    if pf == 0x23:
        return "phase_a_power", decode_phase_power(data, "A")
    if pf == 0x24:
        return "phase_b_power", decode_phase_power(data, "B")
    if pf == 0x25:
        return "phase_c_power", decode_phase_power(data, "C")
    # Version frames
    if pf == 0x34:
        return "arm_version", decode_version(data)
    if pf == 0x35:
        return "dsp_version", decode_version(data)

    entry = _RX_DECODERS.get(pf)
    if entry is None:
        return None, None

    decoder, state_field = entry
    decoded = decoder(data)
    name = state_field or f"pf_0x{pf:02X}"
    return name, decoded


# PF code -> human readable name
PF_NAMES: Dict[int, str] = {
    0x01: "ReadProtectionParams",
    0x02: "ProtectionParams1Reply",
    0x03: "ProtectionParams2Reply",
    0x04: "ProtectionParams3Reply",
    0x05: "SetProtectionParams1",
    0x06: "SetProtectionParams2",
    0x07: "SetProtectionParams3",
    0x08: "SetProtectionReply",
    0x09: "SetTime",
    0x0A: "SetTimeReply",
    0x0B: "SetWorkingMode",
    0x0C: "SetModeParams12",
    0x0D: "SetModeParams34",
    0x0E: "SetModeReply",
    0x0F: "StartStop",
    0x10: "StartStopReply",
    0x11: "DCData",
    0x12: "CapacityEnergy",
    0x13: "Status",
    0x14: "GridVoltage",
    0x15: "GridCurrent",
    0x16: "SystemPower",
    0x17: "LoadVoltage",
    0x18: "LoadCurrent",
    0x19: "LoadPower",
    0x1A: "Heartbeat",
    0x1B: "SetBusVoltageReactive",
    0x1C: "SpecialDataReply",
    0x1D: "ReadSpecialData",
    0x1E: "StoredBusVReactive",
    0x1F: "SetIOBUS",
    0x20: "IOAndAD",
    0x21: "SetPhaseActivePower",
    0x22: "SetPhaseReactivePower",
    0x23: "PhaseAPower",
    0x24: "PhaseBPower",
    0x25: "PhaseCPower",
    0x26: "SetSplitPhaseEnable",
    0x27: "SplitPhaseEnableReply",
    0x28: "SetInverterPhase",
    0x29: "InverterPhaseReply",
    0x2A: "SetReactiveControl",
    0x2B: "ReactiveControlReply",
    0x2C: "SetGridMode",
    0x2D: "GridModeReply",
    0x2E: "SetModuleParallel",
    0x2F: "ModuleParallelReply",
    0x30: "SetChannelParallel",
    0x31: "ChannelParallelReply",
    0x32: "SetBusParallel",
    0x33: "BusParallelReply",
    0x34: "ARMVersion",
    0x35: "DSPVersion",
    0x36: "ModeParamsReply",
    0x37: "Params12Reply",
    0x38: "Params34Reply",
    0x39: "HighResDC",
}


def pf_name(pf_code: int) -> str:
    """Get human-readable name for a PF code."""
    return PF_NAMES.get(pf_code, f"Unknown_0x{pf_code:02X}")
