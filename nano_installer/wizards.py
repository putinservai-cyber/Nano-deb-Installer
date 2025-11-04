import sys
from pathlib import Path
# Add the project root to sys.path if run directly
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))
import subprocess
import time
import re
import hashlib
from pathlib import Path
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QFont, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QComboBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

# Imports from other modules
from nano_installer.settings import SettingsManager
from nano_installer.utils import (
    WorkerThread,
    get_deb_info,
    get_installed_version,
    compare_versions,
    get_icon_for_installed_package,
    get_deb_icon_data,
    parse_dependencies,
    get_nano_installer_package_name,
)
from nano_installer.security import scan_with_virustotal, calculate_file_hash
from nano_installer.gui_components import AuthenticationDialog, DependencyPopup
from nano_installer.constants import APP_NAME, get_backend_path # APP_NAME and get_backend_path are defined in constants.py

# -----------------------
# Base Wizard for common operations
# -----------------------
class BaseOperationWizard(QWizard):
    def __init__(self, pkg_name, parent=None):
        super().__init__(parent)
        self.pkg_name = pkg_name
        self.settings = SettingsManager()
        self._used_saved_password = False
        self._worker_thread = None
        self._previous_id = -1 # Track previous page ID

        self.setFixedSize(600, 500)
        self.setWizardStyle(QWizard.ModernStyle)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowMinimizeButtonHint & ~Qt.WindowMaximizeButtonHint)

    def _create_progress_page(self, title, subtitle):
        """Creates a standardized progress page."""
        page = QWizardPage()
        page.setTitle(title)
        page.setSubTitle(subtitle)
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Progress:"))
        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        self.btn_toggle_log = QPushButton("Show Details")
        self.btn_toggle_log.setCheckable(True)
        self.btn_toggle_log.toggled.connect(self.on_toggle_log)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        mono_font = QFont()
        mono_font.setFamily("monospace")
        mono_font.setStyleHint(QFont.TypeWriter)
        self.log_text.setFont(mono_font)
        self.log_text.setVisible(False)

        layout.addWidget(self.btn_toggle_log)
        layout.addWidget(self.log_text)
        return page

    def on_toggle_log(self, checked):
        self.btn_toggle_log.setText("Hide Details" if checked else "Show Details")
        self.log_text.setVisible(checked)

    def _execute_operation(self):
        """Handles password retrieval and starts the worker thread."""
        self.button(QWizard.BackButton).setEnabled(False)
        self.button(QWizard.NextButton).setEnabled(False)
        self.progress.setValue(5)
        self.log_text.clear()

        auto_enabled = self.settings.get_setting("auto_password_enabled", "false") == "true"
        saved_password = self.settings.get_password() if auto_enabled else None

        if saved_password:
            self.log_text.append("[INFO] Using saved password for authentication.")
            self._start_worker_thread(saved_password, used_saved_password=True)
        else:
            self._ask_password_and_execute()

    def _ask_password_and_execute(self, is_retry=False):
        """Shows the authentication dialog and starts the worker thread."""
        password = AuthenticationDialog.get_auth_password(
            parent=self,
            operation=self._get_operation_verb(),
            package_name=self.pkg_name,
            is_retry=is_retry
        )
        if not password:
            self.back()
            return
        self._start_worker_thread(password)

    def _start_worker_thread(self, password, used_saved_password=False):
        """Initializes and starts the background worker thread."""
        self._used_saved_password = used_saved_password
        worker_fn, on_progress, on_done = self._get_worker_callbacks()
        self._worker_thread = WorkerThread(worker_fn, password=password)
        self._worker_thread.progress.connect(on_progress)
        self._worker_thread.result.connect(on_done)
        self._worker_thread.start()

    # --- Abstract methods for subclasses to implement ---
    def _get_operation_verb(self) -> str:
        raise NotImplementedError

    def _get_worker_callbacks(self) -> tuple:
        raise NotImplementedError

    def initializePage(self, id):
        """Called before a page is shown. Used to track the previous page ID."""
        # When initializePage(id) is called, self.currentId() still holds the ID of the previous page.
        self._previous_id = self.currentId()
        super().initializePage(id)

# Install wizard (offline .deb)
# -----------------------
class InstallWizard(BaseOperationWizard):
    def __init__(self, deb_path: Path, parent=None, is_update=False, is_reinstall=False, is_extract_mode=False, is_downgrade=False, pkg_name=None):
        super().__init__(pkg_name, parent)
        self.deb_path = deb_path
        self.is_reinstall = is_reinstall
        self.is_update = is_update
        self.is_downgrade = is_downgrade
        self.settings = SettingsManager()
        self.is_extract_mode = is_extract_mode
        self.is_create_shortcut_mode = self.settings.get_setting("create_desktop_shortcut_enabled", "false") == "true"
        self._used_saved_password = False

        verb = self._get_operation_verb()

        self.setWindowTitle(f"{verb} {deb_path.name}")

        # Page 1: Preparation
        self.p1 = QWizardPage()
        self.p1.setTitle("Security Scan")
        self.p1.setSubTitle("Please wait while the package is analyzed and scanned for threats.")
        l1 = QVBoxLayout(self.p1)
        self.prep_status_label = QLabel("Initializing...")
        self.prep_status_label.setWordWrap(True)
        l1.addWidget(self.prep_status_label)
        self.prep_progress = QProgressBar()
        self.prep_progress.setRange(0, 100)
        self.prep_progress.setValue(0)
        l1.addWidget(self.prep_progress)
        self.scan_result_text = QTextEdit()
        self.scan_result_text.setReadOnly(True)
        self.scan_result_text.setLineWrapMode(QTextEdit.NoWrap)
        self.scan_result_text.setVisible(False)
        l1.addWidget(self.scan_result_text)

        self.cb_force_install = QCheckBox("Install anyway, even if threats are found or the scan fails.")
        self.cb_force_install.setVisible(False)
        # Let the wizard handle the next button by telling it when the page's completeness changes.
        self.cb_force_install.stateChanged.connect(self.p1.completeChanged.emit)
        l1.addWidget(self.cb_force_install)
        l1.addStretch()

        # Page 2: Detailed Package Information
        p2 = QWizardPage()
        p2.setTitle("Package Information")
        p2.setSubTitle("Review detailed package information and dependencies.")
        l2 = QVBoxLayout(p2)
        
        # Create tab widget for organized info
        self.info_tabs = QTabWidget()
        
        # General tab
        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        
        # Package details
        self.pkg_name_detail = QLabel("Package: Loading...")
        self.pkg_version_detail = QLabel("Version: Loading...")
        self.pkg_maintainer_detail = QLabel("Developer/Maintainer: Loading...")
        self.pkg_architecture_detail = QLabel("Architecture: Loading...")
        self.pkg_size_detail = QLabel("Installed Size: Loading...")
        self.pkg_section_detail = QLabel("Category: Loading...")
        
        for label in [self.pkg_name_detail, self.pkg_version_detail, self.pkg_maintainer_detail, 
                      self.pkg_architecture_detail, self.pkg_size_detail, self.pkg_section_detail]:
            label.setWordWrap(True)
            general_layout.addWidget(label)
        
        general_layout.addStretch()
        self.info_tabs.addTab(general_tab, "General")
        
        # Description tab
        desc_tab = QWidget()
        desc_layout = QVBoxLayout(desc_tab)
        self.pkg_description = QTextEdit()
        self.pkg_description.setReadOnly(True)
        self.pkg_description.setPlainText("Loading package description...")
        desc_layout.addWidget(self.pkg_description)
        self.info_tabs.addTab(desc_tab, "Description")
        
        # Dependencies tab
        deps_tab = QWidget()
        deps_layout = QVBoxLayout(deps_tab)
        deps_layout.addWidget(QLabel("This package depends on:"))
        self.deps_list = QListWidget()
        deps_layout.addWidget(self.deps_list)
        self.info_tabs.addTab(deps_tab, "Dependencies")
        
        l2.addWidget(self.info_tabs)
        
        # Page 3: Summary and Ready to Install
        p3 = QWizardPage()
        p3.setTitle(f"Ready to {verb}")
        p3.setSubTitle("Review the installation summary below.")
        l3 = QVBoxLayout(p3)

        # --- Top Summary (on Page 3) ---
        summary_layout = QHBoxLayout()
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(64, 64)
        summary_layout.addWidget(self.icon_label)

        text_layout = QVBoxLayout()
        self.package_name_label = QLabel(f"Install {self.deb_path.name}")
        font = self.package_name_label.font()
        font.setPointSize(14)
        font.setBold(True)
        self.package_name_label.setFont(font)
        self.package_name_label.setWordWrap(True)

        self.package_details_label = QLabel("Loading package information...")
        self.package_details_label.setWordWrap(True)

        text_layout.addWidget(self.package_name_label)
        text_layout.addWidget(self.package_details_label)

        summary_layout.addLayout(text_layout, 1)
        l3.addLayout(summary_layout)
        l3.addSpacing(15)

        # --- Add a warning/info label for the combined mode ---
        self.extract_info_label = QLabel(
            "<b>Note:</b> In addition to installation, the package contents will also be extracted to a location you choose on the next page."
        )
        self.extract_info_label.setWordWrap(True)
        self.extract_info_label.setStyleSheet("background-color: #333; border: 1px solid orange; padding: 5px;")
        self.extract_info_label.setVisible(self.is_extract_mode)
        l3.addWidget(self.extract_info_label)

        # --- Desktop Shortcut Option ---
        self.cb_create_shortcut_instance = QCheckBox("Create a desktop shortcut")
        self.cb_create_shortcut_instance.setChecked(True)
        self.cb_create_shortcut_instance.setVisible(self.is_create_shortcut_mode)
        l3.addWidget(self.cb_create_shortcut_instance)

        l3.addStretch()

        # Page 4: Extract Location
        p_extract = QWizardPage()
        p_extract.setTitle("Select Extraction Location")
        p_extract.setSubTitle("Choose a directory where the package contents will be extracted.")
        l_extract = QVBoxLayout(p_extract)
        self.extract_path_edit = QLineEdit()
        self.extract_path_edit.setPlaceholderText("Select a destination folder...")
        self.extract_path_edit.setReadOnly(True)
        btn_browse = QPushButton("Browse...")
        extract_layout = QHBoxLayout()
        extract_layout.addWidget(self.extract_path_edit)
        extract_layout.addWidget(btn_browse)
        l_extract.addLayout(extract_layout)
        l_extract.addStretch()

        btn_browse.clicked.connect(self.select_extract_dir)
        self.extract_path_edit.textChanged.connect(p_extract.completeChanged.emit)
        p_extract.isComplete = self.is_p_extract_complete

        # Page 5: Installing / Extracting
        p_install = self._create_progress_page("Installing", "Please wait...")
        self.install_log_text = self.log_text # Alias for clarity

        # Page 6: Success
        p_success = QWizardPage()
        p_success.setFinalPage(True)
        l_success = QVBoxLayout(p_success)
        self.success_icon = QLabel()
        self.success_icon.setPixmap(QIcon.fromTheme("emblem-ok").pixmap(64, 64))
        self.success_icon.setAlignment(Qt.AlignCenter)
        self.success_label = QLabel(f"<b>{self.deb_path.name}</b> was {verb.lower()}ed successfully.")
        self.success_label.setAlignment(Qt.AlignCenter)
        l_success.addStretch()
        l_success.addWidget(self.success_icon)
        l_success.addSpacing(10)
        l_success.addWidget(self.success_label)
        l_success.addStretch()

        self.setPage(1, self.p1)
        self.setPage(2, p2)
        self.setPage(3, p3)
        self.setPage(4, p_extract)
        self.setPage(5, p_install)
        self.setPage(6, p_success)

        self._summary_loaded = False
        self._scan_finished = False
        self._scan_status = None # Explicitly initialize
        self.currentIdChanged.connect(self.on_page_changed)

        # Override isComplete for the first page to control the "Next" button.
        self.p1.isComplete = self.is_p1_complete

    def _get_operation_verb(self):
        if self.is_update:
            return "Update"
        if self.is_reinstall:
            return "Reinstall"
        if self.is_downgrade:
            return "Roll Back"
        return "Install"

    def nextId(self):
        current = self.currentId()
        if current == 3: # After ready to install page
            if self.is_extract_mode:
                return 4 # Go to extract location page
            else:
                return 5 # Go to install progress page
        elif current == 4: # After extract location page
            return 5 # Go to progress page
        return super().nextId()

    def setVisible(self, visible):
        super().setVisible(visible)
        if visible and not self._summary_loaded:
            self.load_summary()

    def load_summary(self):
        self.prep_status_label.setText("Loading package information...")
        self.prep_progress.setValue(10)

        def on_info_loaded(info):
            # First, check if the worker thread returned an error
            if isinstance(info, Exception):
                self.package_name_label.setText(f"Error loading {self.deb_path.name}")
                self.package_details_label.setText(f"<font color='red'>Error loading package info: {info}</font>")
                self.icon_label.setPixmap(QIcon.fromTheme("dialog-error").pixmap(64, 64))
                self.prep_status_label.setText(f"Error: Could not load package information. {info}")
                self.prep_progress.setStyleSheet("QProgressBar::chunk { background-color: red; }")
                self._scan_finished = True # The process is finished, even if it's an error.
                self._summary_loaded = True
                self._scan_status = "error" # Treat as an error
                self.handle_scan_finished()
                return

            # If we get here, we expect a dictionary.
            if not isinstance(info, dict):
                self.package_details_label.setText("<font color='red'>Could not load package information (unexpected data type).</font>")
                return

            deb_info = info.get("deb_info", {})
            icon_data = info.get("icon_data")
            
            name = deb_info.get("Package", self.deb_path.name)
            version = deb_info.get("Version", "Unknown")
            maintainer = deb_info.get("Maintainer", "Unknown")
            architecture = deb_info.get("Architecture", "Unknown")
            size = deb_info.get("Installed-Size", "Unknown")
            section = deb_info.get("Section", "Unknown")
            description = deb_info.get("Description", "No description available.")
            depends = deb_info.get("Depends", "")

            # Update detailed info tabs
            self.pkg_name_detail.setText(f"<b>Package:</b> {name}")
            self.pkg_version_detail.setText(f"<b>Version:</b> {version}")
            self.pkg_maintainer_detail.setText(f"<b>Developer/Maintainer:</b> {maintainer}")
            self.pkg_architecture_detail.setText(f"<b>Architecture:</b> {architecture}")
            if size != "Unknown":
                self.pkg_size_detail.setText(f"<b>Installed Size:</b> {size} KB")
            else:
                self.pkg_size_detail.setText(f"<b>Installed Size:</b> {size}")
            self.pkg_section_detail.setText(f"<b>Category:</b> {section}")
            
            # Update description
            self.pkg_description.setPlainText(description)
            
            # Update dependencies
            self.deps_list.clear()
            if depends:
                # Parse dependencies (they're comma-separated with version info)
                parsed_deps = parse_dependencies(depends)
                for dep_info in parsed_deps:
                    display_text = f"• {dep_info['name']} {dep_info['version']}"
                    self.deps_list.addItem(display_text.strip())
            else:
                self.deps_list.addItem("• No dependencies required")

            self.package_name_label.setText(f"Install {name}")
            self.package_details_label.setText(f"Version: {version} | From: {self.deb_path.name}")

            if icon_data:
                pixmap = QPixmap()
                pixmap.loadFromData(icon_data)
                scaled_pixmap = pixmap.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.icon_label.setPixmap(scaled_pixmap)
                self.success_icon.setPixmap(scaled_pixmap)
            else:
                generic_pixmap = QIcon.fromTheme("package-x-generic").pixmap(64, 64)
                self.icon_label.setPixmap(generic_pixmap)
                self.success_icon.setPixmap(generic_pixmap)

            self._summary_loaded = True
            self.prep_progress.setValue(25)
            self.do_scan() # Chain the scan after loading summary

        def get_info(deb_path, worker=None):
            # get_deb_icon_data is imported from utils
            info = get_deb_info(deb_path) or {}  # Get all available fields
            return {"deb_info": info, "icon_data": get_deb_icon_data(deb_path)}

        self.icon_label.setPixmap(QIcon.fromTheme("package-x-generic").pixmap(64, 64))
        worker = WorkerThread(get_info, self.deb_path)
        worker.result.connect(on_info_loaded)
        worker.start()
        self._summary_worker = worker

    @pyqtSlot(int)
    def on_page_changed(self, idx):
        # The next button state is managed by the scan/load process, not page changes.
        if idx == 5:  # Switched to Progress page
            self.do_operation()

        # Hide the back button on the final page
        page = self.currentPage()
        if page and page.isFinalPage():
            self.button(QWizard.BackButton).hide()

    def select_extract_dir(self):
        dialog = QFileDialog(self)
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setWindowTitle("Select Directory to Extract To")
        dialog.setDirectory(str(Path.home()))
        # Use native file dialog for better desktop integration
        dialog.setOption(QFileDialog.DontUseNativeDialog, False)

        if dialog.exec_():
            selected_dirs = dialog.selectedFiles()
            if selected_dirs:
                self.extract_path_edit.setText(selected_dirs[0])

    def is_p_extract_complete(self):
        path_text = self.extract_path_edit.text()
        return bool(path_text and Path(path_text).is_dir())

    def is_p1_complete(self):
        """
        This method is assigned to the first page's isComplete property.
        The wizard uses this to enable/disable the 'Next' button.
        """
        if not self._scan_finished:
            return False # Wait for scan to finish

        if self._scan_status == "clean":
            return True # Clean scan
        elif self._scan_status in ("danger", "suspicious", "error"):
            # If scan failed, user must force install
            return self.cb_force_install.isChecked()
        return False # Default to disabled

    def do_scan(self):
        self.prep_status_label.setText("Preparing security scan...")

        def on_progress(data):
            line = data.get("line", "")
            self.prep_status_label.setText(line)
            # Fake progress during scan
            if "Calculating hash" in line:
                self.prep_progress.setValue(40)
            elif "Querying" in line:
                self.prep_progress.setValue(80)

        def on_done(res):
            self._scan_finished = True
            if isinstance(res, Exception):
                self._scan_status = "error"
                # The new exception from scan_with_virustotal will have a good message.
                self.scan_result_text.setText(f"{res}")
            elif isinstance(res, str):
                self.scan_result_text.setText(res)
                if "DANGER!" in res:
                    self._scan_status = "danger"
                elif "SUSPICIOUS" in res:
                    self._scan_status = "suspicious"
                elif "Clean" in res:
                    self._scan_status = "clean"
                elif "UNKNOWN" in res: # Handle network errors / skipped scans
                    self._scan_status = "error"
                else: # The string is not a recognized report format
                    self._scan_status = "error"
                    self.scan_result_text.append("\n\n[Error] Could not parse the scan result.")
            else: # The worker returned something unexpected (e.g., None)
                self._scan_status = "error"
                self.scan_result_text.setText(f"The scanner returned an unexpected result type: {type(res)}")

            self.handle_scan_finished()

        self._scan_thread = WorkerThread(scan_with_virustotal, str(self.deb_path))
        self._scan_thread.progress.connect(on_progress)
        self._scan_thread.result.connect(on_done)
        self._scan_thread.start()

    def handle_scan_finished(self):
        self.prep_progress.setValue(100)

        if self._scan_status == "clean":
            self.prep_status_label.setText("<font color='green'><b>Scan Complete: No threats found.</b></font>")
            self.scan_result_text.setVisible(False)
            self.cb_force_install.setVisible(False)
        else:
            # For ALL other cases (error, suspicious, danger), stop and show info.
            self.scan_result_text.setVisible(True)
            self.cb_force_install.setVisible(True)

            if self._scan_status == "danger":
                self.prep_status_label.setText("<font color='red'><b>DANGER! Threats Detected!</b></font>")
            elif self._scan_status == "suspicious":
                self.prep_status_label.setText("<font color='orange'><b>Warning: Suspicious File</b></font>")
            elif self._scan_status == "error":
                self.prep_status_label.setText("<font color='orange'><b>Scan Error</b></font>")
                self.prep_progress.setStyleSheet("QProgressBar::chunk { background-color: red; }")
            else: # Fallback for an unknown or unexpected status
                self._scan_status = "error" # Treat as an error
                self.prep_status_label.setText("<font color='orange'><b>Unknown Scan Status</b></font>")
                self.scan_result_text.setText("The security scan finished with an unexpected status. Installation is not recommended.")
                self.prep_progress.setStyleSheet("QProgressBar::chunk { background-color: red; }")

        # Notify the wizard that the page's completeness may have changed.
        self.p1.completeChanged.emit()

    def do_operation(self):
        """Prepares titles and starts the installation process."""
        verb = self._get_operation_verb()
        self.page(5).setTitle(f"{verb}ing" + (" and Extracting" if self.is_extract_mode else ""))
        self.page(5).setSubTitle(f"Please wait while the package is being {verb.lower()}ed...")
        self._execute_operation()

    def _ask_password_and_execute_install(self, is_retry=False):
        # Get package name for display
        pkg_display_name = self.pkg_name or self.deb_path.name
        
        # Use new authentication dialog
        password = AuthenticationDialog.get_auth_password(
            parent=self,
            operation="install software",
            package_name=pkg_display_name,
            is_retry=is_retry
        )
        
        if not password:
            self.back()  # User cancelled password, go back to the summary page.
            return  # Stop further execution

        self._start_install_thread(password)

    def _get_worker_callbacks(self):
        def install(worker=None, password=None):
            try:
                # Now install the main package using the C backend's apt-op command.
                # apt handles dependencies automatically, simplifying the Python worker.
                if worker: worker.progress.emit({"type": "log", "line": "\n--- Starting package installation via C backend ---\n"})
                
                cmd = ["sudo", "-S", get_backend_path(), "apt-op", "install", str(self.deb_path)]
                if self.is_reinstall:
                    cmd.append("--reinstall")

                output_lines = []
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, encoding='utf-8')
                proc.stdin.write(password + '\n')
                proc.stdin.close()

                if worker: worker.progress.emit({"type": "progress", "value": 5})

                while True:
                    if worker and not worker.is_running(): proc.terminate(); break
                    line = proc.stdout.readline()
                    if not line: break
                    output_lines.append(line)
                    if worker: worker.progress.emit({"type": "log", "line": line})

                proc.wait()
                return proc.returncode, "".join(output_lines)
                
            except Exception as e:
                if worker: worker.progress.emit({"type": "log", "line": f"Installation error: {str(e)}\n"})
                return -1, str(e)

        self.dep_popup = None
        
        def on_progress(data):
            data_type = data.get("type", "")
            
            line = data.get("line", "")
            if line:
                self.install_log_text.append(line.strip())
                self.install_log_text.verticalScrollBar().setValue(self.install_log_text.verticalScrollBar().maximum())

            # Try to parse progress from apt output
            match = re.search(r'(\d+)\s*%', line)
            if match:
                # Cap at 99% to ensure only the 'done' callback sets it to 100%
                self.progress.setValue(min(99, int(match.group(1))))
            elif data_type == "progress":
                self.progress.setValue(data["value"])

        def done(result):
            if isinstance(result, Exception):
                QMessageBox.warning(self, APP_NAME, f"Installation failed with an unexpected error: {result}")
                self.button(QWizard.BackButton).setEnabled(True)
                return

            rc, output = result
            # --- New Enhanced Error Handling ---
            # Check for specific errors from our C backend first.
            backend_error_prefix = "[NANO_BACKEND_ERROR]"
            backend_error_line = next((line for line in output.splitlines() if line.startswith(backend_error_prefix)), None)

            if backend_error_line:
                # We have a specific error from our C code.
                error_message = backend_error_line.replace(backend_error_prefix, "").strip()
                QMessageBox.critical(self, "Backend Error", f"A critical error occurred in the backend process:\n\n{error_message}\n\n(Code: {rc})")
                self.progress.setStyleSheet("QProgressBar::chunk { background-color: red; }")
                self.button(QWizard.BackButton).setEnabled(True)
                return
            # --- End of New Error Handling ---

            # Phrases that indicate a password error from different sudo versions/configs
            password_error_phrases = [
                "sorry, try again",
                "authentication failed",
                "incorrect password",
                "incorrect authentication",
            ]
            is_password_error = rc != 0 and any(phrase in output.lower() for phrase in password_error_phrases)

            if rc == 0:
                # --- INSTALLATION SUCCEEDED ---

                # Create shortcut if requested, before handling extraction.
                if self.is_create_shortcut_mode and self.cb_create_shortcut_instance.isChecked():
                    self._create_desktop_shortcut()

                if self.is_extract_mode:
                    self.install_log_text.append("\n--- Installation successful. Starting extraction phase. ---")
                    self.progress.setValue(80)
                    dest_dir = self.extract_path_edit.text()
                    try:
                        extract_cmd = ["dpkg-deb", "-x", str(self.deb_path), dest_dir]
                        subprocess.run(extract_cmd, check=True, capture_output=True, text=True)
                        self.install_log_text.append("Extraction successful.")
                        self.success_label.setText(f"<b>{self.deb_path.name}</b> was installed and extracted successfully.")
                        self.progress.setValue(100)
                        self.next()
                    except (subprocess.CalledProcessError, FileNotFoundError) as e:
                        error_output = e.stderr if hasattr(e, 'stderr') else str(e)
                        self.install_log_text.append(f"\n[ERROR] Extraction failed:\n{error_output}")
                        self.progress.setStyleSheet("QProgressBar::chunk { background-color: orange; }")
                        self.success_label.setText(f"<b>{self.deb_path.name}</b> was installed, but extraction failed.")
                        QMessageBox.warning(self, "Partial Success", "The package was installed successfully, but the final extraction step failed. See log for details.")
                        self.next()
                else:
                    # Standard install, just finish.
                    self.progress.setValue(100)
                    self.next()
            elif is_password_error:
                # --- PASSWORD FAILED ---
                if self._used_saved_password:
                    self.install_log_text.clear()
                    self.install_log_text.append("[ERROR] Saved password was incorrect or has expired. Please enter it manually.")
                    # For security, clear the bad password and disable the feature.
                    self.settings.save_password("")
                    self.settings.set_setting("auto_password_enabled", "false")

                self.progress.setValue(5)
                self.progress.setStyleSheet("") # Reset style
                self._ask_password_and_execute(is_retry=True)
            else:
                # --- GENERIC FAILURE ---
                self.progress.setStyleSheet("QProgressBar::chunk { background-color: red; }")
                QMessageBox.warning(self, APP_NAME, f"Installation failed with an error (code: {rc}). See log for details.")
                self.button(QWizard.BackButton).setEnabled(True)

        return install, on_progress, done

    def _create_desktop_shortcut(self):
        """Creates a proper desktop shortcut with modern .desktop file standards."""
        if not self.pkg_name:
            self.install_log_text.append("[WARNING] Cannot create shortcut: package name is unknown.")
            return

        self.install_log_text.append(f"\n--- Creating desktop shortcut for {self.pkg_name} ---")
        try:
            # 1. Find the original .desktop file installed by the package
            dpkg_cmd = ["dpkg", "-L", self.pkg_name]
            dpkg_proc = subprocess.Popen(dpkg_cmd, stdout=subprocess.PIPE, text=True, encoding='utf-8')
            grep_cmd = ["grep", r'/usr/share/applications/.*\.desktop$']
            grep_proc = subprocess.Popen(grep_cmd, stdin=dpkg_proc.stdout, stdout=subprocess.PIPE, text=True, encoding='utf-8')
            dpkg_proc.stdout.close()
            desktop_files_output, _ = grep_proc.communicate()

            if not desktop_files_output:
                self.install_log_text.append("[WARNING] No .desktop file found for this package. Creating generic shortcut.")
                self._create_generic_shortcut()
                return

            # Process multiple .desktop files if found
            desktop_files = [f.strip() for f in desktop_files_output.strip().split('\n') if f.strip()]
            created_shortcuts = []
            
            for desktop_file_path in desktop_files:
                original_desktop_path = Path(desktop_file_path)
                if not original_desktop_path.is_file():
                    self.install_log_text.append(f"[WARNING] Desktop file '{original_desktop_path}' not found, skipping.")
                    continue

                self.install_log_text.append(f"[INFO] Processing: {original_desktop_path}")

                # 2. Parse the .desktop file
                desktop_info = self._parse_complete_desktop_file(original_desktop_path)
                if not desktop_info.get("Name") or not desktop_info.get("Exec"):
                    self.install_log_text.append(f"[WARNING] Essential fields missing in {original_desktop_path}, skipping.")
                    continue

                # Skip if marked as NoDisplay=true
                if desktop_info.get("NoDisplay", "").lower() == "true":
                    self.install_log_text.append(f"[INFO] Skipping {desktop_info['Name']} (NoDisplay=true)")
                    continue

                # 3. Create enhanced .desktop file
                shortcut_path = self._create_enhanced_shortcut(desktop_info)
                if shortcut_path:
                    created_shortcuts.append(shortcut_path)
                    self.install_log_text.append(f"[SUCCESS] Created shortcut: {shortcut_path}")

            if created_shortcuts:
                self.install_log_text.append(f"[SUCCESS] Created {len(created_shortcuts)} desktop shortcut(s)")
                # Refresh desktop to show new shortcuts
                self._refresh_desktop()
            else:
                self.install_log_text.append("[WARNING] No valid shortcuts could be created")
                
        except Exception as e:
            self.install_log_text.append(f"[ERROR] Failed to create desktop shortcut: {e}")
    
    def _parse_complete_desktop_file(self, file_path: Path) -> dict:
        """Parses a .desktop file completely with all standard fields."""
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
                    if not in_desktop_entry or not line or line.startswith('#'):
                        continue
                    if line.startswith('[') and line.endswith(']'):
                        # Another section starts
                        break
                    if '=' not in line:
                        continue
                        
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # Parse all relevant desktop entry fields
                    relevant_fields = [
                        "Name", "GenericName", "Comment", "Icon", "Exec", "Path", 
                        "Terminal", "Type", "Categories", "Keywords", "StartupNotify",
                        "MimeType", "NoDisplay", "Hidden", "StartupWMClass", "Version"
                    ]
                    
                    if key in relevant_fields:
                        config[key] = value
                        
        except IOError:
            return {}
        return config
    
    def _create_enhanced_shortcut(self, desktop_info: dict) -> Path:
        """Creates an enhanced desktop shortcut with modern standards."""
        # Determine desktop directory
        desktop_dir = self._get_desktop_directory()
        if not desktop_dir:
            return None
        
        # Create safe filename
        app_name = desktop_info.get('Name', 'Unknown App')
        safe_filename = self._create_safe_filename(app_name)
        shortcut_path = desktop_dir / f"{safe_filename}.desktop"
        
        # Avoid filename conflicts
        counter = 1
        original_path = shortcut_path
        while shortcut_path.exists():
            shortcut_path = desktop_dir / f"{safe_filename}_{counter}.desktop"
            counter += 1
        
        # Create enhanced .desktop content
        content = self._build_desktop_file_content(desktop_info)
        
        try:
            # Write the file
            shortcut_path.write_text(content, encoding='utf-8')
            # Set proper permissions (readable and executable)
            shortcut_path.chmod(0o755)
            
            # For KDE/Plasma, mark as trusted
            self._mark_shortcut_trusted(shortcut_path)
            
            return shortcut_path
            
        except Exception as e:
            self.install_log_text.append(f"[ERROR] Failed to write shortcut file: {e}")
            return None
    
    def _get_desktop_directory(self) -> Path:
        """Gets the appropriate desktop directory for shortcuts."""
        # Try XDG desktop directory first
        try:
            result = subprocess.run(['xdg-user-dir', 'DESKTOP'], 
                                  capture_output=True, text=True, check=True)
            desktop_path = Path(result.stdout.strip())
            if desktop_path.is_dir():
                return desktop_path
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
        
        # Fallback to standard locations
        for desktop_name in ['Desktop', 'Рабочий стол', 'デスクトップ', 'Bureau', 'Escritorio']:
            desktop_path = Path.home() / desktop_name
            if desktop_path.is_dir():
                return desktop_path
        
        # Create Desktop directory if none exists
        desktop_path = Path.home() / 'Desktop'
        try:
            desktop_path.mkdir(exist_ok=True)
            return desktop_path
        except Exception as e:
            self.install_log_text.append(f"[ERROR] Cannot create Desktop directory: {e}")
            return None
    
    def _create_safe_filename(self, name: str) -> str:
        """Creates a safe filename from application name."""
        # Replace problematic characters
        safe_chars = []
        for char in name:
            if char.isalnum() or char in (' ', '-', '_', '.'):
                safe_chars.append(char)
            else:
                safe_chars.append('_')
        
        safe_name = ''.join(safe_chars).strip()
        # Remove multiple spaces/underscores and limit length
        safe_name = ' '.join(safe_name.split())
        safe_name = safe_name.replace(' ', '_')
        return safe_name[:50]  # Limit filename length
    
    def _build_desktop_file_content(self, desktop_info: dict) -> str:
        """Builds enhanced .desktop file content with KDE-specific features."""
        content = "[Desktop Entry]\n"
        
        # Essential fields
        content += f"Version={desktop_info.get('Version', '1.0')}\n"
        content += f"Type={desktop_info.get('Type', 'Application')}\n"
        content += f"Name={desktop_info['Name']}\n"
        
        # Add GenericName if available
        if desktop_info.get('GenericName'):
            content += f"GenericName={desktop_info['GenericName']}\n"
        
        # Add Comment/Description
        if desktop_info.get('Comment'):
            content += f"Comment={desktop_info['Comment']}\n"
        
        # Execution info
        content += f"Exec={desktop_info['Exec']}\n"
        
        # Working directory
        if desktop_info.get('Path'):
            content += f"Path={desktop_info['Path']}\n"
        
        # Terminal setting
        content += f"Terminal={desktop_info.get('Terminal', 'false')}\n"
        
        # Icon
        if desktop_info.get('Icon'):
            content += f"Icon={desktop_info['Icon']}\n"
        
        # Categories for proper menu placement
        if desktop_info.get('Categories'):
            content += f"Categories={desktop_info['Categories']}\n"
        else:
            content += "Categories=Application;\n"
        
        # Keywords for search
        if desktop_info.get('Keywords'):
            content += f"Keywords={desktop_info['Keywords']}\n"
        
        # MIME types if supported
        if desktop_info.get('MimeType'):
            content += f"MimeType={desktop_info['MimeType']}\n"
        
        # Startup notification
        content += f"StartupNotify={desktop_info.get('StartupNotify', 'true')}\n"
        
        # Window class for better window management
        if desktop_info.get('StartupWMClass'):
            content += f"StartupWMClass={desktop_info['StartupWMClass']}\n"
        
        # KDE-specific features
        content += self._add_kde_specific_features(desktop_info)
        
        # Add metadata
        content += f"X-Created-By=Nano Installer\n"
        content += f"X-Creation-Time={int(time.time())}\n"
        
        return content
    
    def _add_kde_specific_features(self, desktop_info: dict) -> str:
        """Adds KDE Plasma specific desktop shortcut features."""
        kde_content = ""
        
        # KDE Activities support
        kde_content += "X-KDE-Activities=*\n"
        
        # KDE shortcuts and actions
        kde_content += self._add_kde_shortcuts(desktop_info)
        
        # KDE appearance and behavior
        kde_content += "X-KDE-StartupNotify=true\n"
        kde_content += "X-KDE-HasTempFileOption=false\n"
        
        # Plasma-specific features
        kde_content += "X-Plasma-Trusted=true\n"
        kde_content += "X-Plasma-DropMimeTypes=text/plain;text/uri-list;\n"
        
        # KDE protocol handling
        if desktop_info.get('MimeType'):
            kde_content += "X-KDE-Protocols=file;http;https;ftp;\n"
        
        # Window management hints
        kde_content += "X-KDE-SubstituteUID=false\n"
        kde_content += "X-KDE-Username=\n"
        
        # Desktop containment features
        kde_content += "X-Plasma-API=javascript\n"
        kde_content += "X-KDE-PluginInfo-EnabledByDefault=true\n"
        
        return kde_content
    
    def _add_kde_shortcuts(self, desktop_info: dict) -> str:
        """Adds KDE keyboard shortcuts and context actions."""
        shortcuts_content = ""
        
        # Add context menu actions for KDE
        app_name = desktop_info.get('Name', 'Application')
        
        # KDE Actions for right-click context menu
        shortcuts_content += "Actions=Settings;About;Uninstall;\n"
        shortcuts_content += "\n"
        
        # Settings action
        shortcuts_content += "[Desktop Action Settings]\n"
        shortcuts_content += f"Name=Configure {app_name}\n"
        shortcuts_content += f"Name[en_US]=Configure {app_name}\n"
        shortcuts_content += "Icon=configure\n"
        
        # Try to find settings/preferences command
        exec_cmd = desktop_info.get('Exec', '')
        if exec_cmd:
            base_cmd = exec_cmd.split()[0] if exec_cmd.split() else ''
            # Common settings patterns
            settings_patterns = [
                f"{base_cmd} --preferences",
                f"{base_cmd} --settings",
                f"{base_cmd} --config",
                f"{base_cmd} -p",
                "systemsettings5"
            ]
            shortcuts_content += f"Exec={settings_patterns[0]}\n"
        else:
            shortcuts_content += "Exec=systemsettings5\n"
        shortcuts_content += "\n"
        
        # About action
        shortcuts_content += "[Desktop Action About]\n"
        shortcuts_content += f"Name=About {app_name}\n"
        shortcuts_content += f"Name[en_US]=About {app_name}\n"
        shortcuts_content += "Icon=help-about\n"
        if exec_cmd:
            base_cmd = exec_cmd.split()[0] if exec_cmd.split() else ''
            shortcuts_content += f"Exec={base_cmd} --help\n"
        else:
            shortcuts_content += "Exec=khelpcenter\n"
        shortcuts_content += "\n"
        
        # Uninstall action
        shortcuts_content += "[Desktop Action Uninstall]\n"
        shortcuts_content += f"Name=Uninstall {app_name}\n"
        shortcuts_content += f"Name[en_US]=Uninstall {app_name}\n"
        shortcuts_content += "Icon=edit-delete\n"
        # installer_path needs to be relative to the main script, which is nano-installer.py
        # We use Path(__file__).parent.parent to get back to the root directory
        installer_path = str(Path(__file__).parent.parent / "nano-installer.py")
        shortcuts_content += f"Exec=python3 '{installer_path}' --uninstall '{self.pkg_name}'\n"
        shortcuts_content += "\n"
        
        return shortcuts_content
    
    def _mark_shortcut_trusted(self, shortcut_path: Path):
        """Marks the shortcut as trusted for KDE Plasma with comprehensive integration."""
        try:
            # Method 1: Set Plasma trusted attribute directly in file
            self._set_plasma_trusted_in_file(shortcut_path)
            
            # Method 2: Use kwriteconfig5 for KDE configuration
            self._configure_kde_shortcut_settings(shortcut_path)
            
            # Method 3: Add to KDE's trusted desktop files list
            self._add_to_kde_trusted_list(shortcut_path)
            
            # Method 4: Set proper KDE file attributes
            self._set_kde_file_attributes(shortcut_path)
            
        except Exception as e:
            self.install_log_text.append(f"[INFO] KDE integration partially completed: {e}")
    
    def _set_plasma_trusted_in_file(self, shortcut_path: Path):
        """Sets Plasma trusted flag directly in the .desktop file."""
        try:
            # Read current content
            with open(shortcut_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Add trusted flag if not already present
            if 'X-Plasma-Trusted=true' not in content:
                content = content.rstrip() + '\nX-Plasma-Trusted=true\n'
            
            # Write back
            with open(shortcut_path, 'w', encoding='utf-8') as f:
                f.write(content)
                
        except Exception:
            pass
    
    def _configure_kde_shortcut_settings(self, shortcut_path: Path):
        """Configures KDE-specific shortcut settings."""
        try:
            # Use kwriteconfig5 to set various KDE properties
            kde_configs = [
                ['kwriteconfig5', '--file', str(shortcut_path), '--group', 'Desktop Entry', '--key', 'X-Plasma-Trusted', 'true'],
                ['kwriteconfig5', '--file', str(shortcut_path), '--group', 'Desktop Entry', '--key', 'X-KDE-StartupNotify', 'true'],
                ['kwriteconfig5', '--file', str(shortcut_path), '--group', 'Desktop Entry', '--key', 'X-KDE-Activities', '*'],
            ]
            
            for config_cmd in kde_configs:
                subprocess.run(config_cmd, capture_output=True, timeout=5)
                
        except Exception:
            pass
    
    def _add_to_kde_trusted_list(self, shortcut_path: Path):
        """Adds shortcut to KDE's global trusted desktop files list."""
        try:
            # KDE stores trusted desktop files in kdesktoprc
            config_dir = Path.home() / '.config'
            kdesktop_rc = config_dir / 'kdesktoprc'
            
            if not kdesktop_rc.exists():
                return
            
            # Use kwriteconfig5 to add to trusted list
            subprocess.run([
                'kwriteconfig5', '--file', str(kdesktop_rc),
                '--group', 'Desktop', '--key', 'TrustedDesktopFiles', 
                str(shortcut_path)
            ], capture_output=True, timeout=5)
            
        except Exception:
            pass
    
    def _set_kde_file_attributes(self, shortcut_path: Path):
        """Sets KDE-specific file attributes for better integration."""
        try:
            # Mark as KDE trusted using extended attributes
            subprocess.run([
                'setfattr', '-n', 'user.kde.trusted', '-v', 'true', str(shortcut_path)
            ], capture_output=True)
            
            # Set KDE desktop file type
            subprocess.run([
                'setfattr', '-n', 'user.mime_type', '-v', 'application/x-desktop', str(shortcut_path)
            ], capture_output=True)
            
        except Exception:
            pass  # Extended attributes might not be supported
    
    def _refresh_desktop(self):
        """Refreshes the desktop using KDE-specific methods and fallbacks."""
        try:
            self.install_log_text.append("[INFO] Refreshing desktop to show new shortcuts...")
            
            # KDE-specific desktop refresh methods
            kde_commands = [
                # Rebuild KDE's system configuration cache
                ['kbuildsycoca5', '--noincremental'],
                # Refresh desktop containment
                ['qdbus', 'org.kde.plasmashell', '/PlasmaShell', 'org.kde.PlasmaShell.refreshCurrentShell'],
                # Update desktop database
                ['kbuildsycoca5'],
                # Force desktop to reload
                ['qdbus', 'org.kde.kdesktop', '/Desktop', 'org.kde.kdesktop.Desktop.refresh'],
            ]
            
            # Generic fallback commands
            fallback_commands = [
                ['update-desktop-database', str(Path.home() / 'Desktop')],
                ['xdg-desktop-menu', 'forceupdate'],
                ['gtk-update-icon-cache', '-f', str(Path.home() / '.local/share/icons/')],
            ]
            
            # Try KDE-specific methods first
            kde_success = False
            for cmd in kde_commands:
                try:
                    result = subprocess.run(cmd, capture_output=True, timeout=10)
                    if result.returncode == 0:
                        kde_success = True
                        self.install_log_text.append(f"[SUCCESS] KDE refresh: {' '.join(cmd)}")
                        break
                except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                    continue
            
            # If KDE methods failed, try generic methods
            if not kde_success:
                for cmd in fallback_commands:
                    try:
                        result = subprocess.run(cmd, capture_output=True, timeout=10)
                        if result.returncode == 0:
                            self.install_log_text.append(f"[SUCCESS] Generic refresh: {' '.join(cmd)}")
                            break
                    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                        continue
            
            # Additional KDE-specific notifications
            self._notify_kde_desktop_changes()
            
        except Exception as e:
            self.install_log_text.append(f"[WARNING] Desktop refresh partially failed: {e}")
    
    def _notify_kde_desktop_changes(self):
        """Notifies KDE about desktop changes using various methods."""
        try:
            # Method 1: Use D-Bus to notify Plasma
            dbus_notifications = [
                # Notify desktop about new files
                ['qdbus', 'org.freedesktop.FileManager1', '/org/freedesktop/FileManager1', 
                 'org.freedesktop.FileManager1.ShowFolders', str(Path.home() / 'Desktop')],
                # Notify icon cache about changes
                ['qdbus', 'org.kde.KIconLoader', '/KIconLoader', 'org.kde.KIconLoader.newIconLoader'],
                # Refresh Plasma desktop containment
                ['qdbus', 'org.kde.plasmashell', '/PlasmaShell', 
                 'org.kde.PlasmaShell.evaluateScript', 
                 'desktops().forEach(d => d.currentConfigGroup = ["General"]; d.reloadConfig())'],
            ]
            
            for cmd in dbus_notifications:
                try:
                    subprocess.run(cmd, capture_output=True, timeout=5)
                except Exception:
                    continue
            
            # Method 2: Create desktop notification
            self._create_kde_notification()
            
        except Exception:
            pass  # Not critical
    
    def _create_kde_notification(self):
        """Creates a KDE notification about the new shortcut."""
        try:
            if hasattr(self, 'pkg_name') and self.pkg_name:
                notification_cmd = [
                    'kdialog', '--title', 'Nano Installer',
                    '--passivepopup', f'Desktop shortcut created for {self.pkg_name}',
                    '3'
                ]
                subprocess.run(notification_cmd, capture_output=True, timeout=5)
        except Exception:
            pass
    
    def _create_generic_shortcut(self):
        """Creates a generic shortcut when no .desktop file is found."""
        try:
            desktop_dir = self._get_desktop_directory()
            if not desktop_dir:
                return
            
            # Create a basic shortcut for the package
            safe_filename = self._create_safe_filename(self.pkg_name)
            shortcut_path = desktop_dir / f"{safe_filename}.desktop"
            
            # Get package description if available
            try:
                desc_result = subprocess.run(['apt-cache', 'show', self.pkg_name],
                                           capture_output=True, text=True)
                description = "Installed application"
                for line in desc_result.stdout.split('\n'):
                    if line.startswith('Description:'):
                        description = line.split(':', 1)[1].strip()
                        break
            except Exception:
                description = "Installed application"
            
            # Create generic .desktop content
            content = f"""[Desktop Entry]
Version=1.0
Type=Application
Name={self.pkg_name.title()}
Comment={description}
Icon=application-x-executable
Exec={self.pkg_name}
Terminal=false
Categories=Application;
StartupNotify=true
X-Created-By=Nano Installer
X-Creation-Time={int(time.time())}
"""
            
            shortcut_path.write_text(content, encoding='utf-8')
            shortcut_path.chmod(0o755)
            
            self.install_log_text.append(f"[SUCCESS] Created generic shortcut: {shortcut_path}")
            
        except Exception as e:
            self.install_log_text.append(f"[ERROR] Failed to create generic shortcut: {e}")

# -----------------------
# Uninstall wizard
# -----------------------
class UninstallWizard(BaseOperationWizard):
    def __init__(self, pkg_name, parent=None):
        super().__init__(pkg_name, parent)
        self.found_leftover_files = []
        self.shortcut_path_to_remove = None
        self.setWindowTitle(f"Uninstall {pkg_name}")

        # --- Page 1: Confirmation ---
        # Page 1: Confirmation
        p1 = QWizardPage()
        p1.setTitle("Ready to Uninstall")
        p1.setSubTitle("This will permanently remove the package from your system.")
        l1 = QVBoxLayout(p1)

        package_pixmap = get_icon_for_installed_package(self.pkg_name)
        if not package_pixmap or package_pixmap.isNull():
            package_pixmap = QIcon.fromTheme("application-x-executable").pixmap(64, 64)

        icon_label = QLabel()
        icon_label.setPixmap(package_pixmap)
        icon_label.setAlignment(Qt.AlignCenter)

        label = QLabel(f"You are about to completely remove:\n\n<b>{pkg_name}</b>\n\nThis action cannot be undone.")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignCenter)

        l1.addStretch(1)
        l1.addWidget(icon_label)
        l1.addSpacing(10)
        l1.addWidget(label)
        l1.addStretch(2)
        self.addPage(p1)

        # --- Page 2: Uninstalling ---
        p2 = self._create_progress_page("Uninstalling", "Please wait while the package is being removed.")
        self.uninstall_log_text = self.log_text # Alias for clarity
        self.addPage(p2)

        # --- Page for Leftover File Cleanup (new) ---
        self.p_cleanup = QWizardPage()
        self.p_cleanup.setTitle("Clean Up Leftover Files")
        self.p_cleanup.setSubTitle("The following user configuration files were found. Select which ones to remove.")
        cleanup_layout = QVBoxLayout(self.p_cleanup)
        
        cleanup_layout.addWidget(QLabel("These files are typically safe to remove, but review them before proceeding."))
        
        self.leftover_files_list = QListWidget()
        self.leftover_files_list.setSelectionMode(QListWidget.NoSelection)
        cleanup_layout.addWidget(self.leftover_files_list)
        
        select_buttons_layout = QHBoxLayout()
        self.btn_select_all = QPushButton("Select All")
        self.btn_deselect_all = QPushButton("Deselect All")
        select_buttons_layout.addWidget(self.btn_select_all)
        select_buttons_layout.addWidget(self.btn_deselect_all)
        select_buttons_layout.addStretch()
        cleanup_layout.addLayout(select_buttons_layout)
        
        self.btn_select_all.clicked.connect(lambda: self._set_all_cleanup_items(True))
        self.btn_deselect_all.clicked.connect(lambda: self._set_all_cleanup_items(False))
        self.addPage(self.p_cleanup)

        # Page 3: Success
        p3 = QWizardPage()
        p3.setFinalPage(True)
        p3.setTitle("Uninstallation Complete")
        p3.setSubTitle("The package has been removed from your system.")
        l3 = QVBoxLayout(p3)
        self.success_icon = QLabel()
        self.success_icon.setPixmap(package_pixmap)
        self.success_icon.setAlignment(Qt.AlignCenter)
        success_label = QLabel(f"<b>{self.pkg_name}</b> was uninstalled successfully.")
        success_label.setAlignment(Qt.AlignCenter)
        l3.addStretch()
        l3.addWidget(self.success_icon)
        l3.addSpacing(10)
        l3.addWidget(success_label)
        l3.addStretch()
        self.addPage(p3)

        self.currentIdChanged.connect(self.on_page_changed)

    def nextId(self):
        current = self.currentId()
        
        # After progress page (ID 1)
        if current == 1:
            if self.found_leftover_files:
                return 2 # Go to cleanup page (p_cleanup)
            else:
                return 3 # Skip cleanup, go directly to success page (p3)
        
        # From cleanup page (ID 2), go to final success page.
        if current == 2:
            return 3 # Go to success page
            
        return super().nextId()

    def _get_operation_verb(self):
        return "remove software"

    @pyqtSlot(int)
    def on_page_changed(self, idx):
        if idx == 1:
            self.do_uninstall()
        # When moving to the final page, perform the cleanup.
        elif idx == 3 and self._previous_id == 2:
            self._perform_cleanup()

        # Hide the back button on the final page
        page = self.currentPage()
        if page and page.isFinalPage():
            self.button(QWizard.BackButton).hide()

    def _prepare_for_shortcut_removal(self):
        """
        Finds all potential desktop shortcuts associated with the package before it's uninstalled.
        Stores the list in self.shortcuts_to_remove.
        """
        self.shortcuts_to_remove = []
        self.uninstall_log_text.append("--- Checking for desktop shortcuts to remove ---")
        
        try:
            # Get desktop directory
            desktop_dir = self._get_desktop_directory_for_removal()
            if not desktop_dir:
                self.uninstall_log_text.append("[INFO] No Desktop directory found. Skipping shortcut removal.")
                return
            
            # Method 1: Find shortcuts based on installed .desktop files
            self._find_shortcuts_from_desktop_files(desktop_dir)
            
            # Method 2: Find shortcuts created by our installer (with metadata)
            self._find_shortcuts_by_metadata(desktop_dir)
            
            # Method 3: Find shortcuts by package name (fallback)
            self._find_shortcuts_by_package_name(desktop_dir)
            
            if self.shortcuts_to_remove:
                self.uninstall_log_text.append(f"[INFO] Found {len(self.shortcuts_to_remove)} shortcut(s) to remove")
                for shortcut in self.shortcuts_to_remove:
                    self.uninstall_log_text.append(f"[INFO] Will remove: {shortcut}")
            else:
                self.uninstall_log_text.append("[INFO] No desktop shortcuts found for this package.")
                
        except Exception as e:
            self.uninstall_log_text.append(f"[WARNING] Error checking for shortcuts: {e}")
    
    def _get_desktop_directory_for_removal(self) -> Path:
        """Gets the desktop directory for shortcut removal."""
        # Try XDG desktop directory first
        try:
            result = subprocess.run(['xdg-user-dir', 'DESKTOP'], 
                                  capture_output=True, text=True, check=True)
            desktop_path = Path(result.stdout.strip())
            if desktop_path.is_dir():
                return desktop_path
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
        
        # Fallback to standard locations
        for desktop_name in ['Desktop', 'Рабочий стол', 'デスクトップ', 'Bureau', 'Escritorio']:
            desktop_path = Path.home() / desktop_name
            if desktop_path.is_dir():
                return desktop_path
        
        return None
    
    def _find_shortcuts_from_desktop_files(self, desktop_dir: Path):
        """Find shortcuts based on installed .desktop files."""
        try:
            # Find .desktop files installed by the package
            dpkg_cmd = ["dpkg", "-L", self.pkg_name]
            dpkg_proc = subprocess.Popen(dpkg_cmd, stdout=subprocess.PIPE, text=True, encoding='utf-8')
            grep_cmd = ["grep", r'/usr/share/applications/.*\.desktop$']
            grep_proc = subprocess.Popen(grep_cmd, stdin=dpkg_proc.stdout, stdout=subprocess.PIPE, text=True, encoding='utf-8')
            dpkg_proc.stdout.close()
            desktop_files_output, _ = grep_proc.communicate()
            
            if not desktop_files_output:
                return
            
            desktop_files = [f.strip() for f in desktop_files_output.strip().split('\n') if f.strip()]
            
            for desktop_file_path in desktop_files:
                original_desktop_path = Path(desktop_file_path)
                if not original_desktop_path.is_file():
                    continue
                
                # Parse the .desktop file
                desktop_info = self._parse_desktop_file_for_removal(original_desktop_path)
                app_name = desktop_info.get("Name")
                if not app_name:
                    continue
                
                # Find potential shortcuts based on the app name
                safe_filename = self._create_safe_filename_for_removal(app_name)
                
                # Check various possible filenames
                potential_names = [
                    f"{safe_filename}.desktop",
                    f"{safe_filename}_1.desktop",
                    f"{safe_filename}_2.desktop",
                    f"{app_name.replace(' ', '_')}.desktop",
                    f"{app_name}.desktop"
                ]
                
                for name in potential_names:
                    shortcut_path = desktop_dir / name
                    if shortcut_path.is_file() and shortcut_path not in self.shortcuts_to_remove:
                        # Verify this shortcut is related to our package
                        if self._verify_shortcut_belongs_to_package(shortcut_path, desktop_info):
                            self.shortcuts_to_remove.append(shortcut_path)
                            
        except Exception:
            pass  # Silent fail, other methods will try
    
    def _find_shortcuts_by_metadata(self, desktop_dir: Path):
        """Find shortcuts created by our installer using metadata."""
        try:
            # Look for .desktop files with our metadata
            for shortcut_file in desktop_dir.glob("*.desktop"):
                if shortcut_file in self.shortcuts_to_remove:
                    continue # Already found by another method

                try:
                    with open(shortcut_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        # Check for our installer's signature and that the uninstall action points to the correct package
                        is_our_shortcut = "X-Created-By=Nano Installer" in content
                        uninstall_action_correct = f"Exec=python3 .* --uninstall '{self.pkg_name}'" in content

                        # A more lenient check if the strict one fails
                        name_matches = f"Name=Uninstall {self.pkg_name}" in content

                        if is_our_shortcut and (uninstall_action_correct or name_matches):
                            if shortcut_file not in self.shortcuts_to_remove:
                                self.shortcuts_to_remove.append(shortcut_file)
                except Exception:
                    continue
                    
        except Exception:
            pass
    
    def _find_shortcuts_by_package_name(self, desktop_dir: Path):
        """Find shortcuts by package name as fallback."""
        try:
            # Look for shortcuts that might be named after the package
            safe_pkg_name = self._create_safe_filename_for_removal(self.pkg_name)
            potential_names = [
                f"{safe_pkg_name}.desktop",
                f"{safe_pkg_name.title()}.desktop",
                f"{self.pkg_name}.desktop",
                f"{self.pkg_name.title()}.desktop"
            ]
            
            for name in potential_names:
                shortcut_path = desktop_dir / name
                if shortcut_path.is_file() and shortcut_path not in self.shortcuts_to_remove:
                    self.shortcuts_to_remove.append(shortcut_path)
                    
        except Exception:
            pass
    
    def _parse_desktop_file_for_removal(self, file_path: Path) -> dict:
        """Parse .desktop file for removal purposes."""
        config = {}
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                in_desktop_entry = False
                for line in f:
                    line = line.strip()
                    if line == '[Desktop Entry]':
                        in_desktop_entry = True
                        continue
                    if not in_desktop_entry or not line or line.startswith('#'):
                        continue
                    if line.startswith('[') and line.endswith(']'):
                        break
                    if '=' not in line:
                        continue
                        
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    if key in ["Name", "Exec", "Icon"]:
                        config[key] = value
        except IOError:
            pass
        return config
    
    def _create_safe_filename_for_removal(self, name: str) -> str:
        """Create safe filename for removal matching creation logic."""
        safe_chars = []
        for char in name:
            if char.isalnum() or char in (' ', '-', '_', '.'):
                safe_chars.append(char)
            else:
                safe_chars.append('_')
        
        safe_name = ''.join(safe_chars).strip()
        safe_name = ' '.join(safe_name.split())
        safe_name = safe_name.replace(' ', '_')
        return safe_name[:50]
    
    def _verify_shortcut_belongs_to_package(self, shortcut_path: Path, expected_info: dict) -> bool:
        """Verify if a shortcut belongs to the package being removed."""
        try:
            shortcut_info = self._parse_desktop_file_for_removal(shortcut_path)
            
            # Check if Name matches
            if expected_info.get("Name") == shortcut_info.get("Name"):
                return True
            
            # Check if Exec contains similar command
            expected_exec = expected_info.get("Exec", "")
            shortcut_exec = shortcut_info.get("Exec", "")
            if expected_exec and shortcut_exec:
                # Extract command name from Exec line
                expected_cmd = expected_exec.split()[0] if expected_exec.split() else ""
                shortcut_cmd = shortcut_exec.split()[0] if shortcut_exec.split() else ""
                if expected_cmd and expected_cmd == shortcut_cmd:
                    return True
            
            return False
            
        except Exception:
            return False

    def _remove_desktop_shortcuts(self):
        """Removes all desktop shortcuts associated with the package."""
        if not hasattr(self, 'shortcuts_to_remove') or not self.shortcuts_to_remove:
            self.uninstall_log_text.append("[INFO] No desktop shortcuts to remove.")
            return
        
        self.uninstall_log_text.append("\n--- Removing desktop shortcuts ---")
        removed_count = 0
        failed_count = 0
        
        for shortcut_path in self.shortcuts_to_remove:
            try:
                if shortcut_path.is_file():
                    shortcut_path.unlink()
                    self.uninstall_log_text.append(f"[SUCCESS] Removed: {shortcut_path.name}")
                    removed_count += 1
                else:
                    self.uninstall_log_text.append(f"[INFO] Not found: {shortcut_path.name}")
            except Exception as e:
                self.uninstall_log_text.append(f"[ERROR] Failed to remove {shortcut_path.name}: {e}")
                failed_count += 1
        
        # Summary
        if removed_count > 0:
            self.uninstall_log_text.append(f"[SUCCESS] Removed {removed_count} desktop shortcut(s)")
        if failed_count > 0:
            self.uninstall_log_text.append(f"[WARNING] Failed to remove {failed_count} shortcut(s)")
            
        # Refresh desktop after removal
        self._refresh_desktop_after_removal()
    
    def _refresh_desktop_after_removal(self):
        """Refreshes desktop after shortcut removal."""
        try:
            # Try different desktop refresh methods
            desktop_commands = [
                ['kbuildsycoca5'],  # KDE
                ['update-desktop-database', str(Path.home() / 'Desktop')],  # Generic
                ['xdg-desktop-menu', 'forceupdate'],  # XDG
            ]
            
            for cmd in desktop_commands:
                try:
                    subprocess.run(cmd, capture_output=True, timeout=5)
                    break  # If one succeeds, we're done
                except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                    continue
                    
        except Exception:
            pass  # Not critical if desktop refresh fails

    def _set_all_cleanup_items(self, checked: bool):
        """Checks or unchecks all items in the leftover files list."""
        for i in range(self.leftover_files_list.count()):
            item = self.leftover_files_list.item(i)
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def _perform_cleanup(self):
        """Deletes the user-selected leftover configuration files."""
        import shutil
        self.uninstall_log_text.append("\n--- Removing leftover configuration files ---")
        for i in range(self.leftover_files_list.count()):
            item = self.leftover_files_list.item(i)
            if item.checkState() == Qt.Checked:
                path_to_remove = Path(item.data(Qt.UserRole))
                try:
                    if path_to_remove.is_dir():
                        shutil.rmtree(path_to_remove)
                    elif path_to_remove.is_file():
                        path_to_remove.unlink()
                    self.uninstall_log_text.append(f"[SUCCESS] Removed: {path_to_remove}")
                except Exception as e:
                    self.uninstall_log_text.append(f"[ERROR] Failed to remove {path_to_remove}: {e}")

    def do_uninstall(self): # This is called when the page changes to the progress page
        self._prepare_for_shortcut_removal()
        self._execute_operation()

    def _get_worker_callbacks(self):
        """Returns the worker function and its callbacks for the base class."""
        def uninstall(worker=None, password=None):
            leftover_files = []
            try:
                # Perform uninstallation using the C backend's apt-op command
                if worker: worker.progress.emit({"type": "log", "line": "\n--- Starting package removal via C backend ---\n"})
                
                # Use apt remove with purge option for complete removal via C backend
                cmd = ["sudo", "-S", get_backend_path(), "apt-op", "purge", self.pkg_name]
                output_lines = []
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, encoding='utf-8')
                proc.stdin.write(password + '\n')
                proc.stdin.close()

                if worker: worker.progress.emit({"type": "progress", "value": 25})

                while True:
                    if worker and not worker.is_running(): proc.terminate(); break
                    line = proc.stdout.readline()
                    if not line: break
                    output_lines.append(line)
                    if worker: worker.progress.emit({"type": "log", "line": line})
                    
                proc.wait()
                
                # Clean up orphaned dependencies via C backend
                if worker: worker.progress.emit({"type": "log", "line": "\n--- Cleaning up orphaned dependencies ---\n"})
                cleanup_cmd = ["sudo", "-S", get_backend_path(), "apt", "autoremove", "-y"]
                cleanup_proc = subprocess.Popen(cleanup_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                cleanup_proc.stdin.write(password + '\n')
                cleanup_proc.stdin.close()
                
                while True:
                    if worker and not worker.is_running(): cleanup_proc.terminate(); break
                    line = cleanup_proc.stdout.readline()
                    if not line: break
                    output_lines.append(line)
                    if worker: worker.progress.emit({"type": "log", "line": line})
                    
                cleanup_proc.wait()
                
                # --- Scan for leftover files after successful purge ---
                if proc.returncode == 0:
                    if worker: worker.progress.emit({"type": "log", "line": "\n--- Scanning for leftover user configuration files ---\n"})
                    
                    home_dir = Path.home()
                    # Common locations for user-specific config/data
                    search_dirs = [
                        home_dir / ".config",
                        home_dir / ".local" / "share",
                        home_dir / ".cache"
                    ]
                    
                    # Create a few variations of the package name to search for
                    pkg_name_variations = {self.pkg_name, self.pkg_name.lower(), self.pkg_name.replace('-', '')}
                    
                    for search_dir in search_dirs:
                        if search_dir.is_dir():
                            for variation in pkg_name_variations:
                                potential_path = search_dir / variation
                                if potential_path.exists() and potential_path not in leftover_files:
                                    leftover_files.append(potential_path)
                                    if worker: worker.progress.emit({"type": "log", "line": f"[INFO] Found potential leftover: {potential_path}\n"})
                
                return proc.returncode, "".join(output_lines), leftover_files
                
            except Exception as e:
                if worker: worker.progress.emit({"type": "log", "line": f"Uninstall error: {str(e)}\n"})
                # Return a tuple with 3 items to match the success case structure
                return -1, str(e), []

        def on_progress(data):
            line = data.get("line", "")
            if line:
                self.uninstall_log_text.append(line.strip())
                self.uninstall_log_text.verticalScrollBar().setValue(self.uninstall_log_text.verticalScrollBar().maximum())

            match = re.search(r'(\d+)\s*%', line)
            if match:
                # Cap at 99% to ensure only the 'done' callback sets it to 100%
                self.progress.setValue(min(99, int(match.group(1))))
            elif data.get("type") == "progress":
                self.progress.setValue(data["value"])

        def done(result):
            if isinstance(result, Exception):
                QMessageBox.warning(self, APP_NAME, f"Uninstallation failed with an unexpected error: {result}")
                self.button(QWizard.BackButton).setEnabled(True)
                return

            rc, output, leftover_files = result
            # --- New Enhanced Error Handling ---
            # Check for specific errors from our C backend first.
            backend_error_prefix = "[NANO_BACKEND_ERROR]"
            backend_error_line = next((line for line in output.splitlines() if line.startswith(backend_error_prefix)), None)

            if backend_error_line:
                # We have a specific error from our C code.
                error_message = backend_error_line.replace(backend_error_prefix, "").strip()
                QMessageBox.critical(self, "Backend Error", f"A critical error occurred in the backend process:\n\n{error_message}\n\n(Code: {rc})")
                self.progress.setStyleSheet("QProgressBar::chunk { background-color: red; }")
                self.button(QWizard.BackButton).setEnabled(True)
                return
            # --- End of New Error Handling ---

            # Phrases that indicate a password error from different sudo versions/configs
            password_error_phrases = [
                "sorry, try again",
                "authentication failed",
                "incorrect password",
                "incorrect authentication",
            ]
            is_password_error = rc != 0 and any(phrase in output.lower() for phrase in password_error_phrases)

            if rc == 0:
                self.progress.setValue(100)
                self._remove_desktop_shortcuts()
                self.found_leftover_files = leftover_files
                
                if self.found_leftover_files:
                    # Populate the cleanup page
                    for path in self.found_leftover_files:
                        item = QListWidgetItem(f"Found: {path}")
                        item.setData(Qt.UserRole, str(path))
                        item.setCheckState(Qt.Checked) # Default to checked
                        self.leftover_files_list.addItem(item)
                
                self.next() # Go to cleanup page or success page
            elif is_password_error:
                if self._used_saved_password:
                    self.uninstall_log_text.clear()
                    self.uninstall_log_text.append("[ERROR] Saved password was incorrect or has expired. Please enter it manually.")
                    self.settings.save_password("")
                    self.settings.set_setting("auto_password_enabled", "false")

                self._ask_password_and_execute(is_retry=True)
            else:
                self.progress.setStyleSheet("QProgressBar::chunk { background-color: red; }")
                QMessageBox.warning(self, APP_NAME, f"Uninstallation failed with an error (code: {rc}). See log for details.")
                self.button(QWizard.BackButton).setEnabled(True)

        return uninstall, on_progress, done