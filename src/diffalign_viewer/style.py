"""Application stylesheet — professional dark theme."""

STYLESHEET = """
* {
    color: #e0e0e8;
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    font-size: 12px;
}

QMainWindow, QWidget {
    background-color: #1e1e2e;
}

QStatusBar {
    background-color: #252536;
    color: #cfcfe0;
    border-top: 1px solid #3a3a52;
}

QStatusBar::item {
    border: none;
}

QToolBar {
    background-color: #252536;
    border-bottom: 1px solid #3a3a52;
    spacing: 4px;
    padding: 4px 6px;
}

QToolBar QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 3px;
    padding: 4px 10px;
    color: #e0e0e8;
}

QToolBar QToolButton:hover {
    background: #35354d;
    border-color: #4a4a65;
}

QToolBar QToolButton:pressed {
    background: #3d3d58;
}

QMenuBar {
    background: #252536;
    color: #e0e0e8;
}

QMenuBar::item:selected {
    background: #35354d;
}

QMenu {
    background: #252536;
    border: 1px solid #3a3a52;
    color: #e0e0e8;
    padding: 4px 0;
}

QMenu::item {
    padding: 5px 22px;
}

QMenu::item:selected {
    background: #35354d;
}

QMenu::separator {
    height: 1px;
    background: #3a3a52;
    margin: 4px 0;
}

QDockWidget {
    color: #e0e0e8;
    titlebar-close-icon: url(none);
    titlebar-normal-icon: url(none);
}

QDockWidget::title {
    background: #252536;
    border-bottom: 1px solid #3a3a52;
    padding: 6px 10px;
    text-align: left;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    font-size: 10px;
    color: #a0a0b8;
}

QGroupBox {
    border: 1px solid #3a3a52;
    border-radius: 4px;
    margin-top: 14px;
    padding: 6px 6px 6px 6px;
    color: #cfcfe0;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    color: #a0a0b8;
    text-transform: uppercase;
    font-size: 10px;
    letter-spacing: 0.5px;
}

QPushButton {
    background-color: #2d2d42;
    border: 1px solid #4a4a65;
    border-radius: 3px;
    padding: 4px 12px;
    color: #e0e0e8;
}

QPushButton:hover {
    background-color: #35354d;
    border-color: #5b8af0;
}

QPushButton:pressed {
    background-color: #3d3d58;
}

QPushButton:disabled {
    color: #6a6a82;
    border-color: #3a3a52;
}

QPushButton[primary="true"] {
    background-color: #5b8af0;
    border-color: #5b8af0;
    color: #ffffff;
    font-weight: 600;
}

QPushButton[primary="true"]:hover {
    background-color: #4a7ae0;
}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #1a1a26;
    border: 1px solid #3a3a52;
    border-radius: 3px;
    padding: 3px 6px;
    color: #e0e0e8;
    selection-background-color: #5b8af0;
}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #5b8af0;
}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background: #2d2d42;
    border: none;
    width: 14px;
}

QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
    background: #35354d;
}

QCheckBox {
    spacing: 6px;
    color: #e0e0e8;
}

QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #4a4a65;
    border-radius: 2px;
    background: #1a1a26;
}

QCheckBox::indicator:checked {
    background: #5b8af0;
    border-color: #5b8af0;
}

QSlider::groove:horizontal {
    height: 4px;
    background: #2d2d42;
    border-radius: 2px;
}

QSlider::handle:horizontal {
    width: 12px;
    height: 12px;
    margin: -5px 0;
    border-radius: 6px;
    background: #5b8af0;
}

QSlider::handle:horizontal:hover {
    background: #6b9af6;
}

QTableView {
    background: #1a1a26;
    alternate-background-color: #20202c;
    border: 1px solid #3a3a52;
    gridline-color: #2d2d42;
    color: #e0e0e8;
    selection-background-color: #2d3a5a;
    selection-color: #ffffff;
}

QTableView::item:selected {
    background: #2d3a5a;
}

QHeaderView::section {
    background: #252536;
    color: #a0a0b8;
    border: none;
    border-right: 1px solid #3a3a52;
    border-bottom: 1px solid #3a3a52;
    padding: 4px 8px;
    font-weight: 600;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.4px;
}

QListWidget {
    background: #1a1a26;
    border: 1px solid #3a3a52;
    color: #e0e0e8;
}

QListWidget::item {
    padding: 4px 8px;
    border-bottom: 1px solid #2d2d42;
    font-family: 'Cascadia Mono', 'Consolas', monospace;
    font-size: 11px;
}

QListWidget::item:hover {
    background: #2d2d42;
}

QListWidget::item:selected {
    background: #2d3a5a;
}

QScrollBar:vertical {
    background: #1a1a26;
    width: 10px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #4a4a65;
    border-radius: 4px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background: #5a5a78;
}

QScrollBar:horizontal {
    background: #1a1a26;
    height: 10px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background: #4a4a65;
    border-radius: 4px;
    min-width: 20px;
}

QScrollBar::handle:horizontal:hover {
    background: #5a5a78;
}

QScrollBar::add-line, QScrollBar::sub-line {
    background: none;
    border: none;
}

QProgressBar {
    background: #1a1a26;
    border: 1px solid #3a3a52;
    border-radius: 3px;
    height: 14px;
    text-align: center;
    color: #e0e0e8;
}

QProgressBar::chunk {
    background: #5b8af0;
    border-radius: 2px;
}

QFrame#paramsPanel, QFrame#templateOligoFrame {
    background: #252536;
    border: 1px solid #3a3a52;
    border-radius: 3px;
}

QToolTip {
    background: #1a1a26;
    color: #e0e0e8;
    border: 1px solid #4a4a65;
    padding: 6px 8px;
    font-family: 'Cascadia Mono', 'Consolas', monospace;
    font-size: 11px;
}

QSplitter::handle {
    background: #3a3a52;
}

QSplitter::handle:horizontal {
    width: 1px;
}

QSplitter::handle:vertical {
    height: 1px;
}
"""
