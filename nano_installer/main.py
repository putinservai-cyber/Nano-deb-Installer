import sys
import os
from pathlib import Path
from urllib.parse import urlparse, unquote
import subprocess

# Add the project root to sys.path if run directly
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QApplication,
    QMessageBox,
    QStackedWidget,
    QWidget,
    QVBoxLayout,
    QMainWindow,
    QAction,
)

# Local imports (now absolute)
from nano_installer.settings import SettingsManager, SettingsPage
from nano_installer.gui_components import OfflinePage
from nano_installer.wizards import InstallWizard, UninstallWizard
from nano_installer.utils import get_deb_info, get_installed_version, compare_versions, is_critical_package
from nano_installer.constants import APP_NAME, BACKEND_PATH
from nano_installer.self_update import check_for_updates

# -----------------------
# Core Logic
# -----------------------
def process_deb_file(path_str: str, parent: QWidget):
    """Core logic to process a .deb file."""
    path = Path(path_str)
    settings = SettingsManager()

    deb_info = get_deb_info(path, fields=["Package", "Version"])
    if not deb_info or not deb_info.get("Package") or not deb_info.get("Version"):
        QMessageBox.warning(parent, "Error", "Could not read package information from the .deb file.")
        return

    pkg_name = deb_info["Package"]
    deb_version = deb_info["Version"]
    
    # Check if this is a critical package
    is_critical, critical_reason = is_critical_package(pkg_name)
    if is_critical:
        QMessageBox.critical(parent, "Critical Package Warning", 
                           f"Installation blocked for safety reasons:\n\n{critical_reason}\n\n"
                           "Installing this package through nano-installer could potentially cause system instability.")
        return

    # 2. Check installed version
    installed_version = get_installed_version(pkg_name)

    is_extract_mode = settings.get_setting("install_and_extract_enabled", "false") == "true"

    # 3. Decide the flow
    if not installed_version:
        # Case 1: Not installed -> Install
        wiz = InstallWizard(path, parent, is_extract_mode=is_extract_mode, pkg_name=pkg_name)
        wiz.exec_()
    else:
        # Case 2: It is installed, compare versions
        is_newer = compare_versions(deb_version, 'gt', installed_version)
        is_same = compare_versions(deb_version, 'eq', installed_version)

        if is_newer:
            # Update
            reply = QMessageBox.question(parent, "Update Available",
                                         f"An update is available for '{pkg_name}'.\n\n"
                                         f"Installed version: {installed_version}\n"
                                         f"New version: {deb_version}\n\n"
                                         "Do you want to update?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if reply == QMessageBox.Yes:
                wiz = InstallWizard(path, parent, is_update=True, is_extract_mode=is_extract_mode, pkg_name=pkg_name)
                wiz.exec_()
        elif is_same:
            # Reinstall or Uninstall
            msg_box = QMessageBox(parent)
            msg_box.setIcon(QMessageBox.Information)
            msg_box.setText(f"Package '{pkg_name}' version {installed_version} is already installed.")
            msg_box.setInformativeText("What would you like to do?")
            reinstall_button = msg_box.addButton("Reinstall", QMessageBox.ActionRole)
            uninstall_button = msg_box.addButton("Uninstall", QMessageBox.ActionRole)
            msg_box.addButton(QMessageBox.Cancel)
            msg_box.exec_()

            clicked_button = msg_box.clickedButton()
            if clicked_button == reinstall_button:
                wiz = InstallWizard(path, parent, is_reinstall=True, is_extract_mode=is_extract_mode, pkg_name=pkg_name)
                wiz.exec_()
            elif clicked_button == uninstall_button:
                uninstall_wiz = UninstallWizard(pkg_name, parent)
                uninstall_wiz.exec_()
        else: # deb_version is older
            msg_box = QMessageBox(parent)
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setWindowTitle("Older Version Detected")
            msg_box.setText(f"The selected file contains an older version of '{pkg_name}'.")
            msg_box.setInformativeText(f"Installed version: {installed_version}\nSelected version: {deb_version}\n\nDo you want to roll back to the older version?")
            
            rollback_button = msg_box.addButton("Roll Back", QMessageBox.AcceptRole)
            msg_box.addButton(QMessageBox.Cancel)
            msg_box.exec_()

            if msg_box.clickedButton() == rollback_button:
                wiz = InstallWizard(path, parent, is_downgrade=True, is_extract_mode=is_extract_mode, pkg_name=pkg_name)
                wiz.exec_()

# -----------------------
# Main Application Window
# -----------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}")
        self.setWindowIcon(QIcon.fromTheme("system-software-install"))
        self.setFixedSize(550, 450)

        # Central widget setup
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        self.stack = QStackedWidget(central_widget)
        self.offline_page = OfflinePage()
        self.settings_page = SettingsPage()

        self.stack.addWidget(self.offline_page)
        self.stack.addWidget(self.settings_page)

        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

        # self._setup_menu_bar() # Menu bar removed per user request

        # Connect signals for page navigation (kept for internal page buttons/links)
        # The settings_requested signal now carries the desired section index (int)
        self.offline_page.settings_requested.connect(self._show_settings_page)
        self.settings_page.back_requested.connect(lambda: self.stack.setCurrentWidget(self.offline_page))
        
        # Connect new menu actions from OfflinePage
        self.offline_page.update_requested.connect(self._show_update_placeholder)
        self.offline_page.about_requested.connect(lambda: show_about_dialog(self))

    def _show_settings_page(self, section_index: int = SettingsPage.SECTION_GENERAL):
        """Switches to the settings page and sets the active section."""
        self.settings_page.set_section(section_index)
        self.stack.setCurrentWidget(self.settings_page)

    def _show_update_placeholder(self):
        check_for_updates(self)

def handle_command_line_args():
    """Handle command-line arguments for KDE shortcut integration."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Nano Installer - Advanced .deb Package Manager')
    parser.add_argument('file', nargs='?', help='.deb file to install')
    parser.add_argument('--uninstall', metavar='PACKAGE', help='Uninstall specified package')
    parser.add_argument('--settings', action='store_true', help='Open settings dialog')
    parser.add_argument('--about', action='store_true', help='Show about dialog')
    
    args = parser.parse_args()
    return args

def show_about_dialog(parent=None):
    """Show KDE-style about dialog."""
    try:
        from PyQt5.QtWidgets import QMessageBox
        about_text = f"""
<h2>{APP_NAME}</h2>
<p><b>Version:</b> 1.0.4</p>
<p><b>Advanced .deb Package Installer with KDE Integration</b></p>
<p>Features:</p>
<ul>
<li>Security scanning with VirusTotal integration</li>
<li>Dependency management and automatic installation</li>
<li>KDE Plasma desktop shortcut creation</li>
<li>Safe installation and uninstallation</li>
<li>Native KDE theme integration</li>
</ul>
<p><b>Created with ❤️ for KDE neon users</b></p>
"""
        
        msg_box = QMessageBox(parent)
        msg_box.setWindowTitle(f"About {APP_NAME}")
        msg_box.setTextFormat(Qt.RichText)
        msg_box.setText(about_text)
        msg_box.setIconPixmap(QIcon.fromTheme("system-software-install").pixmap(64, 64))
        msg_box.exec_()
        
    except Exception:
        # Fallback to kdialog
        subprocess.run([
            'kdialog', '--title', f'About {APP_NAME}',
            '--msgbox', f'{APP_NAME} v1.0.4\nAdvanced .deb Package Installer'
        ], capture_output=True)

def main():
    # Set appropriate platform theme for better desktop integration
    desktop_env = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    
    # Only set platform theme if not already set by user
    if "QT_QPA_PLATFORMTHEME" not in os.environ:
        # KDE Plasma and KDE neon
        if "kde" in desktop_env or "plasma" in desktop_env:
            # Use native KDE styling
            os.environ["QT_QPA_PLATFORMTHEME"] = "kde"
        # GTK-based desktops
        elif any(desktop in desktop_env for desktop in ["gnome", "cinnamon", "mate", "xfce", "budgie"]):
            os.environ["QT_QPA_PLATFORMTHEME"] = "gtk3"
        # For other desktops, let Qt decide or use system default

    # Handle command-line arguments
    args = handle_command_line_args()
    
    app = QApplication(sys.argv)

    # Handle special command-line actions
    if args.about:
        show_about_dialog()
        sys.exit(0)
    
    if args.settings:
        main_win = MainWindow()
        # When launched with --settings, default to General section (index 0)
        main_win._show_settings_page(SettingsPage.SECTION_GENERAL)
        main_win.show()
        sys.exit(app.exec_())
    
    if args.uninstall:
        # Show uninstall wizard for specified package
        temp_parent = QWidget()
        uninstall_wiz = UninstallWizard(args.uninstall, temp_parent)
        uninstall_wiz.exec_()
        sys.exit(0)

    file_to_process = None
    # Check if a file path was passed as a command-line argument
    if args.file:
        path_arg = args.file

        # Handle file URIs (e.g., from GNOME Files) which start with 'file://'
        if path_arg.startswith('file://'):
            path_arg = unquote(urlparse(path_arg).path)

        path = Path(path_arg)
        if path.is_file() and path.suffix == '.deb':
            file_to_process = str(path)

    if file_to_process:
        # Launched with a .deb file. We don't need to show the main window.
        # We create a temporary, invisible parent widget for our dialogs.
        temp_parent = QWidget()
        process_deb_file(file_to_process, temp_parent)
        # The application will exit after the modal wizard/dialog closes.
        sys.exit(0)
    else:
        # Launched normally, without a file. Show the main window.
        main_win = MainWindow()
        main_win.show()
        sys.exit(app.exec_())

if __name__ == "__main__":
    main()