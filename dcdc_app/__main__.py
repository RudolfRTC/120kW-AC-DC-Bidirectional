"""Allow running as: python -m dcdc_app

Supports both CLI and GUI:
    python -m dcdc_app [CLI_ARGS]      # CLI mode
    python -m dcdc_app gui             # Launch GUI
"""
import sys
from dcdc_app.cli import main

sys.exit(main())
