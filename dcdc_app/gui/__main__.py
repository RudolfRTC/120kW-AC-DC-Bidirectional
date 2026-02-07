"""Launch the DC/DC Mission Console GUI.

Usage:
    python -m dcdc_app.gui
"""

import sys
from dcdc_app.gui.app import launch

if __name__ == "__main__":
    sys.exit(launch())
