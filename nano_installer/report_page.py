from . import constants
import webbrowser
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
    QTextEdit,
    QFrame,
)

class ReportPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # Title
        title_layout = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(QIcon.fromTheme("tools-report-bug", QIcon.fromTheme("dialog-warning")).pixmap(32, 32))
        title_layout.addWidget(icon_label)

        title = QLabel("Report a Bug or Suggest a Feature")
        font = title.font()
        font.setPointSize(16)
        font.setBold(True)
        title.setFont(font)
        title_layout.addWidget(title)
        title_layout.addStretch()
        main_layout.addLayout(title_layout)

        subtitle = QLabel("Found an issue or have an idea for a new feature? Please let us know by creating an issue on our GitHub page.")
        subtitle.setWordWrap(True)
        main_layout.addWidget(subtitle)

        main_layout.addWidget(QFrame(frameShape=QFrame.HLine, frameShadow=QFrame.Sunken))

        # --- GitHub Button ---
        self.btn_github = QPushButton(QIcon.fromTheme("github"), "Open GitHub Issues Page")
        self.btn_github.setMinimumHeight(40)
        main_layout.addWidget(self.btn_github)

        info_label = QLabel("Clicking the button will open the new issue page in your web browser. Please provide as much detail as possible, including steps to reproduce the bug, your operating system, and any error messages you received.")
        info_label.setWordWrap(True)
        main_layout.addWidget(info_label)
        
        main_layout.addStretch()

        # --- Connections ---
        self.btn_github.clicked.connect(lambda: webbrowser.open(constants.REPORT_ISSUES_URL))