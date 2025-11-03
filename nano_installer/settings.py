import subprocess
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from PyQt5.QtCore import QSettings, Qt, pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QFileDialog,
    QLineEdit,
)

# Import AuthenticationDialog from gui_components (will be created next)
from .gui_components import AuthenticationDialog

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
        layout.setAlignment(Qt.AlignTop)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- Verbose Logging Section ---
        log_group = QGroupBox("Logging")
        log_layout = QVBoxLayout()

        self.cb_verbose_logging = QCheckBox("Enable verbose logging (for debugging)")
        log_layout.addWidget(self.cb_verbose_logging)

        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        layout.addSpacing(15)

        # --- Default Download Directory Section ---
        download_group = QGroupBox("Download Location")
        download_layout = QVBoxLayout()

        download_label = QLabel("Default directory for dependency downloads:")
        download_layout.addWidget(download_label)

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
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        if directory:
            self.settings_manager.set_default_download_directory(directory)
            self.le_download_path.setText(directory)


class InstallationSettingsWidget(QWidget):
    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- Extract Mode Section ---
        extract_group = QGroupBox("Installation Behavior")
        extract_layout = QVBoxLayout()

        self.cb_extract_mode = QCheckBox("Enable 'Install and Extract' mode")
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
        layout.setAlignment(Qt.AlignTop)
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
    SECTION_SECURITY = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings_manager = SettingsManager()
        self._init_ui()
        
    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # Title
        title = QLabel("Application Settings")
        font = title.font()
        font.setPointSize(16)
        font.setBold(True)
        title.setFont(font)
        main_layout.addWidget(title)
        main_layout.addSpacing(15)
        
        # Content Area (Sidebar + Stacked Widgets)
        content_layout = QHBoxLayout()
        
        # 1. Navigation List (Sidebar)
        self.nav_list = QListWidget()
        self.nav_list.setMaximumWidth(180)
        self.nav_list.setMinimumWidth(150)
        self.nav_list.setFrameShape(QListWidget.NoFrame)
        
        item_general = QListWidgetItem(QIcon.fromTheme("preferences-system"), "General")
        self.nav_list.addItem(item_general)
        item_installation = QListWidgetItem(QIcon.fromTheme("system-software-install"), "Installation")
        self.nav_list.addItem(item_installation)
        item_security = QListWidgetItem(QIcon.fromTheme("dialog-password"), "Security")
        self.nav_list.addItem(item_security)
        
        self.nav_list.setCurrentRow(0) # Default to General
        content_layout.addWidget(self.nav_list)
        
        # 2. Settings Stack
        self.settings_stack = QStackedWidget()
        
        # Initialize section widgets
        self.general_widget = GeneralSettingsWidget(self.settings_manager)
        self.installation_widget = InstallationSettingsWidget(self.settings_manager)
        self.security_widget = SecuritySettingsWidget(self.settings_manager)
        
        self.settings_stack.addWidget(self.general_widget)
        self.settings_stack.addWidget(self.installation_widget)
        self.settings_stack.addWidget(self.security_widget)
        
        content_layout.addWidget(self.settings_stack)
        
        main_layout.addLayout(content_layout)
        main_layout.addStretch()
        
        # --- Bottom Buttons ---
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.btn_back = QPushButton(QIcon.fromTheme("go-previous", QIcon.fromTheme("arrow-left")), "Back")
        button_layout.addWidget(self.btn_back)
        main_layout.addLayout(button_layout)

        # --- Connections ---
        self.nav_list.currentRowChanged.connect(self.settings_stack.setCurrentIndex)
        self.btn_back.clicked.connect(self.back_requested.emit)

    def set_section(self, index: int):
        """Allows external navigation to a specific settings section."""
        if 0 <= index < self.nav_list.count():
            self.nav_list.setCurrentRow(index)