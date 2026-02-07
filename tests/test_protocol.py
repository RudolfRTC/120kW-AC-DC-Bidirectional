"""Tests for the YSTECH PCS CAN protocol encoding and decoding."""

import struct
import pytest

from dcdc_app.protocol import (
    CAN_BITRATE,
    CONTROLLER_ADDR,
    FAULT_CODES,
    PCS_DEFAULT_ADDR,
    RunningState,
    WorkingMode,
    build_can_id,
    decode_capacity_energy,
    decode_dc_data,
    decode_grid_current,
    decode_grid_voltage,
    decode_high_res_dc,
    decode_io_ad,
    decode_load_current,
    decode_load_power,
    decode_load_voltage,
    decode_phase_power,
    decode_protection_params1,
    decode_protection_params2,
    decode_protection_params3,
    decode_rx_message,
    decode_set_reply,
    decode_status,
    decode_system_power,
    decode_version,
    encode_heartbeat,
    encode_read_protection_params,
    encode_read_special_data,
    encode_set_mode_params12,
    encode_set_mode_params34,
    encode_set_protection_params1,
    encode_set_protection_params2,
    encode_set_protection_params3,
    encode_set_time,
    encode_set_working_mode,
    encode_start_stop,
    encode_set_io,
    encode_set_bus_voltage_reactive,
    encode_set_split_phase_enable,
    encode_set_inverter_phase,
    encode_set_reactive_control,
    encode_set_grid_mode,
    encode_set_module_parallel,
    encode_set_phase_power,
    fault_description,
    make_rx_id,
    make_tx_id,
    parse_can_id,
    pf_name,
)


class TestCANIDConstruction:
    def test_bitrate(self):
        assert CAN_BITRATE == 250_000

    def test_build_can_id(self):
        # Priority=6, R=0, DP=0, PF=0x01, PS=0xFA, SA=0xB4
        can_id = build_can_id(0x01, 0xFA, 0xB4, priority=6)
        fields = parse_can_id(can_id)
        assert fields["priority"] == 6
        assert fields["pf"] == 0x01
        assert fields["ps"] == 0xFA
        assert fields["sa"] == 0xB4

    def test_make_tx_id(self):
        # TX: controller -> PCS
        can_id = make_tx_id(0x0F, PCS_DEFAULT_ADDR)
        fields = parse_can_id(can_id)
        assert fields["pf"] == 0x0F
        assert fields["ps"] == PCS_DEFAULT_ADDR
        assert fields["sa"] == CONTROLLER_ADDR

    def test_make_rx_id(self):
        # RX: PCS -> controller
        can_id = make_rx_id(0x11, PCS_DEFAULT_ADDR)
        fields = parse_can_id(can_id)
        assert fields["pf"] == 0x11
        assert fields["ps"] == CONTROLLER_ADDR
        assert fields["sa"] == PCS_DEFAULT_ADDR

    def test_id_roundtrip(self):
        for pf in [0x01, 0x11, 0x1A, 0x39]:
            can_id = build_can_id(pf, 0xFA, 0xB4)
            fields = parse_can_id(can_id)
            assert fields["pf"] == pf
            assert fields["ps"] == 0xFA
            assert fields["sa"] == 0xB4

    def test_parse_can_id_reserved_dp(self):
        # Reserved and data page should be 0 for all our messages
        can_id = make_tx_id(0x01)
        fields = parse_can_id(can_id)
        assert fields["reserved"] == 0
        assert fields["data_page"] == 0


class TestEncoders:
    def test_encode_read_protection_params(self):
        can_id, data = encode_read_protection_params(0x01)
        assert len(data) == 8
        assert data[0] == 0x01
        assert all(b == 0 for b in data[1:])
        fields = parse_can_id(can_id)
        assert fields["pf"] == 0x01

    def test_encode_set_protection_params1(self):
        can_id, data = encode_set_protection_params1(800.0, 50.0, 150.0, 150.0)
        fields = parse_can_id(can_id)
        assert fields["pf"] == 0x05
        # 800.0V / 0.1 = 8000
        assert struct.unpack_from(">H", data, 0)[0] == 8000
        # 50.0V / 0.1 = 500
        assert struct.unpack_from(">H", data, 2)[0] == 500
        # 150.0A / 0.1 = 1500
        assert struct.unpack_from(">H", data, 4)[0] == 1500
        assert struct.unpack_from(">H", data, 6)[0] == 1500

    def test_encode_set_protection_params2(self):
        can_id, data = encode_set_protection_params2(120.0, 120.0, 264.0, 176.0)
        fields = parse_can_id(can_id)
        assert fields["pf"] == 0x06
        assert struct.unpack_from(">H", data, 0)[0] == 1200  # 120kW
        assert struct.unpack_from(">H", data, 4)[0] == 2640  # 264V

    def test_encode_set_protection_params3(self):
        can_id, data = encode_set_protection_params3(55.0, 45.0, 55, 45)
        fields = parse_can_id(can_id)
        assert fields["pf"] == 0x07
        assert struct.unpack_from(">H", data, 0)[0] == 550  # 55Hz / 0.1
        assert data[4] == 55  # 1Hz resolution
        assert data[5] == 45

    def test_encode_set_time(self):
        can_id, data = encode_set_time(2024, 6, 15, 10, 30, 45)
        fields = parse_can_id(can_id)
        assert fields["pf"] == 0x09
        year = struct.unpack_from(">H", data, 0)[0]
        assert year == 2024
        assert data[2] == 6   # month
        assert data[3] == 15  # day
        assert data[4] == 10  # hour
        assert data[5] == 30  # minute
        assert data[6] == 45  # second

    def test_encode_set_working_mode(self):
        can_id, data = encode_set_working_mode(WorkingMode.DC_CONSTANT_VOLTAGE.value)
        fields = parse_can_id(can_id)
        assert fields["pf"] == 0x0B
        assert data[0] == 0x02

    def test_encode_set_mode_params12(self):
        # DC constant voltage: param1 = voltage(0.001V)
        can_id, data = encode_set_mode_params12(400.0, 0.0, 0x02)
        fields = parse_can_id(can_id)
        assert fields["pf"] == 0x0C
        raw1 = struct.unpack_from(">i", data, 0)[0]
        assert raw1 == 400000  # 400V / 0.001 = 400000

    def test_encode_set_mode_params34(self):
        # DC ramp current: param3 = cycle_time(0.001s)
        can_id, data = encode_set_mode_params34(10.0, 0.0, 0x24)
        fields = parse_can_id(can_id)
        assert fields["pf"] == 0x0D
        raw3 = struct.unpack_from(">i", data, 0)[0]
        assert raw3 == 10000  # 10s / 0.001

    def test_encode_start(self):
        can_id, data = encode_start_stop(start=True)
        fields = parse_can_id(can_id)
        assert fields["pf"] == 0x0F
        assert data[0] == 1  # start
        assert data[1] == 0  # no clear fault
        assert data[2] == 0  # no auto start

    def test_encode_stop(self):
        can_id, data = encode_start_stop(start=False)
        assert data[0] == 0

    def test_encode_start_clear_faults(self):
        can_id, data = encode_start_stop(start=True, clear_fault=True, auto_start=True)
        assert data[0] == 1  # start
        assert data[1] == 1  # clear fault
        assert data[2] == 1  # auto start

    def test_encode_heartbeat(self):
        can_id, data = encode_heartbeat(400.0, 50.0, 0x02)
        fields = parse_can_id(can_id)
        assert fields["pf"] == 0x1A
        raw_v = struct.unpack_from(">H", data, 0)[0]
        assert raw_v == 4000  # 400V / 0.1
        raw_i = struct.unpack_from(">H", data, 2)[0]
        assert raw_i == 10500  # (50 + 1000) / 0.1
        assert data[4] == 0x02  # running

    def test_encode_heartbeat_zero_current(self):
        can_id, data = encode_heartbeat(0.0, 0.0, 0x01)
        raw_i = struct.unpack_from(">H", data, 2)[0]
        assert raw_i == 10000  # (0 + 1000) / 0.1 = 10000
        assert data[4] == 0x01  # shutdown

    def test_encode_set_bus_voltage_reactive(self):
        can_id, data = encode_set_bus_voltage_reactive(750.0, 10.0)
        fields = parse_can_id(can_id)
        assert fields["pf"] == 0x1B
        assert struct.unpack_from(">H", data, 0)[0] == 7500

    def test_encode_set_io(self):
        can_id, data = encode_set_io(1, 0, 1, 0)
        fields = parse_can_id(can_id)
        assert fields["pf"] == 0x1F
        assert data[0] == 1
        assert data[1] == 0
        assert data[2] == 1
        assert data[3] == 0

    def test_encode_set_split_phase_enable(self):
        can_id, data = encode_set_split_phase_enable(True)
        assert data[0] == 1
        can_id, data = encode_set_split_phase_enable(False)
        assert data[0] == 0

    def test_encode_set_inverter_phase(self):
        can_id, data = encode_set_inverter_phase(7)  # A-phase host
        fields = parse_can_id(can_id)
        assert fields["pf"] == 0x28
        assert data[0] == 7

    def test_encode_set_reactive_control(self):
        can_id, data = encode_set_reactive_control(1, 0.95)
        fields = parse_can_id(can_id)
        assert fields["pf"] == 0x2A
        assert data[0] == 1

    def test_encode_set_grid_mode(self):
        can_id, data = encode_set_grid_mode(1)  # automatic switching
        fields = parse_can_id(can_id)
        assert fields["pf"] == 0x2C
        assert data[0] == 1

    def test_encode_set_module_parallel(self):
        can_id, data = encode_set_module_parallel(1, 3, 666)
        fields = parse_can_id(can_id)
        assert fields["pf"] == 0x2E
        assert data[0] == 1  # host
        assert data[1] == 3  # 3 modules

    def test_encode_set_phase_power(self):
        can_id, data = encode_set_phase_power(10.0, 10.0, 10.0)
        fields = parse_can_id(can_id)
        assert fields["pf"] == 0x21
        assert struct.unpack_from(">H", data, 0)[0] == 100  # 10kW / 0.1

    def test_encode_read_special_data(self):
        can_id, data = encode_read_special_data(0x0A)
        fields = parse_can_id(can_id)
        assert fields["pf"] == 0x1D
        assert data[0] == 0x0A

    def test_all_encoders_return_8_bytes(self):
        """All encoded messages must be exactly 8 bytes."""
        functions = [
            lambda: encode_read_protection_params(0x01),
            lambda: encode_set_protection_params1(800, 50, 150, 150),
            lambda: encode_set_protection_params2(120, 120, 264, 176),
            lambda: encode_set_protection_params3(55, 45, 55, 45),
            lambda: encode_set_time(2024, 1, 1, 0, 0, 0),
            lambda: encode_set_working_mode(0x02),
            lambda: encode_set_mode_params12(400, 0, 0x02),
            lambda: encode_set_mode_params34(0, 0, 0x02),
            lambda: encode_start_stop(True),
            lambda: encode_heartbeat(),
            lambda: encode_set_bus_voltage_reactive(750, 0),
            lambda: encode_set_io(0, 0, 0, 0),
            lambda: encode_set_split_phase_enable(True),
            lambda: encode_set_inverter_phase(7),
            lambda: encode_set_reactive_control(0, 1.0),
            lambda: encode_set_grid_mode(0),
            lambda: encode_set_module_parallel(0, 1, 666),
            lambda: encode_set_phase_power(10, 10, 10),
            lambda: encode_read_special_data(0x01),
        ]
        for fn in functions:
            can_id, data = fn()
            assert len(data) == 8, f"Expected 8 bytes, got {len(data)} from {fn}"


class TestDecoders:
    def test_decode_dc_data(self):
        # V=400.0V, I=50.0A (raw=10500 with +1000 offset), P=20.0kW, T=35.0°C
        data = struct.pack(">HHHH", 4000, 10500, 200, 850)
        dc = decode_dc_data(data)
        assert abs(dc.voltage - 400.0) < 0.01
        assert abs(dc.current - 50.0) < 0.01
        assert abs(dc.power - 20.0) < 0.01
        assert abs(dc.inlet_temperature - 35.0) < 0.01

    def test_decode_dc_data_negative_current(self):
        # Charging: I=-50.0A -> raw = (-50 + 1000) / 0.1 = 9500
        data = struct.pack(">HHHH", 4000, 9500, 200, 850)
        dc = decode_dc_data(data)
        assert abs(dc.current - (-50.0)) < 0.01

    def test_decode_dc_data_zero_current(self):
        # I=0A -> raw = (0 + 1000) / 0.1 = 10000
        data = struct.pack(">HHHH", 4000, 10000, 0, 850)
        dc = decode_dc_data(data)
        assert abs(dc.current) < 0.01

    def test_decode_capacity_energy(self):
        # Cap=100.0Ah, Energy=50000.0Wh, outlet_temp=40°C
        data = struct.pack(">HIH", 1000, 500000, 900)
        ce = decode_capacity_energy(data)
        assert abs(ce.capacity - 100.0) < 0.01
        assert abs(ce.energy - 50000.0) < 0.01
        assert abs(ce.outlet_temperature - 40.0) < 0.01

    def test_decode_status_standby(self):
        data = struct.pack(">BxHxxxx", RunningState.STANDBY, 0)
        st = decode_status(data)
        assert st.running_state == RunningState.STANDBY
        assert st.fault_code == 0
        assert st.state_name == "STANDBY"
        assert not st.is_fault

    def test_decode_status_fault(self):
        data = struct.pack(">BxHxxxx", RunningState.FAULT, 0x800D)
        st = decode_status(data)
        assert st.running_state == RunningState.FAULT
        assert st.fault_code == 0x800D
        assert st.is_fault
        assert "CAN1" in st.fault_description

    def test_decode_grid_voltage(self):
        data = struct.pack(">HHHxx", 2300, 2300, 2300)
        gv = decode_grid_voltage(data)
        assert abs(gv.u_voltage - 230.0) < 0.01
        assert abs(gv.v_voltage - 230.0) < 0.01
        assert abs(gv.w_voltage - 230.0) < 0.01

    def test_decode_grid_current(self):
        data = struct.pack(">HHHh", 500, 500, 500, 10)
        gc = decode_grid_current(data)
        assert abs(gc.u_current - 50.0) < 0.01
        assert abs(gc.power_factor - 1.0) < 0.01

    def test_decode_system_power(self):
        data = struct.pack(">HHHH", 1000, 50, 1001, 500)
        sp = decode_system_power(data)
        assert abs(sp.active_power - 100.0) < 0.01
        assert abs(sp.reactive_power - 5.0) < 0.01
        assert abs(sp.apparent_power - 100.1) < 0.01
        assert abs(sp.frequency - 50.0) < 0.01

    def test_decode_load_voltage(self):
        data = struct.pack(">HHHxx", 2200, 2200, 2200)
        lv = decode_load_voltage(data)
        assert abs(lv.u_voltage - 220.0) < 0.01

    def test_decode_load_current(self):
        data = struct.pack(">HHHxx", 100, 100, 100)
        lc = decode_load_current(data)
        assert abs(lc.u_current - 10.0) < 0.01

    def test_decode_load_power(self):
        data = struct.pack(">HHHxx", 500, 10, 501)
        lp = decode_load_power(data)
        assert abs(lp.active_power - 50.0) < 0.01

    def test_decode_phase_power(self):
        data = struct.pack(">HHHxx", 100, 5, 101)
        pp = decode_phase_power(data, "A")
        assert pp.phase == "A"
        assert abs(pp.active_power - 10.0) < 0.01

    def test_decode_high_res_dc(self):
        # V=400.123V, I=50.456A
        v_raw = int(400.123 / 0.001)
        i_raw = int((50.456 + 1000.0) / 0.001)
        data = struct.pack(">II", v_raw, i_raw)
        hr = decode_high_res_dc(data)
        assert abs(hr.voltage - 400.123) < 0.01
        assert abs(hr.current - 50.456) < 0.01

    def test_decode_high_res_dc_negative_current(self):
        i_raw = int((-75.5 + 1000.0) / 0.001)
        data = struct.pack(">II", 400000, i_raw)
        hr = decode_high_res_dc(data)
        assert abs(hr.current - (-75.5)) < 0.01

    def test_decode_protection_params1(self):
        data = struct.pack(">HHHH", 8000, 500, 1500, 1500)
        pp = decode_protection_params1(data)
        assert abs(pp.max_output_voltage - 800.0) < 0.01
        assert abs(pp.min_output_voltage - 50.0) < 0.01
        assert abs(pp.max_charge_current - 150.0) < 0.01

    def test_decode_protection_params2(self):
        data = struct.pack(">HHHH", 1200, 1200, 2640, 1760)
        pp = decode_protection_params2(data)
        assert abs(pp.max_charge_power - 120.0) < 0.01
        assert abs(pp.ac_voltage_upper - 264.0) < 0.01
        assert abs(pp.ac_voltage_lower - 176.0) < 0.01

    def test_decode_protection_params3(self):
        data = struct.pack(">HHBBxx", 550, 450, 55, 45)
        pp = decode_protection_params3(data)
        assert abs(pp.discharge_freq_upper - 55.0) < 0.01
        assert abs(pp.charge_freq_lower - 45.0) < 0.01
        assert pp.ac_freq_upper == 55.0
        assert pp.ac_freq_lower == 45.0

    def test_decode_set_reply_success(self):
        assert decode_set_reply(b"\x01\x00\x00\x00\x00\x00\x00\x00") is True
        assert decode_set_reply(b"\x01\x01\x00\x00\x00\x00\x00\x00") is True

    def test_decode_set_reply_failure(self):
        assert decode_set_reply(b"\x00\x00\x00\x00\x00\x00\x00\x00") is False

    def test_decode_io_ad(self):
        data = bytes([1, 0, 1, 0]) + struct.pack(">HH", 3300, 1650)
        io = decode_io_ad(data)
        assert io.io1 == 1
        assert io.io2 == 0
        assert io.io3 == 1
        assert io.io4 == 0
        assert abs(io.ad1_voltage - 3.3) < 0.01
        assert abs(io.ad2_voltage - 1.65) < 0.01

    def test_decode_version(self):
        data = bytes([1, 2, 3, 2, 1, 38, 0, 0])
        v = decode_version(data)
        assert v.hw_v == 1
        assert v.hw_b == 2
        assert v.hw_d == 3
        assert v.sw_v == 2
        assert v.sw_b == 1
        assert v.sw_d == 38


class TestMessageDispatcher:
    def test_decode_rx_dc_data(self):
        can_id = make_rx_id(0x11)
        data = struct.pack(">HHHH", 4000, 10500, 200, 850)
        name, decoded = decode_rx_message(can_id, data)
        assert name == "dc"
        assert abs(decoded.voltage - 400.0) < 0.01

    def test_decode_rx_status(self):
        can_id = make_rx_id(0x13)
        data = struct.pack(">BxHxxxx", 13, 0)
        name, decoded = decode_rx_message(can_id, data)
        assert name == "status"
        assert decoded.running_state == RunningState.STANDBY

    def test_decode_rx_phase_power(self):
        for pf, phase, field in [(0x23, "A", "phase_a_power"), (0x24, "B", "phase_b_power"), (0x25, "C", "phase_c_power")]:
            can_id = make_rx_id(pf)
            data = struct.pack(">HHHxx", 100, 5, 101)
            name, decoded = decode_rx_message(can_id, data)
            assert name == field
            assert decoded.phase == phase

    def test_decode_rx_high_res(self):
        can_id = make_rx_id(0x39)
        data = struct.pack(">II", 400000, 1050000)
        name, decoded = decode_rx_message(can_id, data)
        assert name == "dc_hires"
        assert abs(decoded.voltage - 400.0) < 0.01

    def test_decode_rx_unknown(self):
        can_id = make_rx_id(0xFF)
        data = b"\x00" * 8
        name, decoded = decode_rx_message(can_id, data)
        assert name is None
        assert decoded is None

    def test_decode_rx_set_reply(self):
        can_id = make_rx_id(0x10)
        data = b"\x01" + b"\x00" * 7
        name, decoded = decode_rx_message(can_id, data)
        assert "0x10" in name
        assert decoded is True


class TestFaultCodes:
    def test_known_fault(self):
        assert "CAN1" in fault_description(0x800D)

    def test_no_fault(self):
        assert fault_description(0) == "No fault"

    def test_unknown_fault(self):
        desc = fault_description(0x9999)
        assert "0x9999" in desc or "contact factory" in desc.lower()

    def test_all_faults_have_descriptions(self):
        for code in FAULT_CODES:
            assert len(FAULT_CODES[code]) > 0


class TestWorkingModes:
    def test_all_modes_defined(self):
        expected = [0x02, 0x08, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26,
                    0x27, 0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x40, 0x41,
                    0x61, 0x91, 0x94]
        for val in expected:
            assert WorkingMode(val) is not None

    def test_mode_names(self):
        assert WorkingMode.DC_CONSTANT_VOLTAGE.name == "DC_CONSTANT_VOLTAGE"
        assert WorkingMode.DC_CC_CV.name == "DC_CC_CV"
        assert WorkingMode.IDLE.name == "IDLE"
        assert WorkingMode.STANDBY.name == "STANDBY"


class TestRunningStates:
    def test_all_states(self):
        for i in range(1, 15):
            assert RunningState(i) is not None

    def test_state_names(self):
        assert RunningState.STANDBY == 13
        assert RunningState.FAULT == 6
        assert RunningState.CONSTANT_VOLTAGE == 11


class TestPFNames:
    def test_known_pf(self):
        assert pf_name(0x11) == "DCData"
        assert pf_name(0x13) == "Status"
        assert pf_name(0x0F) == "StartStop"

    def test_unknown_pf(self):
        assert "Unknown" in pf_name(0xFF)


class TestEncodingRoundtrip:
    """Verify that encoding then decoding produces the original values."""

    def test_protection_params1_roundtrip(self):
        _, data = encode_set_protection_params1(800.0, 50.0, 150.0, 150.0)
        decoded = decode_protection_params1(data)
        assert abs(decoded.max_output_voltage - 800.0) < 0.1
        assert abs(decoded.min_output_voltage - 50.0) < 0.1
        assert abs(decoded.max_charge_current - 150.0) < 0.1
        assert abs(decoded.max_discharge_current - 150.0) < 0.1

    def test_protection_params2_roundtrip(self):
        _, data = encode_set_protection_params2(120.0, 120.0, 264.0, 176.0)
        decoded = decode_protection_params2(data)
        assert abs(decoded.max_charge_power - 120.0) < 0.1
        assert abs(decoded.max_discharge_power - 120.0) < 0.1
        assert abs(decoded.ac_voltage_upper - 264.0) < 0.1
        assert abs(decoded.ac_voltage_lower - 176.0) < 0.1

    def test_heartbeat_dc_roundtrip(self):
        """Encode heartbeat -> decode as external device data (frame 26)."""
        _, data = encode_heartbeat(400.0, 50.0, 0x02)
        v_raw = struct.unpack_from(">H", data, 0)[0]
        i_raw = struct.unpack_from(">H", data, 2)[0]
        voltage = v_raw * 0.1
        current = i_raw * 0.1 - 1000.0
        assert abs(voltage - 400.0) < 0.1
        assert abs(current - 50.0) < 0.1
        assert data[4] == 0x02
