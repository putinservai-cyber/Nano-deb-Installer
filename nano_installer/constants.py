from pathlib import Path

# --- Constants ---
APP_NAME = "Nano Installer"
# Path to the compiled C backend executable (relative to the project root)
BACKEND_PATH = str(Path(__file__).parent.parent / "nano_backend")