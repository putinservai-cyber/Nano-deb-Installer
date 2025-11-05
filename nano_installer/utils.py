import os
import sys
import io

import subprocess
from pathlib import Path
import re
import time
import tarfile

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QPixmap, QIcon

# -----------------------
# Worker Thread for background tasks
# -----------------------
class WorkerThread(QThread):
    result = pyqtSignal(object)
    progress = pyqtSignal(dict)
    # New signal to notify the worker function that cancellation is requested
    stop_requested = pyqtSignal()

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self._is_running = True
        self._process = None # To hold a reference to the running subprocess

    def run(self):
        try:
            # Pass a reference to this thread instance to the target function
            self.kwargs['worker'] = self
            res = self.fn(*self.args, **self.kwargs)
            self.result.emit(res)
        except Exception as e:
            self.result.emit(e)

    def is_running(self):
        return self._is_running and self.isRunning()

    def set_process(self, proc: subprocess.Popen):
        """Sets the subprocess reference for termination."""
        self._process = proc

    def stop(self):
        """Requests the worker to stop and attempts to terminate the subprocess."""
        self._is_running = False
        self.stop_requested.emit() # Signal the worker function to stop gracefully
        
        if self._process and self._process.poll() is None:
            # The process is still running, attempt to terminate it safely
            try:
                # Send SIGTERM to the process group to stop sudo and the backend
                os.killpg(os.getpgid(self._process.pid), 15) # 15 is SIGTERM
                self._process.wait(timeout=5)
            except (ProcessLookupError, TimeoutError):
                # If SIGTERM fails or times out, use SIGKILL as a last resort
                try:
                    os.killpg(os.getpgid(self._process.pid), 9) # 9 is SIGKILL
                except ProcessLookupError:
                    pass # Process already terminated
            except Exception:
                pass # Ignore other termination errors
        
        self.wait() # Wait for the thread to finish its run() method

# -----------------------
# Helper Functions
# -----------------------
def get_icon(theme_name: str, fallback_path: str = None) -> QIcon:
    """
    Loads an icon from the theme with a fallback to a local file path.
    This is crucial for cross-platform compatibility (e.g., Windows/macOS).
    """
    # 1. Try to load from theme (best for Linux desktop integration)
    theme_icon = QIcon.fromTheme(theme_name)
    if not theme_icon.isNull():
        return theme_icon
    
    # 2. Fallback to local file path
    if fallback_path and Path(fallback_path).exists():
        return QIcon(fallback_path)
        
    # 3. Fallback to a generic theme icon if the first one failed
    # This is a last resort for systems with poor theme support
    generic_theme_icon = QIcon.fromTheme("application-x-executable")
    if not generic_theme_icon.isNull():
        return generic_theme_icon
        
    # 4. Return an empty icon if all else fails
    return QIcon()

def get_deb_info(deb_path: Path, fields: list = None):
    """Extracts specified fields from a .deb file's control information."""
    if fields is None:
        fields = ["Package", "Version", "Maintainer", "Description", "Depends", "Architecture", "Section", "Priority", "Installed-Size"]
    try:
        cmd = ["dpkg-deb", "-f", str(deb_path)] + fields
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        info = {}
        # dpkg-deb -f outputs "Field: Value" pairs, one per line.
        for line in result.stdout.strip().split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                info[key.strip()] = value.strip()
        return info
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

def get_installed_version(pkg_name: str):
    """Gets the installed version of a package. Returns None if not installed."""
    try:
        cmd = ["dpkg-query", "-W", "-f=${Version}", pkg_name]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None

def compare_versions(v1, op, v2):
    """Compares two Debian versions using dpkg. Returns True if condition is met."""
    try:
        cmd = ["dpkg", "--compare-versions", v1, op, v2]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def get_deb_icon_data(deb_path: Path):
    """Extracts icon data from a .deb file using Python's tarfile for performance."""
    try:
        # Find the data archive name (e.g., data.tar.xz)
        ar_list_cmd = ["ar", "t", str(deb_path)]
        ar_list_proc = subprocess.run(ar_list_cmd, capture_output=True, text=True, check=True)
        data_archive_name = next((m for m in ar_list_proc.stdout.splitlines() if m.startswith("data.tar")), None)
        if not data_archive_name:
            return None

        # Extract the data archive into an in-memory bytes buffer to make it seekable
        ar_extract_cmd = ["ar", "p", str(deb_path), data_archive_name]
        ar_proc = subprocess.run(ar_extract_cmd, stdout=subprocess.PIPE, check=True)
        data_archive_stream = io.BytesIO(ar_proc.stdout)

        # Use 'r|*' for streaming decompression, which is more robust than 'r:*'
        with tarfile.open(fileobj=data_archive_stream, mode='r|*') as tf:
            # Build a map of all members for fast lookups
            members_map = {member.name: member for member in tf.getmembers() if member.isfile()}

            icon_name = None
            for member_name, member_obj in members_map.items():
                if member_name.endswith('.desktop') and '/usr/share/applications/' in member_name:
                    desktop_content = tf.extractfile(member_obj).read().decode('utf-8', errors='ignore')
                    for line in desktop_content.split('\n'):
                        if line.strip().startswith("Icon="):
                            icon_name = line.split("=", 1).strip()
                            break
                    if icon_name:
                        break

            if not icon_name:
                return None

            # Find the icon file by searching prioritized paths
            search_paths = [
                f"./usr/share/icons/hicolor/scalable/apps/{icon_name}.svg",
                f"./usr/share/icons/hicolor/256x256/apps/{icon_name}.png",
                f"./usr/share/icons/hicolor/512x512/apps/{icon_name}.png",
                f"./usr/share/pixmaps/{icon_name}.svg",
                f"./usr/share/pixmaps/{icon_name}.png",
                f"./usr/share/pixmaps/{icon_name}.xpm",
            ]

            for path in search_paths:
                if path in members_map:
                    icon_data = tf.extractfile(members_map[path]).read()
                    return icon_data

        return None

    except (subprocess.CalledProcessError, FileNotFoundError, tarfile.TarError, KeyError):
        return None

def get_icon_for_installed_package(pkg_name: str) -> QPixmap:
    """Finds the icon for an installed package by querying dpkg."""
    try:
        # Find .desktop file installed by the package
        dpkg_cmd = ["dpkg", "-L", pkg_name]
        dpkg_proc = subprocess.Popen(dpkg_cmd, stdout=subprocess.PIPE, text=True, encoding='utf-8')

        grep_cmd = ["grep", r'/usr/share/applications/.*\.desktop$']
        grep_proc = subprocess.Popen(grep_cmd, stdin=dpkg_proc.stdout, stdout=subprocess.PIPE, text=True, encoding='utf-8')

        dpkg_proc.stdout.close()
        desktop_files_output, _ = grep_proc.communicate()

        if not desktop_files_output:
            return None

        # Take the first .desktop file found
        desktop_files = desktop_files_output.strip().split('\n')
        if not desktop_files or not desktop_files[0]:
            return None
            
        desktop_file_path = desktop_files[0]

        if not Path(desktop_file_path).is_file():
            return None

        # Parse .desktop file for Icon=
        icon_name = None
        with open(desktop_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip().startswith("Icon="):
                    icon_name = line.split("=", 1)[1].strip()
                    break
        if not icon_name:
            return None
        # Load icon from theme at a standard size
        return QIcon.fromTheme(icon_name).pixmap(64, 64)
    except (FileNotFoundError, subprocess.CalledProcessError, IndexError):
        return None

def check_missing_dependencies(depends_string: str, worker=None) -> list[str]:
    """
    Checks which packages in the dependency string are not currently installed.
    Returns a list of missing dependency groups (represented by their first alternative).
    """
    missing_deps = []
    dependency_groups = parse_dependencies(depends_string)
    
    for group in dependency_groups:
        is_satisfied = False
        
        # Check if any alternative in the group is installed
        for dep_info in group:
            pkg_name = dep_info['name']
            # Check if the package is installed
            try:
                # dpkg-query -W -f='${Status}' <pkg>
                # We only care if it's installed, not the version, as apt will handle version resolution.
                cmd = ["dpkg-query", "-W", "-f=${Status}", pkg_name]
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
                status = result.stdout.strip()
                
                # dpkg-query returns non-zero if the package is not found.
                # If it returns 0, we check the status.
                if result.returncode == 0 and "install ok installed" in status:
                    is_satisfied = True
                    break # Dependency satisfied by this alternative
            except Exception:
                # Ignore errors and continue to the next alternative
                continue
        
        if not is_satisfied:
            # If no alternative satisfied the dependency, add the first one to the missing list
            # This is for display purposes in the GUI.
            missing_deps.append(group[0]['name'])
            
    return missing_deps

def parse_dependencies(depends_string: str) -> list[list[dict]]:
    """
    Parses dependency string and returns a list of dependency groups.
    Each group is a list of dictionaries representing alternatives.
    Example: [[{'name': 'pkg1', 'version': ''}], [{'name': 'pkg2', 'version': ''}, {'name': 'pkg3', 'version': ''}]]
    """
    if not depends_string:
        return []
    
    dependency_groups = []

    # Split by comma for individual dependency entries
    for dep_entry in depends_string.split(','):
        dep_entry = dep_entry.strip()
        if not dep_entry:
            continue

        # Handle alternative dependencies (e.g., package1 | package2)
        alternatives = []
        for alternative_str in dep_entry.split('|'):
            alternative_str = alternative_str.strip()
            if not alternative_str:
                continue

            # Use regex to separate the package name from the version specifier
            # The regex is slightly modified to allow uppercase letters in package names (e.g., libGL)
            match = re.match(r'^\s*([a-zA-Z0-9.+-]+)\s*(\(.*\))?\s*$', alternative_str)
            if match:
                pkg_name = match.group(1)
                version_spec = match.group(2) or "" # e.g., "(>= 1.2.3)"
                
                # Only add the package name and version specifier
                alternatives.append({'name': pkg_name, 'version': version_spec.strip()})
        
        if alternatives:
            dependency_groups.append(alternatives)
            
    return dependency_groups

def parse_desktop_file(file_path: Path) -> dict:
    """Parses a .desktop file and returns a dictionary of its main keys."""
    config = {}
    if not file_path.is_file():
        return config
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            in_desktop_entry = False
            for line in f:
                line = line.strip()
                if line == '[Desktop Entry]':
                    in_desktop_entry = True
                    continue
                if not in_desktop_entry or not line or line.startswith('#') or '=' not in line:
                    continue
                if line.startswith('['): # Another section starts
                    break
                key, value = line.split('=', 1)
                if key.strip() in ["Name", "Exec", "Icon", "Comment", "Categories"]:
                    config[key.strip()] = value.strip()
    except IOError:
        return {}
    return config

def is_critical_package(pkg_name: str) -> tuple[bool, str]:
    """Checks if a package is critical to system stability or nano-installer."""
    # Packages that should never be uninstalled for system safety
    critical_packages = {
        # Core system packages
        'base-files', 'base-passwd', 'bash', 'coreutils', 'dash', 'debianutils',
        'diffutils', 'dpkg', 'e2fsprogs', 'findutils', 'grep', 'gzip', 'hostname',
        'init-system-helpers', 'libc6', 'login', 'lsb-base', 'mount', 'passwd',
        'perl-base', 'sed', 'sysvinit-utils', 'tar', 'util-linux', 'zlib1g',
        
        # Package management
        'apt', 'apt-utils', 'dpkg-dev', 'debconf', 'debconf-2.0',
        
        # Essential Python packages
        'python3', 'python3-minimal', 'python3.12', 'python3.12-minimal',
        'python3-apt', 'python3-dbus', 'python3-gi', 'python3-pil',
        
        # Qt/PyQt5 packages (needed for nano-installer)
        'python3-pyqt5', 'python3-pyqt5.qtcore', 'python3-pyqt5.qtgui',
        'python3-pyqt5.qtwidgets', 'libqt5core5a', 'libqt5gui5', 'libqt5widgets5',
        
        # KDE essential packages
        'kde-runtime', 'kdelibs5-data', 'plasma-desktop', 'systemsettings',
        
        # Network and security
        'ca-certificates', 'openssl', 'libssl3', 'gnupg', 'gpgv',
        
        # Kernel and drivers
        'linux-image-generic', 'linux-headers-generic', 'initramfs-tools'
    }
    
    # Check if it's a critical package
    if pkg_name.lower() in critical_packages:
        return True, f"'{pkg_name}' is a critical system package required for system stability."
    
    # Check if it's a kernel package
    if any(kernel in pkg_name.lower() for kernel in ['linux-image', 'linux-headers', 'linux-modules']):
        return True, f"'{pkg_name}' is a kernel package that should not be removed."
    
    # Check if it's related to nano-installer itself
    # NOTE: Temporarily disabled to allow testing of self-update/reinstall in dev environment.
    # if 'nano-installer' in pkg_name.lower():
    #     return True, f"'{pkg_name}' appears to be the nano-installer package itself. Self-uninstallation is not supported for security reasons."
    
    return False, ""

def get_nano_installer_package_name() -> str:
    """
    Attempts to determine the package name of nano-installer if installed as a .deb.
    Returns an empty string if not found.
    """
    try:
        # Get the path of the current script
        # In a packaged app, this might be in /usr/lib/python3/dist-packages/nano_installer/
        script_path = Path(os.path.abspath(sys.argv))

        # Try to find which package owns this file
        result = subprocess.run(['dpkg', '-S', str(script_path)],
                                capture_output=True, text=True, check=False)
        if result.returncode == 0:
            # Extract package name from output like "package-name: /path/to/file"
            return result.stdout.strip().split(':')[0]
    except Exception:
        pass

    # Fallback: common names for nano-installer
    possible_names = ['nano-installer', 'nano-installer-kde', 'nano-installer-plasma']
    for name in possible_names:
        if get_installed_version(name):
            return name

    return ""