"""Logging utilities for CAN frame recording and console output.

Supports CSV and JSONL output formats for CAN frame logging.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, TextIO

from dcdc_app.protocol import PF_NAMES, parse_can_id

logger = logging.getLogger(__name__)


@dataclass
class FrameRecord:
    """Single CAN frame log record."""
    timestamp: float
    direction: str  # "TX" or "RX"
    can_id: int
    dlc: int
    data_hex: str
    pf: int
    pf_name: str
    decoded: Optional[Dict[str, Any]] = None

    def to_csv_row(self) -> list:
        dt = datetime.fromtimestamp(self.timestamp).isoformat(timespec="milliseconds")
        decoded_str = json.dumps(self.decoded) if self.decoded else ""
        return [
            dt,
            self.direction,
            f"0x{self.can_id:08X}",
            self.dlc,
            self.data_hex,
            f"0x{self.pf:02X}",
            self.pf_name,
            decoded_str,
        ]

    def to_jsonl(self) -> str:
        d = {
            "timestamp": datetime.fromtimestamp(self.timestamp).isoformat(timespec="milliseconds"),
            "direction": self.direction,
            "can_id": f"0x{self.can_id:08X}",
            "dlc": self.dlc,
            "data_hex": self.data_hex,
            "pf": f"0x{self.pf:02X}",
            "pf_name": self.pf_name,
        }
        if self.decoded:
            d["decoded"] = self.decoded
        return json.dumps(d)


CSV_HEADER = ["timestamp", "direction", "can_id", "dlc", "data_hex", "pf", "pf_name", "decoded"]


class FrameLogger:
    """Logs CAN frames to file (CSV or JSONL) and optionally to console."""

    def __init__(
        self,
        filepath: Optional[str] = None,
        fmt: str = "csv",
        console: bool = True,
    ):
        """Initialize frame logger.

        Args:
            filepath: Output file path. None to disable file logging.
            fmt: Output format - 'csv' or 'jsonl'.
            console: If True, also log decoded frames to console.
        """
        self.filepath = filepath
        self.fmt = fmt.lower()
        self.console = console
        self._file: Optional[TextIO] = None
        self._csv_writer = None
        self._record_count = 0

    def open(self) -> None:
        """Open the log file."""
        if self.filepath:
            path = Path(self.filepath)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(self.filepath, "w", newline="", encoding="utf-8")
            if self.fmt == "csv":
                self._csv_writer = csv.writer(self._file)
                self._csv_writer.writerow(CSV_HEADER)
            logger.info("Logging frames to %s (%s)", self.filepath, self.fmt)

    def close(self) -> None:
        """Close the log file."""
        if self._file:
            self._file.close()
            self._file = None
            self._csv_writer = None
            logger.info("Closed frame log (%d records)", self._record_count)

    def log_frame(
        self,
        can_id: int,
        data: bytes,
        direction: str = "RX",
        decoded: Optional[Any] = None,
    ) -> None:
        """Log a CAN frame.

        Args:
            can_id: CAN arbitration ID.
            data: Frame data bytes.
            direction: "TX" or "RX".
            decoded: Decoded data object (dataclass or dict).
        """
        fields = parse_can_id(can_id)
        pf = fields["pf"]
        pf_name = PF_NAMES.get(pf, f"Unknown_0x{pf:02X}")

        decoded_dict = None
        if decoded is not None:
            if hasattr(decoded, "__dataclass_fields__"):
                decoded_dict = asdict(decoded)
            elif isinstance(decoded, dict):
                decoded_dict = decoded
            elif isinstance(decoded, bool):
                decoded_dict = {"success": decoded}

        record = FrameRecord(
            timestamp=time.time(),
            direction=direction,
            can_id=can_id,
            dlc=len(data),
            data_hex=data.hex(" "),
            pf=pf,
            pf_name=pf_name,
            decoded=decoded_dict,
        )

        # Write to file
        if self._file:
            if self.fmt == "csv" and self._csv_writer:
                self._csv_writer.writerow(record.to_csv_row())
            else:
                self._file.write(record.to_jsonl() + "\n")
            self._file.flush()
            self._record_count += 1

        # Console output
        if self.console:
            self._print_console(record)

    def _print_console(self, record: FrameRecord) -> None:
        """Print a frame record to console in a readable format."""
        dt = datetime.fromtimestamp(record.timestamp).strftime("%H:%M:%S.%f")[:-3]
        line = (
            f"[{dt}] {record.direction}  "
            f"ID=0x{record.can_id:08X}  "
            f"PF={record.pf_name:<25s}  "
            f"Data={record.data_hex}"
        )
        if record.decoded:
            # Format decoded values compactly
            parts = []
            for k, v in record.decoded.items():
                if isinstance(v, float):
                    parts.append(f"{k}={v:.2f}")
                else:
                    parts.append(f"{k}={v}")
            line += "  | " + ", ".join(parts)
        print(line)

    def __enter__(self) -> FrameLogger:
        self.open()
        return self

    def __exit__(self, *args) -> None:
        self.close()


def setup_logging(level: str = "INFO", logfile: Optional[str] = None) -> None:
    """Configure application-wide logging.

    Args:
        level: Log level name (DEBUG, INFO, WARNING, ERROR).
        logfile: Optional file to also write log messages to.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    handlers: list = [logging.StreamHandler(sys.stderr)]
    if logfile:
        handlers.append(logging.FileHandler(logfile))

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )
