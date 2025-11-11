import sys
import subprocess
from pathlib import Path

# Add the project root to sys.path if run directly for testing
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

from cryptography.fernet import Fernet, InvalidToken
from PyQt6.QtCore import QSettings, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QToolButton,
    QWidget,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QFileDialog,
    QFrame,
    QScrollArea,
    QLineEdit,
    QTabWidget,
)

# Import AuthenticationDialog from gui_components (will be created next)
from nano_installer.gui_components import AuthenticationDialog
from .donation_page import DonationPage # Keep for instantiation
from .report_page import ReportPage # Keep for instantiation

class SettingsManager:
    def __init__(self):
        self.settings = QSettings("NanoInstaller", "NanoInstaller")
        self._key = self._get_or_create_key()
        self.fernet = Fernet(self._key)

    def _get_or_create_key(self):
        key = self.settings.value("encryption_key")
        if not key:
            key = Fernet.generate_key().decode('utf-8')
            self.settings.setValue("encryption_key", key)
        return key.encode('utf-8')

    def get_setting(self, key, default=None):
        return self.settings.value(key, default)

    def set_setting(self, key, value):
        self.settings.setValue(key, value)

    def save_password(self, password: str):
        if not password:
            self.settings.remove("sudo_password")
            return
        encrypted_password = self.fernet.encrypt(password.encode('utf-8'))
        self.settings.setValue("sudo_password", encrypted_password.decode('utf-8'))

    def get_password(self) -> str | None:
        encrypted_password = self.settings.value("sudo_password")
        if not encrypted_password:
            return None
        try:
            decrypted = self.fernet.decrypt(encrypted_password.encode('utf-8'))
            return decrypted.decode('utf-8')
        except (InvalidToken, TypeError):
            # Handle case where token is invalid or key changed
            self.settings.remove("sudo_password")
            return None

    def save_virustotal_api_key(self, api_key: str):
        """Encrypts and saves the VirusTotal API key."""
        if not api_key:
            self.settings.remove("virustotal_api_key")
            return
        encrypted_key = self.fernet.encrypt(api_key.encode('utf-8'))
        self.settings.setValue("virustotal_api_key", encrypted_key.decode('utf-8'))

    def get_virustotal_api_key(self) -> str | None:
        """Retrieves and decrypts the VirusTotal API key."""
        encrypted_key = self.settings.value("virustotal_api_key")
        if not encrypted_key:
            return None
        try:
            return self.fernet.decrypt(encrypted_key.encode('utf-8')).decode('utf-8')
        except (InvalidToken, TypeError):
            self.settings.remove("virustotal_api_key")
            return None

    def get_verbose_logging_enabled(self) -> bool:
        return self.get_setting("verbose_logging_enabled", "false") == "true"

    def set_verbose_logging_enabled(self, enabled: bool):
        self.set_setting("verbose_logging_enabled", "true" if enabled else "false")

    def get_default_download_directory(self) -> str:
        # Default to user's home directory if not set
        return self.get_setting("default_download_directory", str(Path.home()))

    def set_default_download_directory(self, path: str):
        self.set_setting("default_download_directory", path)

# --- Settings Section Widgets ---

class GeneralSettingsWidget(QWidget):
    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- Verbose Logging Section ---
        log_group = QGroupBox("Logging")
        log_layout = QVBoxLayout()

        # Create a layout for the checkbox and help button
        logging_option_layout = QHBoxLayout()
        self.cb_verbose_logging = QCheckBox("Enable verbose logging (for debugging)")
        logging_option_layout.addWidget(self.cb_verbose_logging)
        logging_option_layout.addStretch()

        btn_logging_help = QToolButton()
        btn_logging_help.setIcon(QIcon.fromTheme("help-contextual"))
        btn_logging_help.setToolTip("What's this?")
        btn_logging_help.clicked.connect(self._show_verbose_logging_help)
        logging_option_layout.addWidget(btn_logging_help)

        log_layout.addLayout(logging_option_layout)

        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        layout.addSpacing(15)

        # --- Default Download Directory Section ---
        download_group = QGroupBox("Download Location")
        download_layout = QVBoxLayout()

        download_label_layout = QHBoxLayout()
        download_label = QLabel("Default directory for dependency downloads:")
        download_label_layout.addWidget(download_label)
        download_label_layout.addStretch()

        btn_download_help = QToolButton()
        btn_download_help.setIcon(QIcon.fromTheme("help-contextual"))
        btn_download_help.setToolTip("What's this?")
        btn_download_help.clicked.connect(self._show_download_dir_help)
        download_label_layout.addWidget(btn_download_help)

        download_layout.addLayout(download_label_layout)

        path_selection_layout = QHBoxLayout()
        self.le_download_path = QLineEdit()
        self.le_download_path.setReadOnly(True)
        path_selection_layout.addWidget(self.le_download_path)

        self.btn_browse = QPushButton("Browse...")
        self.btn_browse.clicked.connect(self._browse_directory)
        path_selection_layout.addWidget(self.btn_browse)

        download_layout.addLayout(path_selection_layout)

        download_group.setLayout(download_layout)
        layout.addWidget(download_group)

        layout.addStretch()

        # Connections
        self.cb_verbose_logging.toggled.connect(self.on_verbose_logging_toggled)

    def _load_settings(self):
        is_enabled = self.settings_manager.get_verbose_logging_enabled()
        self.cb_verbose_logging.setChecked(is_enabled)
        self.le_download_path.setText(self.settings_manager.get_default_download_directory())

    def on_verbose_logging_toggled(self, checked):
        self.settings_manager.set_verbose_logging_enabled(checked)

    def _browse_directory(self):
        current_path = self.settings_manager.get_default_download_directory()
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Default Download Directory",
            current_path,
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks
        )
        if directory:
            self.settings_manager.set_default_download_directory(directory)
            self.le_download_path.setText(directory)

    def _show_verbose_logging_help(self):
        QMessageBox.information(
            self,
            "About Verbose Logging",
            "When enabled, the application will show detailed logs during installation or uninstallation processes.\n\n"
            "This is useful for debugging issues or for users who want to see exactly what commands are being run in the background."
        )

    def _show_download_dir_help(self):
        QMessageBox.information(
            self,
            "About Default Download Directory",
            "This setting specifies the default folder where any required dependencies for a package will be downloaded.\n\n"
            "It is currently a placeholder for future functionality and does not affect the standard installation process."
        )


class InstallationSettingsWidget(QWidget):
    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- Extract Mode Section ---
        extract_group = QGroupBox("Installation Behavior")
        extract_layout = QVBoxLayout()

        self.cb_extract_mode = QCheckBox("Enable 'Install and Extract' mode")
        self.cb_extract_mode.setToolTip(
            "Warning: This is an experimental feature.\n"
            "It may not work as expected and might not clean up extracted files perfectly upon uninstallation."
        )
        extract_layout.addWidget(self.cb_extract_mode)

        extract_label = QLabel(
            "<b>Experimental:</b> When enabled, the wizard will first install the package "
            "and then extract its contents to a directory you choose."
        )
        extract_label.setWordWrap(True)
        extract_layout.addWidget(extract_label)

        extract_group.setLayout(extract_layout)
        layout.addWidget(extract_group)
        layout.addSpacing(15)

        # --- Desktop Shortcut Section (Experimental) ---
        shortcut_group = QGroupBox("Desktop Integration (Experimental)")
        shortcut_layout = QVBoxLayout()

        self.cb_create_shortcut = QCheckBox("Enable desktop shortcut creation feature")
        self.cb_create_shortcut.setToolTip(
            "Warning: This is an experimental feature.\n"
            "It may not work correctly on all desktop environments and might create duplicate or non-functional shortcuts."
        )
        shortcut_layout.addWidget(self.cb_create_shortcut)

        shortcut_label = QLabel(
            "<b>Experimental:</b> When enabled, the installation wizard will offer to create a "
            "desktop shortcut for the application."
        )
        shortcut_label.setWordWrap(True)
        shortcut_layout.addWidget(shortcut_label)

        shortcut_group.setLayout(shortcut_layout)
        layout.addWidget(shortcut_group)

        layout.addStretch()

        # Connections
        self.cb_extract_mode.toggled.connect(self.on_extract_mode_toggled)
        self.cb_create_shortcut.toggled.connect(self.on_create_shortcut_toggled)

    def _load_settings(self):
        is_extract_mode = self.settings_manager.get_setting("install_and_extract_enabled", "false") == "true"
        self.cb_extract_mode.setChecked(is_extract_mode)
        is_shortcut_mode = self.settings_manager.get_setting("create_desktop_shortcut_enabled", "false") == "true"
        self.cb_create_shortcut.setChecked(is_shortcut_mode)

    def on_extract_mode_toggled(self, checked):
        self.settings_manager.set_setting("install_and_extract_enabled", "true" if checked else "false")

    def on_create_shortcut_toggled(self, checked):
        self.settings_manager.set_setting("create_desktop_shortcut_enabled", "true" if checked else "false")


class ExperimentalSettingsWidget(QWidget):
    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- Extract Mode Section ---
        extract_group = QGroupBox("Installation Behavior")
        extract_layout = QVBoxLayout()

        self.cb_extract_mode = QCheckBox("Enable 'Install and Extract' mode")
        self.cb_extract_mode.setToolTip(
            "Warning: This is an experimental feature.\n"
            "It may not work as expected and might not clean up extracted files perfectly upon uninstallation."
        )
        extract_layout.addWidget(self.cb_extract_mode)

        extract_label = QLabel(
            "<b>Experimental:</b> When enabled, the wizard will first install the package "
            "and then extract its contents to a directory you choose."
        )
        extract_label.setWordWrap(True)
        extract_layout.addWidget(extract_label)

        extract_group.setLayout(extract_layout)
        layout.addWidget(extract_group)
        layout.addSpacing(15)

        # --- Desktop Shortcut Section (Experimental) ---
        shortcut_group = QGroupBox("Desktop Integration (Experimental)")
        shortcut_layout = QVBoxLayout()

        self.cb_create_shortcut = QCheckBox("Enable desktop shortcut creation feature")
        self.cb_create_shortcut.setToolTip(
            "Warning: This is an experimental feature.\n"
            "It may not work correctly on all desktop environments and might create duplicate or non-functional shortcuts."
        )
        shortcut_layout.addWidget(self.cb_create_shortcut)

        shortcut_label = QLabel(
            "<b>Experimental:</b> When enabled, the installation wizard will offer to create a "
            "desktop shortcut for the application."
        )
        shortcut_label.setWordWrap(True)
        shortcut_layout.addWidget(shortcut_label)

        shortcut_group.setLayout(shortcut_layout)
        layout.addWidget(shortcut_group)

        layout.addStretch()

        # Connections
        self.cb_extract_mode.toggled.connect(self.on_extract_mode_toggled)
        self.cb_create_shortcut.toggled.connect(self.on_create_shortcut_toggled)

    def _load_settings(self):
        is_extract_mode = self.settings_manager.get_setting("install_and_extract_enabled", "false") == "true"
        self.cb_extract_mode.setChecked(is_extract_mode)
        is_shortcut_mode = self.settings_manager.get_setting("create_desktop_shortcut_enabled", "false") == "true"
        self.cb_create_shortcut.setChecked(is_shortcut_mode)

    def on_extract_mode_toggled(self, checked):
        self.settings_manager.set_setting("install_and_extract_enabled", "true" if checked else "false")

    def on_create_shortcut_toggled(self, checked):
        self.settings_manager.set_setting("create_desktop_shortcut_enabled", "true" if checked else "false")


class SecuritySettingsWidget(QWidget):
    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- Auto Password Section ---
        group = QGroupBox("Automatic Sudo Authentication")
        group_layout = QVBoxLayout()

        self.cb_auto_password = QCheckBox("Enable automatic password entry for installations")
        group_layout.addWidget(self.cb_auto_password)

        warning_label = QLabel(
            "<font color='orange'><b>Warning:</b> Enabling this feature will store your sudo password "
            "in an encrypted format on your disk. While encrypted, this is less secure than "
            "entering your password each time. Use with caution.</font>"
        )
        warning_label.setWordWrap(True)
        group_layout.addWidget(warning_label)

        group.setLayout(group_layout)
        layout.addWidget(group)
        layout.addStretch()

        # Connections
        self.cb_auto_password.clicked.connect(self.on_auto_password_clicked)

    def _load_settings(self):
        is_enabled = self.settings_manager.get_setting("auto_password_enabled", "false") == "true"
        self.cb_auto_password.setChecked(is_enabled)

    def on_auto_password_clicked(self):
        from .gui_components import AuthenticationDialog # Local import to avoid circular dependency

        # If the user is checking the box
        if self.cb_auto_password.isChecked():
            # Use new authentication dialog
            password = AuthenticationDialog.get_auth_password(
                parent=self,
                operation="save password for automatic authentication",
                package_name="",
                is_retry=False
            )

            if password:
                self.settings_manager.save_password(password)
                self.settings_manager.set_setting("auto_password_enabled", "true")
                QMessageBox.information(self, "Success", "Password saved and automatic authentication enabled.")
            else:
                # User cancelled or entered empty password, so we revert the check.
                self.cb_auto_password.setChecked(False)
                # Ensure setting is also false, in case they cancel.
                self.settings_manager.set_setting("auto_password_enabled", "false")
        else:
            # If the user is unchecking the box
            self.settings_manager.save_password("") # Clear password
            self.settings_manager.set_setting("auto_password_enabled", "false")
            QMessageBox.information(self, "Password Cleared", "Automatic password entry has been disabled and the saved password has been cleared.")


class SettingsPage(QWidget):
    back_requested = pyqtSignal()
    
    # Define section indices for external navigation
    SECTION_GENERAL = 0
    SECTION_INSTALLATION = 1
    SECTION_EXPERIMENTAL = 2
    SECTION_SECURITY = 3
    SECTION_DONATE = 4
    SECTION_REPORT = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings_manager = SettingsManager()
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Use QTabWidget for top menu navigation
        self.tab_widget = QTabWidget()

        # Initialize section widgets and add them to scroll areas
        self.general_widget = GeneralSettingsWidget(self.settings_manager)
        self.installation_widget = InstallationSettingsWidget(self.settings_manager)
        self.experimental_widget = ExperimentalSettingsWidget(self.settings_manager)
        self.security_widget = SecuritySettingsWidget(self.settings_manager)
        self.donation_page = DonationPage()
        self.report_page = ReportPage()

        # Add widgets to tabs with scroll areas
        self.tab_widget.addTab(self._create_scrollable_area(self.general_widget), QIcon.fromTheme("preferences-system"), "General")
        self.tab_widget.addTab(self._create_scrollable_area(self.installation_widget), QIcon.fromTheme("system-software-install"), "Installation")
        self.tab_widget.addTab(self._create_scrollable_area(self.experimental_widget), QIcon.fromTheme("preferences-plugin"), "Experimental")
        self.tab_widget.addTab(self._create_scrollable_area(self.security_widget), QIcon.fromTheme("dialog-password"), "Security")
        self.tab_widget.addTab(self._create_scrollable_area(self.donation_page), QIcon.fromTheme("help-donate"), "Donate")
        self.tab_widget.addTab(self._create_scrollable_area(self.report_page), QIcon.fromTheme("tools-report-bug"), "Report a Bug")

        main_layout.addWidget(self.tab_widget)

        # --- Bottom Buttons ---
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.btn_back = QPushButton(QIcon.fromTheme("go-previous", QIcon.fromTheme("arrow-left")), "Back")
        self.btn_back.setMinimumSize(100, 35)
        button_layout.addWidget(self.btn_back)
        main_layout.addLayout(button_layout)

        # --- Connections ---
        self.btn_back.clicked.connect(self.back_requested.emit)

    def _create_scrollable_area(self, widget: QWidget) -> QScrollArea:
        """Wraps a widget in a QScrollArea to make it scrollable."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        # The widget needs to be placed i
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.addWidget(widget)
        scroll_area.setWidget(container)
        
        return scroll_area

    def set_section(self, index: int):
        """Allows external navigation to a specific settings section."""
        if 0 <= index < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(index)
