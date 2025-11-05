import subprocess
import logging
import requests
import tempfile
from PyQt5.QtWidgets import QMessageBox, QApplication, QWidget
from PyQt5.QtCore import QProcess
from .utils import get_installed_version, compare_versions, get_nano_installer_package_name
from .constants import APP_NAME, GITHUB_RELEASES_API

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def _get_latest_release_info():
    """
    Fetches the latest release version and .deb download URL from GitHub API.
    Returns a tuple of (version, download_url) or (None, None) on failure.
    """
    # 1. Try to get the latest release (preferred for package updates)
    try:
        response = requests.get(GITHUB_RELEASES_API, timeout=10)
        response.raise_for_status()
        releases = response.json()
        
        # If the releases list is empty, there's nothing to do.
        if not releases:
            print("No releases found on GitHub.")
            return None, None
        
        # The latest release is the first one in the list.
        release_info = releases[0]
        
        # The tag_name is typically 'vX.Y.Z', so we strip the 'v'
        latest_version = release_info.get('tag_name', '').lstrip('v')
        
        deb_url = None
        for asset in release_info.get('assets', []):
            if asset.get('name', '').endswith('.deb'):
                deb_url = asset.get('browser_download_url')
                break
        
        if latest_version and deb_url:
            return latest_version, deb_url
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            print(f"Releases API returned 404: No releases found. Error: {e}")
        else:
            print(f"Error fetching latest release info from GitHub: {e}")
    except requests.exceptions.RequestException as e:
        print(f"Error fetching latest release info from GitHub: {e}")
    except Exception as e:
        print(f"Unexpected error during GitHub API call: {e}")
        
    return None, None

def _download_package(parent: QWidget, download_url: str) -> str | None:
    """
    Downloads the .deb package to a temporary file.
    Returns the path to the downloaded file or None on failure.
    """
    # QMessageBox.information(parent, "Downloading Update",
    #                         f"Downloading the new version of {APP_NAME}. Please wait...")
    
    try:
        # Create a progress dialog
        from PyQt5.QtWidgets import QProgressDialog
        from PyQt5.QtCore import Qt
        progress_dialog = QProgressDialog(f"Downloading {APP_NAME} update...", "Cancel", 0, 100, parent)
        progress_dialog.setWindowTitle("Downloading Update")
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setAutoClose(True)
        progress_dialog.setAutoReset(True)
        progress_dialog.setValue(0)
        
        response = requests.get(download_url, stream=True, timeout=60)
        response.raise_for_status()
        
        total_length = int(response.headers.get('content-length', 0))
        chunk_size = 8192
        
        # Create a temporary file to save the .deb package
        with tempfile.NamedTemporaryFile(suffix=".deb", delete=False) as tmp_file:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=chunk_size):
                if progress_dialog.wasCanceled():
                    return None
                
                tmp_file.write(chunk)
                downloaded += len(chunk)
                
                if total_length > 0:
                    percent_complete = int((downloaded / total_length) * 100)
                    progress_dialog.setValue(percent_complete)
                    
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
    logging.info("Checking for updates using GitHub releases API...")
    # 1. Get the currently installed version
    pkg_name = get_nano_installer_package_name()
    installed_version = get_installed_version(pkg_name)
    
    # Determine the version to compare against
    current_version = installed_version
    if not current_version:
        # Fallback to the hardcoded version in constants.py if not installed as a package
        from .constants import VERSION
        current_version = VERSION
        
    if not current_version:
        QMessageBox.warning(parent, "Update Check Failed",
                            "Could not determine the current version. Cannot check for updates.")
        return

    # 2. Get the latest version and download URL from GitHub
    logging.info(f"Getting latest version and download URL from GitHub API: {GITHUB_RELEASES_API}")
    latest_version, download_url = _get_latest_release_info()

    if not latest_version:
        logging.warning("Could not retrieve the latest version information from the server.")
        QMessageBox.warning(parent, "Update Check Failed",
                            "Could not retrieve the latest version information from the server. This may be due to a network issue or because no releases are available on GitHub.")
        return

    # 3. Compare versions
    if compare_versions(latest_version, 'gt', current_version):
        reply = QMessageBox.question(
            parent,
            "Update Available",
            f"A new version of {APP_NAME} is available!\n\n"
            f"Current version: {current_version}\n"
            f"New version: {latest_version}\n\n"
            "Do you want to download and install it now? This requires administrative privileges.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        
        if reply == QMessageBox.Yes:
            # 4. Download the package
            deb_path = _download_package(parent, download_url)
            
            if deb_path:
                # 5. Verify the package
                logging.info("Verifying the downloaded package...")
                try:
                    # Verify the package signature using gpg
                    logging.info("Verifying package signature using gpg...")
                    subprocess.check_call(['gpg', '--verify', deb_path], cwd='.')
                    logging.info("Package signature verified successfully.")
                    # 5. Install the package
                    _install_update(parent, deb_path)
                except subprocess.CalledProcessError as e:
                    logging.error(f"Error verifying package signature: {e}")
                    QMessageBox.critical(parent, "Update Failed", f"Error verifying package signature: {e}")
            # Note: The temporary file will be cleaned up by the OS after the process exits.
    else:
        QMessageBox.information(parent, "Up to Date",
                                f"{APP_NAME} (version {current_version}) is already the latest version.")


# The main entry point for update check, which can be called from the GUI
def check_for_self_update(parent: QWidget):
    """
    Main function to check for self-updates.
    It checks if the application is installed as a package or running from source.
    """
    # A simple check to see if we are running from the installed path or source path
    # This is a heuristic and might need refinement.
    # For now, we'll assume if get_installed_version fails, we are in dev mode.
    # The check_for_updates function now handles both installed and source-run versions
    check_for_updates(parent)
