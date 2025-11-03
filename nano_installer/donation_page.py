from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
    QGroupBox,
    QFrame,
    QScrollArea,
)

class DonationPage(QWidget):
    back_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # Title
        title_layout = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(QIcon.fromTheme("help-donate", QIcon.fromTheme("emblem-favorite")).pixmap(32, 32))
        title_layout.addWidget(icon_label)

        title = QLabel("Support Nano Installer")
        font = title.font()
        font.setPointSize(16)
        font.setBold(True)
        title.setFont(font)
        title_layout.addWidget(title)
        title_layout.addStretch()
        main_layout.addLayout(title_layout)

        subtitle = QLabel("Your contributions help keep the project alive and support future development. Thank you for your generosity!")
        subtitle.setWordWrap(True)
        main_layout.addWidget(subtitle)

        main_layout.addWidget(QFrame(frameShape=QFrame.HLine, frameShadow=QFrame.Sunken))

        # --- Donation Options ---
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        
        scroll_content = QWidget()
        donation_layout = QVBoxLayout(scroll_content)
        donation_layout.setAlignment(Qt.AlignTop)

        # GPay Donation Option
        gpay_group = QGroupBox("GPay / UPI Donation")
        gpay_layout = QVBoxLayout(gpay_group)
        gpay_layout.setAlignment(Qt.AlignCenter)
        
        gpay_label = QLabel("Scan the QR code below to donate via GPay or any UPI app:")
        gpay_label.setAlignment(Qt.AlignCenter)
        gpay_layout.addWidget(gpay_label)
        
        # Load and display QR code image
        qr_code_label = QLabel()
        pixmap = QPixmap("assets/gpay.jpg")
        if not pixmap.isNull():
            # Scale pixmap down if necessary, assuming a reasonable size for a QR code
            scaled_pixmap = pixmap.scaled(250, 250, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            qr_code_label.setPixmap(scaled_pixmap)
            qr_code_label.setAlignment(Qt.AlignCenter)
            gpay_layout.addWidget(qr_code_label)
        else:
            gpay_layout.addWidget(QLabel("Error: GPay QR code image not found at assets/gpay.jpg"))
            
        donation_layout.addWidget(gpay_group)
        
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)

        # --- Bottom Buttons ---
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.btn_back = QPushButton(QIcon.fromTheme("go-previous", QIcon.fromTheme("arrow-left")), "Back")
        button_layout.addWidget(self.btn_back)
        main_layout.addLayout(button_layout)

        # --- Connections ---
        self.btn_back.clicked.connect(self.back_requested.emit)