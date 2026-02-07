# YSTECH PCS (30-120kW) CAN Communication Application

Python application for communicating with YSTECH bidirectional AC/DC PCS modules
over CAN bus using PEAK PCAN hardware.

## Repo Findings

### Documentation Sources

| File | Content |
|------|---------|
| `YSTECH_PCS battery test system external CAN communication protocol v1.11-20231127_EN.pdf` | Complete CAN protocol: 35+ message frames, signal definitions, fault codes, working modes |
| `YSTECH ( 30-120KW ) Series PCS Module Products User Manual TUV-V1.2.pdf` | Hardware specs: voltage/current ratings, communication interfaces, installation |
| `PMA Series PCS Power connection 2.pdf` | Wiring diagrams, parallel connection topology |

### CAN Protocol Summary

| Parameter | Value |
|-----------|-------|
| Standard | CAN 2.0B extended frame (29-bit IDs) |
| Protocol | J1939-based |
| Bitrate | **250 kbps** |
| Controller address | 0xB4 (180) |
| PCS default address | 0xFA (250) |
| Status frame period | 200 ms |
| Heartbeat timeout | 5 seconds (triggers CAN1 fault + shutdown) |
| Data encoding | Big-endian (high byte first) |

### CAN ID Structure (29-bit)

```
[28:26] Priority (3 bits, default 6)
[25]    Reserved (0)
[24]    Data Page (0)
[23:16] PF - PDU Format (command code)
[15:8]  PS - Target address
[7:0]   SA - Source address
```

- **Controller -> PCS**: `0x18{PF}{PCS_ADDR}{0xB4}`
- **PCS -> Controller**: `0x18{PF}{0xB4}{PCS_ADDR}`

### Key Message Frames

| PF | Direction | Name | Period |
|----|-----------|------|--------|
| 0x0B | TX | Set Working Mode | Burst |
| 0x0C | TX | Set Mode Params 1&2 | Burst |
| 0x0D | TX | Set Mode Params 3&4 | Burst |
| 0x0F | TX | Start/Stop/Clear Faults | Burst |
| 0x1A | TX | Heartbeat (external device data) | **200ms** |
| 0x11 | RX | DC Voltage/Current/Power/Temp | 200ms |
| 0x12 | RX | Capacity (Ah) / Energy (Wh) | 200ms |
| 0x13 | RX | Running State + Fault Code | 200ms |
| 0x14 | RX | Grid Voltages (U/V/W) | 200ms |
| 0x15 | RX | Grid Currents (U/V/W) + PF | 200ms |
| 0x16 | RX | System Power (P/Q/S) + Freq | 200ms |
| 0x39 | RX | High-res DC V/I (0.001 resolution) | 200ms |

### Working Modes (19 modes)

| Code | Mode | Parameters |
|------|------|------------|
| 0x02 | DC Constant Voltage | voltage (0.001V) |
| 0x08 | DC CV + Current Limiting | voltage, max charge I, max discharge I |
| 0x21 | DC Constant Current | current (0.001A) |
| 0x22 | DC Constant Power | power (0.001W) |
| 0x29 | DC CC-CV | voltage, current, end current |
| 0x40 | AC Constant Power | active power, reactive power |
| 0x41 | Independent Inverter | voltage, frequency |
| 0x91 | Idle | — |
| 0x94 | Standby | — |

Negative current/power values = **charging**, positive = **discharging**.

### Safety Constraints

- Mode change requires device to be **stopped first** (no online mode change)
- Frame 26 heartbeat **must be sent every 200ms** to prevent CAN timeout fault
- When modifying start/stop command, other fields must maintain original values
- Parameters must stay within protection parameter boundaries

## Architecture

```
dcdc_app/
  __init__.py          # Package metadata
  __main__.py          # python -m dcdc_app entry point
  protocol.py          # CAN IDs, signal encode/decode, data structures, fault codes
  can_iface.py         # PCAN/virtual bus init, send/recv, filters, reconnect
  controller.py        # State machine: heartbeat, RX loop, enable/disable/fault
  cli.py               # argparse CLI with all commands
  logging_utils.py     # CSV/JSONL frame logging, console output
  simulator.py         # Simulated PCS for dry-run mode
tests/
  test_protocol.py     # Encode/decode unit tests, roundtrip tests
  test_controller.py   # Integration tests with simulated bus
```

### Module Responsibilities

- **protocol.py**: Pure data layer. No I/O. Defines all 35+ CAN message encoders/decoders,
  data classes for each frame, working modes, running states, fault codes.
  All values from the YSTECH protocol v1.11 document.

- **can_iface.py**: Hardware abstraction. Wraps python-can Bus for PCAN (Windows/Linux),
  virtual bus (dry-run), reconnect with exponential backoff.

- **controller.py**: Orchestration. Runs RX thread (decodes + updates PCSState),
  heartbeat thread (200ms), provides high-level commands (enable, disable, set mode,
  reset faults). Thread-safe state access.

- **cli.py**: User interface. argparse with subcommands. Each command creates
  controller + optional simulator, executes action, prints results.

- **simulator.py**: Fake PCS on virtual CAN bus. Sends realistic periodic frames,
  responds to commands. Simulates heartbeat timeout detection.

## Installation

```bash
# Basic install
pip install -e .

# With PCAN driver support
pip install -e ".[pcan]"

# Development (includes pytest)
pip install -e ".[dev]"

# Or just install dependencies directly
pip install python-can
```

### PCAN Driver Setup (Windows)

1. Download and install [PEAK PCAN drivers](https://www.peak-system.com/Drivers.523.0.html)
2. Connect PCAN-USB adapter
3. Verify with: `dcdc-pcs list-interfaces`

### PCAN Driver Setup (Linux)

```bash
# Load the peak_usb kernel module
sudo modprobe peak_usb

# Verify
ip link show can0
# Or use PCAN channel names with python-can
```

## Usage

### Dry-Run Mode (No Hardware)

```bash
# Monitor simulated PCS data
python -m dcdc_app --dry-run monitor

# Read status
python -m dcdc_app --dry-run status

# Enable/disable
python -m dcdc_app --dry-run enable
python -m dcdc_app --dry-run disable

# Set working mode
python -m dcdc_app --dry-run set cv 400        # DC constant voltage 400V
python -m dcdc_app --dry-run set cc 50         # DC constant current 50A
python -m dcdc_app --dry-run set cp 10000      # DC constant power 10kW
python -m dcdc_app --dry-run set cccv 400 50 5 # CC-CV: 400V, 50A, 5A cutoff

# Record frames
python -m dcdc_app --dry-run record --duration 10 --out data.csv

# Read firmware version
python -m dcdc_app --dry-run version

# Dump fault code table
python -m dcdc_app dump-faults

# Clear faults
python -m dcdc_app --dry-run reset-faults
```

### With PCAN Hardware (Windows)

```bash
# Use default PCAN_USBBUS1 at 250kbps
python -m dcdc_app monitor

# Specify channel and bitrate
python -m dcdc_app --channel PCAN_USBBUS2 --bitrate 250000 monitor

# Different PCS address
python -m dcdc_app --pcs-addr 0x01 status

# Enable with debug logging
python -m dcdc_app --log-level DEBUG enable

# Record to JSONL with log file
python -m dcdc_app --log-file app.log record --duration 60 --out frames.jsonl
```

### With PCAN on Linux (SocketCAN)

```bash
# Setup CAN interface
sudo ip link set can0 type can bitrate 250000
sudo ip link set can0 up

# Use socketcan interface
python -m dcdc_app --interface socketcan --channel can0 monitor
```

### CLI Commands Reference

| Command | Description |
|---------|-------------|
| `list-interfaces` | Scan for available PCAN hardware |
| `monitor` | Live display of all PCS status frames |
| `status` | One-shot status read (DC, AC, temps, faults) |
| `enable` | Start the PCS device |
| `disable` | Stop the PCS device |
| `set <param> <value>` | Set working mode/parameters (cv, cc, cp, cccv, mode) |
| `dump-faults` | Print all known fault codes |
| `reset-faults` | Clear fault state on PCS |
| `record -d N -o FILE` | Record N seconds of CAN frames to CSV/JSONL |
| `version` | Read PCS ARM/DSP firmware version |
| `read-params` | Read protection parameters |

## Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_protocol.py -v

# Run with timeout (default 30s per test)
pytest --timeout=30
```

## Troubleshooting

### PCAN Driver Not Found

```
Error: Failed to connect: PCAN driver not found
```
- **Windows**: Install PEAK PCAN drivers from peak-system.com
- **Linux**: `sudo modprobe peak_usb` or install `libpcan`

### Bus-Off / Bitrate Mismatch

```
Error: TX error: Bus-off
```
- Verify bitrate matches PCS setting: **250 kbps** (protocol spec)
- Check CAN bus termination (120Ω at each end)
- Ensure proper wiring (CAN-H, CAN-L, GND)

### No Data from PCS

- PCS default address is **0xFA** — verify with `--pcs-addr`
- Heartbeat (frame 26) must be sent within 5 seconds or PCS reports fault
- Check that PCS CAN address matches (configurable via PCS display screen)

### Permission Denied (Linux)

```bash
# Add user to dialout group
sudo usermod -aG dialout $USER
# Or run with sudo for socketcan
sudo python -m dcdc_app --interface socketcan --channel can0 monitor
```

### CAN1 Communication Fault (0x800D)

This fault occurs when the PCS doesn't receive heartbeat frames for 5 seconds.
The application automatically sends heartbeats at 200ms intervals. If this fault
appears, check:
- CAN bus connection and wiring
- Bitrate match (250 kbps)
- Application was running and sending heartbeats

To clear: `python -m dcdc_app reset-faults`

## Protocol Reference

Full protocol details are in the PDF:
`YSTECH_PCS battery test system external CAN communication protocol v1.11-20231127_EN.pdf`

Key documents in repository:
- CAN protocol specification (36 pages)
- Hardware user manual (21 pages)
- Power connection diagrams (3 pages)
