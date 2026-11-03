import os
from pathlib import Path

# Paths
SERVER_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = SERVER_DIR.parent
STRATEGIES_DIR = BASE_DIR / "strategies"
DATA_DIR = BASE_DIR / "data"

# Application Metadata
APP_TITLE = "NujinSkills Telemetry & Signal Gateway API"
APP_VERSION = "2.0.0"
APP_DESCRIPTION = "Institutional 24/7 Backend Telemetry Hub, WebSocket Dispatcher, and Execution Gateway"

# Network
DEFAULT_HOST = os.getenv("NUJIN_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.getenv("NUJIN_PORT", "8000"))
