import sys
import subprocess
import os
import tempfile
import requests
from PyQt5.QtWidgets import QMessageBox, QApplication, QWidget
from PyQt5.QtCore import QProcess

from .utils import get_installed_version, compare_versions
from .constants import APP_NAME, GITHUB_RELEASES_API

def _get_latest_release_info() -> tuple[str | None, str | None]:
    """
    Fetches the latest release version and .deb download URL from GitHub API.
    Returns (version, download_url) or (None, None) on failure.
    """
    try:
        response = requests.get(GITHUB_RELEASES_API, timeout=10)
        response.raise_for_status()
        release_info = response.json()
        
        # The tag_name is typically 'vX.Y.Z', so we strip the 'v'
        latest_version = release_info.get('tag_name', '').lstrip('v')
        
        deb_url = None
        for asset in release_info.get('assets', []):
            if asset.get('name', '').endswith('.deb'):
                deb_url = asset.get('browser_download_url')
                break
        
        return latest_version, deb_url
    except requests.exceptions.RequestException as e:
        print(f"Error fetching latest release info from GitHub: {e}")
        return None, None
    except Exception as e:
        print(f"Unexpected error during GitHub API call: {e}")
        return None, None

def _download_package(parent: QWidget, download_url: str) -> str | None:
    """
    Downloads the .deb package to a temporary file.
    Returns the path to the downloaded file or None on failure.
    """
    QMessageBox.information(parent, "Downloading Update",
                            f"Downloading the new version of {APP_NAME}. Please wait...")
    
    try:
        response = requests.get(download_url, stream=True, timeout=60)
        response.raise_for_status()
        
        # Create a temporary file to save the .deb package
        with tempfile.NamedTemporaryFile(suffix=".deb", delete=False) as tmp_file:
            for chunk in response.iter_content(chunk_size=8192):
                tmp_file.write(chunk)
            temp_path = tmp_file.name
        
        return temp_path
    except requests.exceptions.RequestException as e:
        QMessageBox.critical(parent, "Download Error", f"Failed to download the update package:\n{e}")
        return None
    except Exception as e:
        QMessageBox.critical(parent, "Download Error", f"An unexpected error occurred during download:\n{e}")
        return None

def _install_update(parent: QWidget, deb_path: str):
    """
    Launches a separate process to install the update using pkexec/dpkg.
    This requires the user to authenticate.
    """
    QMessageBox.information(parent, "Starting Update",
                            f"The application will now close to start the update process for '{APP_NAME}'. "
                            "You may be prompted for your password to authorize the installation.")
    
    # Command: pkexec dpkg -i <deb_path>
    # We use dpkg -i instead of apt install to install the local .deb file directly.
    command = f"pkexec dpkg -i {deb_path}"
    
    # Launch the update process detached using pkexec for privilege escalation
    QProcess.startDetached("/bin/sh", ["-c", command])
    
    # Exit current application
    QApplication.instance().quit()

def check_for_updates(parent: QWidget):
    """
    Checks for updates using the GitHub releases API and offers to install the .deb package.
    """
    # 1. Get the currently installed version
    # We assume the package name is 'nano-installer' for the installed version check
    installed_version = get_installed_version('nano-installer')
    if not installed_version:
        QMessageBox.warning(parent, "Update Check Failed",
                            "Could not determine the installed version of 'nano-installer'. Cannot check for updates.")
        return

    # 2. Get the latest version and download URL from GitHub
    latest_version, download_url = _get_latest_release_info()

    if not latest_version or not download_url:
        QMessageBox.warning(parent, "Update Check Failed",
                            "Could not retrieve the latest version information from the server. Check your network connection.")
        return

    # 3. Compare versions
    if compare_versions(latest_version, 'gt', installed_version):
        reply = QMessageBox.question(
            parent,
            "Update Available",
            f"A new version of {APP_NAME} is available!\n\n"
            f"Current version: {installed_version}\n"
            f"New version: {latest_version}\n\n"
            "Do you want to download and install it now? This requires administrative privileges.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        
        if reply == QMessageBox.Yes:
            # 4. Download the package
            deb_path = _download_package(parent, download_url)
            
            if deb_path:
                # 5. Install the package
                _install_update(parent, deb_path)
            # Note: The temporary file will be cleaned up by the OS after the process exits.
    else:
        QMessageBox.information(parent, "Up to Date",
                                f"{APP_NAME} (version {installed_version}) is already the latest version.")

def _check_for_updates_git(parent: QWidget):
    """(Fallback for dev) Placeholder for Git-based update check."""
    QMessageBox.information(parent, "Developer Mode",
                            "Update check is in developer mode (using Git).\n"
                            "This is because the application does not appear to be installed as a system package.")

# The main entry point for update check, which can be called from the GUI
def check_for_self_update(parent: QWidget):
    """
    Main function to check for self-updates.
    It checks if the application is installed as a package or running from source.
    """
    # A simple check to see if we are running from the installed path or source path
    # This is a heuristic and might need refinement.
    # For now, we'll assume if get_installed_version fails, we are in dev mode.
    if get_installed_version('nano-installer'):
        check_for_updates(parent)
    else:
        _check_for_updates_git(parent)