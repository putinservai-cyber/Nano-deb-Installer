import sys
import subprocess
import os
import re
from PyQt5.QtWidgets import QMessageBox, QApplication, QWidget
from PyQt5.QtCore import QProcess

from .utils import get_installed_version, compare_versions, get_nano_installer_package_name
from .constants import APP_NAME

def _run_apt_update():
    """Runs 'apt update' to refresh package lists."""
    try:
        # Run apt update. We don't use check=True because apt update often returns non-zero
        # exit codes for warnings (e.g., missing signatures) even if it successfully updates lists.
        result = subprocess.run(["apt", "update"], capture_output=True, text=True)
        
        # Check if the command failed critically (e.g., command not found, or major error)
        if result.returncode != 0:
            # Log the error output for debugging, but return True if it's just warnings
            # A common non-zero exit code is 100, which means some lists could not be retrieved.
            # We assume if the command ran, the main lists were updated enough to check for updates.
            if result.returncode != 100:
                print(f"Error running apt update (Exit Code {result.returncode}): {result.stderr}")
                return False
        
        return True
    except FileNotFoundError:
        print("Error: 'apt' command not found.")
        return False
    except Exception as e:
        print(f"Unexpected error during apt update: {e}")
        return False

def _check_for_upgradable_version(pkg_name: str) -> str | None:
    """Checks if a package has an upgradable version available."""
    try:
        # apt list --upgradable outputs lines like:
        # package-name/release-name version-available -> version-installed [upgradable from: version-installed]
        cmd = ["apt", "list", "--upgradable", pkg_name]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        # Check if the package is listed as upgradable
        for line in result.stdout.splitlines():
            if line.startswith(f"{pkg_name}/") and "upgradable from:" in line:
                # Extract the available version (the first version number after the package name)
                # Example line: nano-installer/stable 1.2.3 -> 1.2.2 [upgradable from: 1.2.2]
                match = re.search(r'^\s*[^/]+\/[^ ]+\s+([^ ]+)\s+->', line)
                if match:
                    return match.group(1)
        return None
    except subprocess.CalledProcessError:
        return None
    except FileNotFoundError:
        return None

def _install_update(parent: QWidget, pkg_name: str):
    """
    Launches a separate process to install the update using pkexec/apt.
    This requires the user to authenticate.
    """
    QMessageBox.information(parent, "Starting Update",
                            f"The application will now close to start the update process for '{pkg_name}'. "
                            "You may be prompted for your password to authorize the installation.")
    
    # Launch the update process detached using pkexec for privilege escalation
    # Command: pkexec apt install -y <pkg_name>
    command = f"pkexec apt install -y {pkg_name}"
    QProcess.startDetached("/bin/sh", ["-c", command])
    
    # Exit current application
    QApplication.instance().quit()


def check_for_updates(parent: QWidget):
    """
    Checks for updates using the system's package manager (apt).
    """
    # 1. Get the package name of the running installer
    our_pkg_name = get_nano_installer_package_name()
    if not our_pkg_name:
        # Fallback for development environments
        return _check_for_updates_git(parent)

    # 2. Get the currently installed version
    installed_version = get_installed_version(our_pkg_name)
    if not installed_version:
        QMessageBox.warning(parent, "Update Check Failed",
                            f"Could not determine the installed version of '{our_pkg_name}'. Cannot check for updates.")
        return

    try:
        # 3. Refresh package lists
        if not _run_apt_update():
            QMessageBox.critical(parent, "Update Error", "Failed to refresh package lists (apt update). Check your network connection or repository configuration.")
            return

        # 4. Check for upgradable version
        latest_version = _check_for_upgradable_version(our_pkg_name)

        if latest_version and compare_versions(latest_version, 'gt', installed_version):
            reply = QMessageBox.question(
                parent,
                "Update Available",
                f"A new version of {APP_NAME} is available in the repositories!\n\n"
                f"Current version: {installed_version}\n"
                f"New version: {latest_version}\n\n"
                "Do you want to install it now? This requires administrative privileges.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                _install_update(parent, our_pkg_name)
        else:
            QMessageBox.information(parent, "Up to Date",
                                    f"{APP_NAME} (version {installed_version}) is already the latest version available in the repositories.")

    except Exception as e:
        QMessageBox.critical(parent, "Update Error", f"An unexpected error occurred while checking for updates:\n{e}")

def _check_for_updates_git(parent: QWidget):
    """(Fallback for dev) Checks for updates using Git."""
    QMessageBox.information(parent, "Developer Mode",
                            "Update check is in developer mode (using Git).\n"
                            "This is because the application does not appear to be installed as a system package.")
    # The original git logic can be kept here if desired for development.
    # For this refactor, we'll just show a message.
    # You can paste the old git logic here if you still need it.