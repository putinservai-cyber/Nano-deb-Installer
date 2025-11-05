import sys
import os
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
    QListWidgetItem,
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
    check_missing_dependencies, # ADDED
    get_nano_installer_package_name,
)
from nano_installer.security import scan_with_virustotal, calculate_file_hash
from nano_installer.gui_components import AuthenticationDialog, DependencyPopup
from nano_installer.desktop_utils import create_desktop_shortcut, remove_desktop_shortcuts
from nano_installer.constants import APP_NAME, BACKEND_PATH # APP_NAME and BACKEND_PATH are defined in constants.py

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
        
        # Connect the wizard's rejected signal (Cancel/Close) to the worker's stop method
        self.rejected.connect(self.on_wizard_rejected)

    def on_wizard_rejected(self):
        """Called when the user presses Cancel or closes the window."""
        if self._worker_thread:
            self.log_text.append("\n[INFO] Cancellation requested. Attempting to stop background process...")
            self._worker_thread.stop()

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

    def _handle_worker_completion(self, result):
        """
        A centralized handler for worker thread completion.
        This method processes the result, checks for common errors (backend, password),
        and calls a success hook or handles failure UI.
        """
        # 1. Unpack result safely
        if isinstance(result, Exception):
            rc, output = -1, str(result)
            leftover_data = None
        elif len(result) == 3: # For uninstall wizard
            rc, output, leftover_data = result
        else:
            rc, output = result
            leftover_data = None

        # 2. Check for critical backend errors first
        backend_error_prefix = "[NANO_BACKEND_ERROR]"
        backend_error_line = next((line for line in output.splitlines() if line.startswith(backend_error_prefix)), None)
        if backend_error_line:
            error_message = backend_error_line.replace(backend_error_prefix, "").strip()
            QMessageBox.critical(self, "Backend Error", f"A critical error occurred in the backend process:\n\n{error_message}\n\n(Code: {rc})")
            self.progress.setStyleSheet("QProgressBar::chunk { background-color: red; }")
            self.button(QWizard.BackButton).setEnabled(True)
            return

        # 3. Check for password authentication errors
        password_error_phrases = ["sorry, try again", "authentication failed", "incorrect password"]
        is_password_error = rc != 0 and any(phrase in output.lower() for phrase in password_error_phrases)
        if is_password_error:
            if self._used_saved_password:
                self.log_text.clear()
                self.log_text.append("[ERROR] Saved password was incorrect or has expired. Please enter it manually.")
                self.settings.save_password("")
                self.settings.set_setting("auto_password_enabled", "false")
            
            self.progress.setValue(5)
            self.progress.setStyleSheet("") # Reset style
            self._ask_password_and_execute(is_retry=True)
            return

        # 4. Handle success or generic failure
        if rc == 0:
            self.progress.setValue(100)
            self._on_operation_success(output, leftover_data) # Call success hook
        elif rc == -15: # SIGTERM (Cancellation)
            self.progress.setStyleSheet("QProgressBar::chunk { background-color: orange; }")
            self.progress.setValue(0)
            self.log_text.append("\n[INFO] Operation cancelled by user.")
            QMessageBox.information(self, "Cancelled", f"The operation for '{self.pkg_name}' was cancelled by the user.")
            self.button(QWizard.BackButton).setEnabled(True)
        else:
            # Generic failure
            self.progress.setStyleSheet("QProgressBar::chunk { background-color: red; }")
            op_name = self.pkg_name
            QMessageBox.warning(self, "Operation Failed", f"The operation for '{op_name}' failed with an error (code: {rc}). See log for details.")
            self.button(QWizard.BackButton).setEnabled(True)

    def _on_operation_success(self, output: str, data: any):
        """
        Hook for subclasses to implement their specific success logic.
        This is called by _handle_worker_completion on success.
        """
        self.next() # Default behavior is to just go to the next page.

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
        self._deps_checked = False # New flag to prevent re-running dependency check on 'Back'

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

        # Page 2: Dependency Check (New Page)
        self.p_deps = QWizardPage()
        self.p_deps.setTitle("Dependency Check")
        self.p_deps.setSubTitle("Checking for missing dependencies...")
        l_deps = QVBoxLayout(self.p_deps)
        self.deps_status_label = QLabel("Initializing dependency check...")
        self.deps_status_label.setWordWrap(True)
        l_deps.addWidget(self.deps_status_label)
        self.deps_list_widget = QListWidget()
        self.deps_list_widget.setVisible(False)
        l_deps.addWidget(self.deps_list_widget)
        l_deps.addStretch()
        
        # Page 3: Detailed Package Information (Old Page 2)
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
        
        # Page 4: Summary and Ready to Install (Old Page 3)
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

        # Page 5: Extract Location (Old Page 4)
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

        # Page 6: Installing / Extracting (Old Page 5)
        p_install = self._create_progress_page("Installing", "Please wait...")
        self.install_log_text = self.log_text # Alias for clarity

        # Page 7: Success (Old Page 6)
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
        self.setPage(2, self.p_deps) # New Dependency Check Page
        self.setPage(3, p2)          # Old Page 2 (Package Info) is now Page 3
        self.setPage(4, p3)          # Old Page 3 (Summary) is now Page 4
        self.setPage(5, p_extract)   # Old Page 4 (Extract) is now Page 5
        self.setPage(6, p_install)   # Old Page 5 (Install) is now Page 6
        self.setPage(7, p_success)   # Old Page 6 (Success) is now Page 7

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
        if current == 1: # After Security Scan (Page 1)
            return 2 # Go to Dependency Check (Page 2)
        elif current == 2: # After Dependency Check (Page 2)
            return 3 # Go to Package Information (Page 3)
        elif current == 4: # After Ready to Install (Page 4)
            if self.is_extract_mode:
                return 5 # Go to Extract Location (Page 5)
            else:
                return 6 # Go to Install Progress (Page 6)
        elif current == 5: # After Extract Location (Page 5)
            return 6 # Go to Install Progress (Page 6)
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
            self.pkg_name = name # Update the wizard's package name
            version = deb_info.get("Version", "Unknown")
            maintainer = deb_info.get("Maintainer", "Unknown")
            architecture = deb_info.get("Architecture", "Unknown")
            size = deb_info.get("Installed-Size", "Unknown")
            section = deb_info.get("Section", "Unknown")
            description = deb_info.get("Description", "No description available.")
            self.depends_string = deb_info.get("Depends", "") # Store dependency string

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
            if self.depends_string:
                # Parse dependencies (they're comma-separated with version info)
                dependency_groups = parse_dependencies(self.depends_string)
                for group in dependency_groups:
                    # Display the dependency group, showing alternatives if present
                    display_text = " | ".join([f"{dep['name']} {dep['version']}".strip() for dep in group])
                    self.deps_list.addItem(f"• {display_text}")
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
        if idx == 2: # Switched to Dependency Check page
            self.do_dependency_check()
        elif idx == 6:  # Switched to Progress page
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

    def do_dependency_check(self):
        """Starts the worker thread to check for missing dependencies, only if not already checked."""
        if self._deps_checked:
            return

        self.deps_status_label.setText("Checking for missing dependencies...")
        self.deps_list_widget.clear()
        self.deps_list_widget.setVisible(False)
        self.button(QWizard.NextButton).setEnabled(False)
        
        def on_done(missing_deps):
            if isinstance(missing_deps, Exception):
                self.deps_status_label.setText(f"<font color='red'>Error during dependency check: {missing_deps}</font>")
                self.button(QWizard.NextButton).setEnabled(True) # Allow user to proceed anyway
                self._deps_checked = True # Mark as checked even on error to prevent re-run
                return
            
            if missing_deps:
                self.deps_status_label.setText(f"<font color='orange'><b>{len(missing_deps)} missing dependencies found.</b></font>")
                self.deps_list_widget.setVisible(True)
                for dep in missing_deps:
                    self.deps_list_widget.addItem(f"• {dep}")
                
                # Show a warning and ask the user to update cache/install deps
                QMessageBox.warning(self, "Missing Dependencies",
                                    "The package requires missing dependencies. "
                                    "Please ensure your package cache is up-to-date and try again. "
                                    "The installation process will attempt to resolve them, but may fail.")
            else:
                self.deps_status_label.setText("<font color='green'><b>All dependencies appear to be installed.</b></font>")
                
            self.button(QWizard.NextButton).setEnabled(True)
            self._deps_checked = True # Mark as checked on success

        # The worker function is check_missing_dependencies from utils.py
        worker = WorkerThread(check_missing_dependencies, self.depends_string)
        worker.result.connect(on_done)
        worker.start()
        self._deps_worker = worker

    def do_scan(self):
        self.prep_status_label.setText("Preparing security scan...")

        def on_progress(data):
            line = data.get("line", "")
            self.prep_status_label.setText(line)
            if "Calculating hash" in line:
                self.prep_progress.setValue(40)
            elif "Querying" in line:
                self.prep_progress.setValue(80)

        def on_done(res):
            self._scan_finished = True
            if isinstance(res, Exception):
                self._scan_status = "error"
                self.scan_result_text.setText(f"{res}")
            elif isinstance(res, str):
                self.scan_result_text.setText(res)
                if "DANGER!" in res:
                    self._scan_status = "danger"
                elif "SUSPICIOUS" in res:
                    self._scan_status = "suspicious"
                elif "Clean" in res:
                    self._scan_status = "clean"
                else:
                    self._scan_status = "error"
                    self.scan_result_text.append("\n\n[Error] Could not parse the scan result.")
            else:
                self._scan_status = "error"
                self.scan_result_text.setText(f"The scanner returned an unexpected result type: {type(res)}")

            self.handle_scan_finished()

        try:
            self._scan_thread = WorkerThread(scan_with_virustotal, str(self.deb_path))
            self._scan_thread.progress.connect(on_progress)
            self._scan_thread.result.connect(on_done)
            self._scan_thread.start()
        except ValueError as e:
            self._scan_finished = True
            self._scan_status = "error"
            self.scan_result_text.setText(str(e))
            self.handle_scan_finished()

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
        self.page(6).setTitle(f"{verb}ing" + (" and Extracting" if self.is_extract_mode else ""))
        self.page(6).setSubTitle(f"Please wait while the package is being {verb.lower()}ed...")
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
                
                cmd = ["sudo", "-S", BACKEND_PATH, "apt-op", "install", str(self.deb_path).strip()]
                if self.is_reinstall:
                    cmd.append("--reinstall")

                output_lines = []
                # Use preexec_fn=os.setsid to create a new process group for safe termination
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, encoding='utf-8', preexec_fn=os.setsid)
                
                # Pass the process to the worker thread for cancellation handling
                if worker: worker.set_process(proc)
                
                proc.stdin.write(password + '\n')
                proc.stdin.close()

                if worker: worker.progress.emit({"type": "progress", "value": 5})

                while True:
                    # Check for cancellation request
                    if worker and not worker.is_running():
                        # The worker's stop() method handles process termination
                        return -15, "".join(output_lines) # Return SIGTERM code for cancellation
                        
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
            # This regex is for the main installation/unpacking phase
            match = re.search(r'(\d+)\s*%', line)
            if match:
                # Cap at 99% to ensure only the 'done' callback sets it to 100%
                self.progress.setValue(min(99, int(match.group(1))))
            elif data_type == "progress":
                self.progress.setValue(data["value"])
            
            # Check for the final "Setting up" or "Processing triggers" lines to jump to 99%
            if "Setting up" in line or "Processing triggers" in line:
                self.progress.setValue(99)

        return install, on_progress, self._handle_worker_completion

    def _on_operation_success(self, output: str, data: any):
        """Handles successful installation, shortcut creation, and extraction."""
        # Create shortcut if requested, before handling extraction.
        if self.is_create_shortcut_mode and self.cb_create_shortcut_instance.isChecked() and self.pkg_name:
            create_desktop_shortcut(self.pkg_name, self.install_log_text.append)

        if self.is_extract_mode:
            self.install_log_text.append("\n--- Installation successful. Starting extraction phase. ---")
            self.progress.setValue(80) # Visually indicate a new step
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
            self.next()

# -----------------------
# Uninstall wizard
# -----------------------
class UninstallWizard(BaseOperationWizard):
    def __init__(self, pkg_name, parent=None):
        super().__init__(pkg_name, parent)
        self.found_leftover_files = []
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
        self._execute_operation()

    def _get_worker_callbacks(self):
        """Returns the worker function and its callbacks for the base class."""
        def uninstall(worker=None, password=None):
            leftover_files = []
            try:
                # Perform uninstallation using the C backend's apt-op command
                if worker: worker.progress.emit({"type": "log", "line": "\n--- Starting package removal via C backend ---\n"})
                
                # Use apt remove with purge option for complete removal via C backend
                cmd = ["sudo", "-S", BACKEND_PATH, "apt-op", "purge", self.pkg_name]
                output_lines = []
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, encoding='utf-8', preexec_fn=os.setsid)
                
                if worker: worker.set_process(proc)
                
                proc.stdin.write(password + '\n')
                proc.stdin.close()

                if worker: worker.progress.emit({"type": "progress", "value": 25})

                while True:
                    if worker and not worker.is_running():
                        return -15, "".join(output_lines), []
                        
                    line = proc.stdout.readline()
                    if not line: break
                    output_lines.append(line)
                    if worker: worker.progress.emit({"type": "log", "line": line})
                    
                proc.wait()
                
                # Clean up orphaned dependencies via C backend
                if worker: worker.progress.emit({"type": "log", "line": "\n--- Cleaning up orphaned dependencies via C backend ---\n"})
                cleanup_cmd = ["sudo", "-S", BACKEND_PATH, "apt-autoremove"]
                cleanup_proc = subprocess.Popen(cleanup_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, preexec_fn=os.setsid)
                
                if worker: worker.set_process(cleanup_proc)
                
                cleanup_proc.stdin.write(password + '\n')
                cleanup_proc.stdin.close()
                
                while True:
                    if worker and not worker.is_running():
                        return -15, "".join(output_lines), []
                        
                    line = cleanup_proc.stdout.readline()
                    if not line: break
                    output_lines.append(line)
                    if worker: worker.progress.emit({"type": "log", "line": line})
                    
                cleanup_proc.wait()
                
                # --- Scan for leftover files after successful purge ---
                if proc.returncode == 0:
                    if worker: worker.progress.emit({"type": "log", "line": "\n--- Scanning for leftover user configuration and data files ---\n"})
                    
                    home_dir = Path.home()
                    # Common locations for user-specific config/data
                    search_dirs = [
                        home_dir / ".config",
                        home_dir / ".local" / "share",
                        home_dir / ".cache",
                        home_dir, # For dotfiles like .bashrc
                    ]
                    
                    # --- Improved Name Variation Generation ---
                    # Create a comprehensive set of name variations to search for.
                    base_name = self.pkg_name.lower()
                    pkg_name_variations = {
                        base_name,
                        base_name.replace('-', ''),
                        base_name.replace('-', '_'),
                        base_name.title().replace('-', ''),
                        base_name.title()
                    }
                    
                    for search_dir in search_dirs:
                        if search_dir.is_dir():
                            try:
                                for item in search_dir.iterdir():
                                    item_name_lower = item.name.lower()
                                    # For home dir, only check for dotfiles
                                    if search_dir == home_dir and not item.name.startswith('.'):
                                        continue
                                    
                                    # Check if any variation is present in the item's name
                                    for variation in pkg_name_variations:
                                        if variation in item_name_lower:
                                            if item not in leftover_files:
                                                leftover_files.append(item)
                                                if worker: worker.progress.emit({"type": "log", "line": f"[INFO] Found potential leftover: {item}\n"})
                                            break # Move to the next item once a match is found
                            except OSError as e:
                                if worker: worker.progress.emit({"type": "log", "line": f"[WARNING] Could not scan {search_dir}: {e}\n"})
                
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

        return uninstall, on_progress, self._handle_worker_completion

    def _on_operation_success(self, output: str, leftover_files: list):
        """Handles successful uninstallation, shortcut removal, and leftover file scan."""
        remove_desktop_shortcuts(self.pkg_name, self.uninstall_log_text.append)
        self.found_leftover_files = leftover_files
        
        if self.found_leftover_files:
            # Populate the cleanup page
            for path in self.found_leftover_files:
                item = QListWidgetItem(f"Found: {path}")
                item.setData(Qt.UserRole, str(path))
                item.setCheckState(Qt.Checked) # Default to checked
                self.leftover_files_list.addItem(item)
        
        self.next() # Go to cleanup page or success page

# -----------------------
# Update Cache wizard
# -----------------------
class UpdateCacheWizard(BaseOperationWizard):
    def __init__(self, parent=None):
        # We pass a generic name for the BaseOperationWizard
        super().__init__("package cache", parent)
        self.setWindowTitle("Update Package Cache")

        # --- Page 1: Confirmation ---
        p1 = QWizardPage()
        p1.setTitle("Ready to Update Cache")
        p1.setSubTitle("This will refresh the list of available packages from all configured sources.")
        l1 = QVBoxLayout(p1)

        icon_label = QLabel()
        icon_label.setPixmap(QIcon.fromTheme("system-software-update").pixmap(64, 64))
        icon_label.setAlignment(Qt.AlignCenter)

        label = QLabel("You are about to update the package cache (apt update).\n\nThis requires an internet connection.")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignCenter)

        l1.addStretch(1)
        l1.addWidget(icon_label)
        l1.addSpacing(10)
        l1.addWidget(label)
        l1.addStretch(2)
        self.addPage(p1)

        # --- Page 2: Updating ---
        p2 = self._create_progress_page("Updating", "Please wait while the package cache is being updated.")
        self.update_log_text = self.log_text # Alias
        self.addPage(p2)

        # --- Page 3: Success ---
        p3 = QWizardPage()
        p3.setFinalPage(True)
        p3.setTitle("Update Complete")
        p3.setSubTitle("The package cache has been successfully updated.")
        l3 = QVBoxLayout(p3)
        success_icon = QLabel()
        success_icon.setPixmap(QIcon.fromTheme("emblem-ok").pixmap(64, 64))
        success_icon.setAlignment(Qt.AlignCenter)
        success_label = QLabel("The package cache was updated successfully.")
        success_label.setAlignment(Qt.AlignCenter)
        l3.addStretch()
        l3.addWidget(success_icon)
        l3.addSpacing(10)
        l3.addWidget(success_label)
        l3.addStretch()
        self.addPage(p3)

        self.currentIdChanged.connect(self.on_page_changed)

    def _get_operation_verb(self):
        return "update package lists"

    @pyqtSlot(int)
    def on_page_changed(self, idx):
        if idx == 1: # Progress page
            self._execute_operation()

        page = self.currentPage()
        if page and page.isFinalPage():
            self.button(QWizard.BackButton).hide()

    def _get_worker_callbacks(self):
        def update_cache(worker=None, password=None):
            try:
                if worker: worker.progress.emit({"type": "log", "line": "--- Starting package cache update via C backend ---\n"})
                cmd = ["sudo", "-S", BACKEND_PATH, "apt-update"]
                
                output_lines = []
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, encoding='utf-8', preexec_fn=os.setsid)
                
                if worker: worker.set_process(proc)
                
                proc.stdin.write(password + '\n')
                proc.stdin.close()

                while True:
                    if worker and not worker.is_running():
                        return -15, "".join(output_lines)
                        
                    line = proc.stdout.readline()
                    if not line: break
                    output_lines.append(line)
                    if worker: worker.progress.emit({"type": "log", "line": line})

                proc.wait()
                return proc.returncode, "".join(output_lines)
            except Exception as e:
                return -1, str(e)

        def on_progress(data):
            line = data.get("line", "").strip()
            if line:
                self.update_log_text.append(line)
                self.update_log_text.verticalScrollBar().setValue(self.update_log_text.verticalScrollBar().maximum())

                # --- Improved Progress Parsing for `apt update` ---
                # Phase 1: Downloading from repositories (maps to 0-90%)
                # Matches lines like "Get:1", "Hit:2", etc.
                match = re.match(r'^(Get|Hit):\d+', line)
                if match:
                    # Increment progress for each repository line, but don't go past 90
                    self.progress.setValue(min(90, self.progress.value() + 4))

                # Phase 2: Reading package lists (final step, 100%)
                elif "Reading package lists..." in line:
                    self.progress.setValue(100)

        return update_cache, on_progress, self._handle_worker_completion

# -----------------------
# System Upgrade wizard
# -----------------------
class UpgradeSystemWizard(BaseOperationWizard):
    def __init__(self, parent=None):
        super().__init__("system packages", parent)
        self.setWindowTitle("System Upgrade")

        # --- Page 1: Confirmation ---
        p1 = QWizardPage()
        p1.setTitle("Ready to Upgrade System")
        p1.setSubTitle("This will upgrade all installed packages to their newest versions.")
        l1 = QVBoxLayout(p1)

        icon_label = QLabel()
        icon_label.setPixmap(QIcon.fromTheme("system-software-update").pixmap(64, 64))
        icon_label.setAlignment(Qt.AlignCenter)

        label = QLabel("You are about to perform a full system upgrade (apt upgrade).\n\n" 
                       "This may take a long time and requires a stable internet connection.\n" 
                       "Please save all your work before proceeding.")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-weight: bold;")

        l1.addStretch(1)
        l1.addWidget(icon_label)
        l1.addSpacing(10)
        l1.addWidget(label)
        l1.addStretch(2)
        self.addPage(p1)

        # --- Page 2: Upgrading ---
        p2 = self._create_progress_page("Upgrading System", "Please wait while packages are being downloaded and installed.")
        self.upgrade_log_text = self.log_text # Alias
        self.addPage(p2)

        # --- Page 3: Success ---
        p3 = QWizardPage()
        p3.setFinalPage(True)
        p3.setTitle("Upgrade Complete")
        p3.setSubTitle("Your system has been successfully upgraded.")
        l3 = QVBoxLayout(p3)
        success_icon = QLabel()
        success_icon.setPixmap(QIcon.fromTheme("emblem-ok").pixmap(64, 64))
        success_icon.setAlignment(Qt.AlignCenter)
        success_label = QLabel("The system upgrade was completed successfully.")
        success_label.setAlignment(Qt.AlignCenter)
        l3.addStretch()
        l3.addWidget(success_icon)
        l3.addSpacing(10)
        l3.addWidget(success_label)
        l3.addStretch()
        self.addPage(p3)

        self.currentIdChanged.connect(self.on_page_changed)

    def _get_operation_verb(self):
        return "upgrade system packages"

    @pyqtSlot(int)
    def on_page_changed(self, idx):
        if idx == 1: # Progress page
            self._execute_operation()

        page = self.currentPage()
        if page and page.isFinalPage():
            self.button(QWizard.BackButton).hide()

    def _get_worker_callbacks(self):
        def upgrade_system(worker=None, password=None):
            try:
                if worker: worker.progress.emit({"type": "log", "line": "--- Starting system upgrade via C backend ---\n"})
                cmd = ["sudo", "-S", BACKEND_PATH, "apt-upgrade"]
                
                output_lines = []
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, encoding='utf-8', preexec_fn=os.setsid)
                
                if worker: worker.set_process(proc)
                
                proc.stdin.write(password + '\n')
                proc.stdin.close()

                while True:
                    if worker and not worker.is_running():
                        return -15, "".join(output_lines)
                        
                    line = proc.stdout.readline()
                    if not line: break
                    output_lines.append(line)
                    if worker: worker.progress.emit({"type": "log", "line": line})

                proc.wait()
                return proc.returncode, "".join(output_lines)
            except Exception as e:
                return -1, str(e)

        def on_progress(data):
            line = data.get("line", "").strip()
            if line:
                self.upgrade_log_text.append(line)
                self.upgrade_log_text.verticalScrollBar().setValue(self.upgrade_log_text.verticalScrollBar().maximum())

                # --- Progress Parsing for `apt upgrade` ---
                # Phase 1: Downloading packages (maps to 0-50% of progress bar)
                # Matches lines like "Progress: [ 12%]"
                dl_match = re.search(r'Progress:\s*\[\s*(\d+)%\s*\]', line)
                if dl_match:
                    progress_val = int(dl_match.group(1)) * 0.5 # Scale to 0-50
                    self.progress.setValue(int(progress_val))
                    return

                # Phase 2: Unpacking/Installing from database (maps to 50-100% of progress bar)
                install_match = re.search(r'\(Reading database\s*\.\.\.\s*(\d+)%\)', line)
                if install_match:
                    progress_val = 50 + (int(install_match.group(1)) * 0.5) # Scale to 50-100
                    self.progress.setValue(int(progress_val))
        return upgrade_system, on_progress, self._handle_worker_completion
# -----------------------
# Maintenance wizard
# -----------------------
class MaintenanceWizard(BaseOperationWizard):
    """A generic wizard for running simple backend maintenance commands."""
    def __init__(self, operation_name, backend_command, subtitle, parent=None):
        super().__init__(operation_name, parent)
        self.operation_name = operation_name
        self.backend_command = backend_command
        self.setWindowTitle(operation_name)
        self._operation_started = False # New flag to prevent re-running on 'Back'

        # --- Confirmation Page ---
        p1 = QWizardPage()
        p1.setTitle(f"Ready to {operation_name}")
        p1.setSubTitle(subtitle)
        l1 = QVBoxLayout(p1)
        l1.addWidget(QLabel(f"Click Next to start the '{operation_name}' process."))
        self.addPage(p1)

        # --- Progress Page ---
        p2 = self._create_progress_page(f"Running {operation_name}", "Please wait...")
        self.addPage(p2)

        # --- Success Page ---
        p3 = QWizardPage()
        p3.setFinalPage(True)
        p3.setTitle("Operation Complete")
        l3 = QVBoxLayout(p3)
        l3.addWidget(QLabel(f"The '{operation_name}' process finished successfully."))
        self.addPage(p3)

        self.currentIdChanged.connect(self.on_page_changed)

    def on_page_changed(self, idx):
        if idx == 1 and not self._operation_started:
            self._operation_started = True
            self._execute_operation()

    def _get_operation_verb(self):
        return f"run '{self.operation_name}'"

    def _get_worker_callbacks(self):
        # Reuse the robust install worker, but change the command
        def maintenance_worker(worker=None, password=None):
            cmd = ["sudo", "-S", BACKEND_PATH, self.backend_command]
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, encoding='utf-8', preexec_fn=os.setsid)
            
            if worker: worker.set_process(proc)
            
            proc.stdin.write(password + '\n')
            proc.stdin.close()
            output = []
            
            while True:
                if worker and not worker.is_running():
                    return -15, "".join(output)
                    
                line = proc.stdout.readline()
                if not line: break
                output.append(line)
                if worker: worker.progress.emit({"type": "log", "line": line})
                
            proc.wait()
            return proc.returncode, "".join(output)

        def on_progress(data):
            """Generic progress handler for simple log output."""
            line = data.get("line", "")
            if line:
                self.log_text.append(line.strip())
                self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

        return maintenance_worker, on_progress, self._handle_worker_completion