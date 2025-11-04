from pathlib import Path

# --- Constants ---
APP_NAME = "Nano Installer"
VERSION = "1.0.4"
# Path to the compiled C backend executable (relative to the project root)
BACKEND_PATH = str(Path(__file__).parent.parent / "nano_backend")

# Icon and Asset Paths
APP_ICON_NAME = "nano-installer.png"
APP_ICON_PATH_INSTALLED = f"/usr/share/nano-installer/assets/{APP_ICON_NAME}"
APP_ICON_PATH_SOURCE = str(Path(__file__).parent.parent / "assets" / APP_ICON_NAME)

REPORT_ISSUES_URL = "https://github.com/putinservai-cyber/Nano-deb-Installer/issues"