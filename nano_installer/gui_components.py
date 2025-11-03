from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QFont, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QLabel,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QDialog,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from pathlib import Path

# Imports from other modules (to be created/moved)
# No imports from .main needed at top level

# -----------------------
# Enhanced Authentication Dialog
# -----------------------
class AuthenticationDialog(QDialog):
    def __init__(self, parent=None, operation="install software", package_name="", is_retry=False):
        super().__init__(parent)
        self.operation = operation
        self.package_name = package_name
        self.is_retry = is_retry
        self.password = ""
        
        self.setModal(True)
        self.setWindowTitle("Authentication Required")
        self.setFixedSize(450, 320)
        
        # Remove window controls for security
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.CustomizeWindowHint)
        
        self._setup_ui()
        
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(25, 25, 25, 25)
        
        # Security icon and title
        header_layout = QHBoxLayout()
        
        # Security shield icon
        icon_label = QLabel()
        shield_icon = QIcon.fromTheme("dialog-password", QIcon.fromTheme("security-high"))
        icon_label.setPixmap(shield_icon.pixmap(48, 48))
        icon_label.setAlignment(Qt.AlignTop)
        header_layout.addWidget(icon_label)
        
        # Title and description
        text_layout = QVBoxLayout()
        title_label = QLabel("Administrator Access Required")
        title_font = title_label.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        
        # Dynamic description based on operation and retry status
        if self.is_retry:
            desc_text = "<font color='#d32f2f'>Incorrect password. Please try again.</font><br><br>"
        else:
            desc_text = ""
            
        desc_text += f"Administrator privileges are required to {self.operation}."
        if self.package_name:
            desc_text += f"<br><br><b>Package:</b> {self.package_name}"
        
        desc_label = QLabel(desc_text)
        desc_label.setWordWrap(True)
        desc_label.setAlignment(Qt.AlignTop)
        
        text_layout.addWidget(title_label)
        text_layout.addWidget(desc_label)
        header_layout.addLayout(text_layout, 1)
        
        layout.addLayout(header_layout)
        
        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)
        
        # Password input section
        password_layout = QVBoxLayout()
        
        password_label = QLabel("Enter your password:")
        password_font = password_label.font()
        password_font.setBold(True)
        password_label.setFont(password_font)
        
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("Your administrator password")
        self.password_edit.setMinimumHeight(35)
        self.password_edit.returnPressed.connect(self.accept)
        
        # Show/hide password toggle
        password_container = QHBoxLayout()
        password_container.addWidget(self.password_edit)
        
        self.show_password_btn = QPushButton()
        self.show_password_btn.setIcon(QIcon.fromTheme("view-reveal", QIcon.fromTheme("eye")))
        self.show_password_btn.setCheckable(True)
        self.show_password_btn.setFixedSize(35, 35)
        self.show_password_btn.setToolTip("Show/Hide password")
        self.show_password_btn.toggled.connect(self._toggle_password_visibility)
        password_container.addWidget(self.show_password_btn)
        
        password_layout.addWidget(password_label)
        password_layout.addLayout(password_container)
        
        layout.addLayout(password_layout)
        
        # Security notice
        notice_layout = QHBoxLayout()
        notice_icon = QLabel()
        info_icon = QIcon.fromTheme("dialog-information")
        notice_icon.setPixmap(info_icon.pixmap(16, 16))
        
        notice_text = QLabel("Your password will not be stored and is used only for this operation.")
        notice_text.setWordWrap(True)
        # Use system font for notice
        notice_font = notice_text.font()
        notice_font.setPointSize(notice_font.pointSize() - 1)
        notice_text.setFont(notice_font)
        
        notice_layout.addWidget(notice_icon)
        notice_layout.addWidget(notice_text, 1)
        layout.addLayout(notice_layout)
        
        layout.addStretch()
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setMinimumSize(80, 35)
        self.cancel_btn.clicked.connect(self.reject)
        
        self.authenticate_btn = QPushButton("Authenticate")
        self.authenticate_btn.setMinimumSize(120, 35)
        self.authenticate_btn.setDefault(True)
        self.authenticate_btn.clicked.connect(self.accept)
        
        button_layout.addWidget(self.cancel_btn)
        button_layout.addSpacing(10)
        button_layout.addWidget(self.authenticate_btn)
        
        layout.addLayout(button_layout)
        
        # Focus on password field
        self.password_edit.setFocus()
        
    def _toggle_password_visibility(self, checked):
        if checked:
            self.password_edit.setEchoMode(QLineEdit.Normal)
            self.show_password_btn.setIcon(QIcon.fromTheme("view-conceal", QIcon.fromTheme("eye-blocked")))
            self.show_password_btn.setToolTip("Hide password")
        else:
            self.password_edit.setEchoMode(QLineEdit.Password)
            self.show_password_btn.setIcon(QIcon.fromTheme("view-reveal", QIcon.fromTheme("eye")))
            self.show_password_btn.setToolTip("Show password")
    
    def get_password(self):
        return self.password_edit.text()
    
    def accept(self):
        self.password = self.password_edit.text()
        if not self.password:
            # Use system colors for error indication
            self.password_edit.setPlaceholderText("Password is required")
            # Flash the field briefly to indicate error
            self.password_edit.selectAll()
            return
        super().accept()
    
    @staticmethod
    def get_auth_password(parent=None, operation="install software", package_name="", is_retry=False):
        """Static method to show auth dialog and return password"""
        dialog = AuthenticationDialog(parent, operation, package_name, is_retry)
        if dialog.exec_() == QDialog.Accepted:
            return dialog.get_password()
        return None

# -----------------------
# Dependency Download Popup Dialog
# -----------------------
class DependencyPopup(QDialog):
    def __init__(self, dependencies, parent=None):
        super().__init__(parent)
        self.dependencies = dependencies
        self.setWindowTitle("Installing Dependencies")
        self.setFixedSize(480, 380)
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.CustomizeWindowHint)
        
        self._setup_ui()
        
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(25, 25, 25, 25)
        
        # Header with icon
        header_layout = QHBoxLayout()
        
        # Download icon
        icon_label = QLabel()
        download_icon = QIcon.fromTheme("download", QIcon.fromTheme("go-down"))
        icon_label.setPixmap(download_icon.pixmap(40, 40))
        icon_label.setAlignment(Qt.AlignTop)
        header_layout.addWidget(icon_label)
        
        # Title and subtitle
        text_layout = QVBoxLayout()
        title_label = QLabel("Installing Dependencies")
        title_font = title_label.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        
        subtitle_label = QLabel("Required packages are being downloaded and installed")
        # Use system font with smaller size
        subtitle_font = subtitle_label.font()
        subtitle_font.setPointSize(subtitle_font.pointSize() - 1)
        subtitle_label.setFont(subtitle_font)
        
        text_layout.addWidget(title_label)
        text_layout.addWidget(subtitle_label)
        header_layout.addLayout(text_layout, 1)
        
        layout.addLayout(header_layout)
        
        # Progress info
        self.info_label = QLabel("Preparing to download dependencies...")
        self.info_label.setWordWrap(True)
        # Make info label bold using system font
        info_font = self.info_label.font()
        info_font.setBold(True)
        self.info_label.setFont(info_font)
        layout.addWidget(self.info_label)
        
        # Overall progress
        progress_label = QLabel("Overall Progress:")
        progress_font = progress_label.font()
        progress_font.setBold(True)
        progress_font.setPointSize(progress_font.pointSize() - 1)
        progress_label.setFont(progress_font)
        layout.addWidget(progress_label)
        
        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 100)
        self.overall_progress.setMinimumHeight(25)
        layout.addWidget(self.overall_progress)
        
        # Current package progress
        self.current_label = QLabel("")
        current_font = self.current_label.font()
        current_font.setBold(True)
        current_font.setPointSize(current_font.pointSize() - 1)
        self.current_label.setFont(current_font)
        layout.addWidget(self.current_label)
        
        self.current_progress = QProgressBar()
        self.current_progress.setRange(0, 100)
        self.current_progress.setMinimumHeight(20)
        layout.addWidget(self.current_progress)
        
        # Dependency list
        dep_label = QLabel("Dependencies to install:")
        dep_font = dep_label.font()
        dep_font.setBold(True)
        dep_label.setFont(dep_font)
        layout.addWidget(dep_label)
        
        self.dep_list = QListWidget()
        self.dep_list.setMaximumHeight(120)
        self.dep_list.setAlternatingRowColors(True)
        for dep in self.dependencies:
            self.dep_list.addItem(f"• {dep}")
        layout.addWidget(self.dep_list)
        
        # Close button (initially hidden)
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.close_btn = QPushButton("Close")
        self.close_btn.setMinimumSize(100, 35)
        self.close_btn.clicked.connect(self.accept)
        self.close_btn.setVisible(False)
        
        button_layout.addWidget(self.close_btn)
        layout.addLayout(button_layout)
        
    def update_progress(self, overall_percent, current_package="", current_percent=0, info=""):
        self.overall_progress.setValue(overall_percent)
        if current_package:
            self.current_label.setText(f"Installing: {current_package}")
        self.current_progress.setValue(current_percent)
        if info:
            self.info_label.setText(info)
            
    def finish_installation(self, success=True):
        if success:
            self.info_label.setText("<font color='green'>Dependencies installed successfully!</font>")
            self.overall_progress.setValue(100)
            self.current_progress.setValue(100)
        else:
            self.info_label.setText("<font color='red'>Some dependencies failed to install.</font>")
        self.close_btn.setVisible(True)

# -----------------------
# Offline installer tab
# -----------------------
class OfflinePage(QWidget):
    # Signal now carries the desired section index (int)
    settings_requested = pyqtSignal(int)
    update_requested = pyqtSignal()
    about_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        # A single button to select a .deb file
        self.btn_select_deb = QPushButton(QIcon.fromTheme("document-open", QIcon.fromTheme("folder-open")), " Select .deb Package to Install...")
        
        # Replace settings button with a menu button
        self.btn_settings_menu = QToolButton()
        self.btn_settings_menu.setIcon(QIcon.fromTheme("preferences-system"))
        self.btn_settings_menu.setText("Menu")
        self.btn_settings_menu.setPopupMode(QToolButton.InstantPopup)
        self.btn_settings_menu.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        
        # Create the menu
        settings_menu = QMenu(self)
        
        # Import constants from settings.py for section indices
        from .settings import SettingsPage
        
        self.action_general = settings_menu.addAction(QIcon.fromTheme("preferences-system"), "General Settings")
        self.action_installation = settings_menu.addAction(QIcon.fromTheme("system-software-install"), "Installation Behavior")
        self.action_security = settings_menu.addAction(QIcon.fromTheme("dialog-password"), "Security & Authentication")
        
        settings_menu.addSeparator()
        
        self.action_update = settings_menu.addAction(QIcon.fromTheme("system-software-update"), "Self Update")
        self.action_about = settings_menu.addAction(QIcon.fromTheme("help-about"), "About")
        
        self.btn_settings_menu.setMenu(settings_menu)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.btn_select_deb)
        button_layout.addStretch()

        # Top right settings menu button
        top_layout = QHBoxLayout()
        top_layout.addStretch()
        top_layout.addWidget(self.btn_settings_menu)

        layout.addLayout(top_layout)
        layout.addStretch(1)
        layout.addLayout(button_layout)
        layout.addStretch(1)

        # Signals
        self.btn_select_deb.clicked.connect(self.on_select_deb)
        
        # Connect menu actions to a unified signal emission
        self.action_general.triggered.connect(lambda: self.settings_requested.emit(SettingsPage.SECTION_GENERAL))
        self.action_installation.triggered.connect(lambda: self.settings_requested.emit(SettingsPage.SECTION_INSTALLATION))
        self.action_security.triggered.connect(lambda: self.settings_requested.emit(SettingsPage.SECTION_SECURITY))
        
        # Connect new actions
        self.action_update.triggered.connect(self.update_requested.emit)
        self.action_about.triggered.connect(self.about_requested.emit)

    def on_select_deb(self):
        dialog = QFileDialog(self)
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter("Debian Packages (*.deb)")
        dialog.setWindowTitle("Select .deb Package")
        dialog.setDirectory(str(Path.home()))
        # Use native file dialog for better desktop integration
        dialog.setOption(QFileDialog.DontUseNativeDialog, False)

        if dialog.exec_():
            files = dialog.selectedFiles()
            if files:
                # process_deb_file is imported locally to avoid circular dependency
                from .main import process_deb_file
                process_deb_file(files[0], self)