from pathlib import Path

# --- Constants ---
APP_NAME = "Nano Installer"
VERSION = "1.0.8"
# Path to the compiled C backend executable
BACKEND_PATH_INSTALLED = "/usr/lib/nano-installer/nano_backend"
BACKEND_PATH_SOURCE = str(Path(__file__).parent.parent / "nano_backend")

def get_backend_path() -> str:
    """Returns the correct path to the C backend executable."""
    # Check if the installed path exists (FHS compliant)
    if Path(BACKEND_PATH_INSTALLED).exists():
        return BACKEND_PATH_INSTALLED
    # Fallback to the source path (for development)
    return BACKEND_PATH_SOURCE

BACKEND_PATH = get_backend_path()

# Icon and Asset Paths
APP_ICON_NAME = "nano-installer.png"
APP_ICON_THEME_NAME = "nano-installer" # The name used in .desktop files and themes
APP_ICON_PATH_INSTALLED = f"/usr/share/nano-installer/assets/{APP_ICON_NAME}"
APP_ICON_PATH_SOURCE = str(Path(__file__).parent.parent / "assets" / APP_ICON_NAME)

REPORT_ISSUES_URL = "https://github.com/putinservai-cyber/Nano-deb-Installer/issues"
REPORT_ISSUES_URL = "https://github.com/putinservai-cyber/Nano-deb-Installer/issues"
GITHUB_RELEASES_API = "https://api.github.com/repos/putinservai-cyber/Nano-deb-Installer/releases"