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
        # Use a QHBoxLayout with spacers to center the content horizontally
        centering_layout = QHBoxLayout()
        centering_layout.addStretch()

        gpay_group = QGroupBox("GPay / UPI Donation")
        gpay_group.setFixedWidth(300) # Give the group box a fixed width for better centering
        gpay_layout = QVBoxLayout(gpay_group)
        
        gpay_label = QLabel("Scan the QR code below to donate via GPay or any UPI app:")
        gpay_label.setAlignment(Qt.AlignCenter)
        gpay_label.setWordWrap(True)
        gpay_layout.addWidget(gpay_label)
        
        # Load and display QR code image
        qr_code_label = QLabel()
        # Use absolute path for installed asset
        asset_path = "/usr/share/nano-installer/assets/gpay.jpg"
        pixmap = QPixmap(asset_path)
        if not pixmap.isNull():
            # Scale pixmap to a fixed size for a clean look
            scaled_pixmap = pixmap.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            qr_code_label.setFixedSize(200, 200)
            qr_code_label.setPixmap(scaled_pixmap)
            qr_code_label.setAlignment(Qt.AlignCenter)
            gpay_layout.addWidget(qr_code_label)
        else:
            gpay_layout.addWidget(QLabel(f"Error: GPay QR code image not found at {asset_path}"))
            
        centering_layout.addWidget(gpay_group)
        centering_layout.addStretch()
        donation_layout.addLayout(centering_layout)
        
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)

        main_layout.addStretch()