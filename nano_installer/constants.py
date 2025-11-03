from pathlib import Path

# --- Constants ---
APP_NAME = "Nano Installer"
VERSION = "1.0.4"
# Path to the compiled C backend executable (relative to the project root)
BACKEND_PATH = str(Path(__file__).parent.parent / "nano_backend")
REPORT_ISSUES_URL = "https://github.com/putinservai-cyber/Nano-deb-Installer/issues"