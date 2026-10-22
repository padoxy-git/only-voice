"""Graphical entry point. All controls are reached through the tray icon."""
import os
from pathlib import Path
import queue
import sys

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFormLayout,
                              QHBoxLayout, QLabel, QMenu, QMessageBox, QProgressBar,
                              QPushButton, QSystemTrayIcon, QTextEdit, QVBoxLayout, QWidget)

from .application import Application, Paths, lock
from .desktop_backend import DesktopBackend
from .gui_state import presentation
from .variants import PRECISIONS, VARIANTS

WINDOWS = sys.platform == 'win32'


def icon(active=False):
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor('#315ee8' if active else '#526179'))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, 60, 60)
    painter.setPen(QPen(QColor('white'), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for x, top in ((20, 26), (32, 17), (44, 23)):
        painter.drawLine(x, top, x, 64 - top)
    painter.end()
    return QIcon(pixmap)


def discover():
    if WINDOWS:
        from .windows_audio import microphones
    else:
        from .desktop_backend import microphones
    return microphones()


class Settings(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setWindowTitle('Only Voice · Configuración')
        self.resize(550, 610)
        layout = QVBoxLayout(self)
        title = QLabel('Only Voice')
        title.setStyleSheet('font-size:26px;font-weight:700')
        layout.addWidget(title)
        layout.addWidget(QLabel('Tu voz, en primer plano.'))
        self.message = QLabel('Preparando los ajustes…')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        form = QFormLayout()
        self.source = QComboBox()
        self.refresh = QPushButton('Actualizar micrófonos')
        self.refresh.clicked.connect(controller.refresh_devices)
        form.addRow('Micrófono', self.source)
        form.addRow('', self.refresh)
        self.mode = QComboBox()
        self.mode.addItem('Solo mi voz', 'voice')
        self.mode.addItem('Reducir ruido', 'noise')
        form.addRow('Filtro', self.mode)
        self.precision = QComboBox()
        for precision in PRECISIONS:
            self.precision.addItem(VARIANTS[precision]['label'], precision)
        form.addRow('Variante de voz', self.precision)
        layout.addLayout(form)
        self.hint = QLabel('')
        self.hint.setWordWrap(True)
        self.mode.currentIndexChanged.connect(self.describe)
        self.precision.currentIndexChanged.connect(self.describe)
        layout.addWidget(self.hint)
        row = QHBoxLayout()
        self.record = QPushButton('Registrar mi voz (15 s)')
        self.record.clicked.connect(lambda: controller.register())
        row.addWidget(self.record)
        self.import_wav = QPushButton('Usar un WAV…')
        self.import_wav.clicked.connect(self.choose_wav)
        row.addWidget(self.import_wav)
        layout.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        self.levels = []
        for text in ('Nivel de entrada', 'Nivel filtrado'):
            layout.addWidget(QLabel(text))
            level = QProgressBar()
            level.setRange(0, 60)
            level.setTextVisible(False)
            layout.addWidget(level)
            self.levels.append(level)
        self.action = QPushButton('Activar filtro')
        self.action.clicked.connect(controller.toggle)
        layout.addWidget(self.action)
        if WINDOWS:
            help_text = QLabel('Salida: CABLE Input → en tu llamada elige CABLE Output.\n'
                               'Instala VB-CABLE y reinicia Windows antes de activar el filtro.')
            help_text.setWordWrap(True)
            layout.addWidget(help_text)
            cable = QPushButton('Descargar VB-CABLE del sitio oficial')
            cable.clicked.connect(lambda: QDesktopServices.openUrl(QUrl('https://vb-audio.com/Cable/')))
            layout.addWidget(cable)
        else:
            layout.addWidget(QLabel('En tu aplicación de llamadas elige el micrófono Only_Voice.'))
        details = QPushButton('Ver registro de actividad')
        details.clicked.connect(controller.details)
        layout.addWidget(details)
        note = QLabel('Cerrar esta ventana mantiene el filtro. Usa «Salir» en el icono de bandeja para detenerlo.')
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()

    def describe(self):
        self.precision.setEnabled(self.mode.currentData() == 'voice' and not self.controller.active)
        self.hint.setText('Registra una muestra de tu voz. Los modelos se descargan al primer uso; '
                          'el audio se procesa en tu equipo.' if self.mode.currentData() == 'voice'
                          else 'RNNoise reduce el ruido sin necesitar un perfil de voz.')

    def choose_wav(self):
        filename, _ = QFileDialog.getOpenFileName(self, 'Muestra de voz: WAV PCM16, 5–60 segundos', '', 'WAV (*.wav)')
        if filename:
            self.controller.register(filename)

    def closeEvent(self, event):
        event.ignore()
        self.hide()


class TrayController:
    def __init__(self, app, application=None):
        self.app = app
        self.application = application or Application()
        self.backend = DesktopBackend(self.application)
        self.active = False
        self.pending = False
        self.quitting = False
        self.loaded = False
        self.devices_loaded = False
        self.state = {'active': False}
        self.has_profile = False
        self.window = Settings(self)
        self.window.describe()
        self.save_timer = QTimer()
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.save_preferences)
        for combo in (self.window.source, self.window.mode, self.window.precision):
            combo.currentIndexChanged.connect(self.preferences_changed)
        self.tray = QSystemTrayIcon(icon(), app)
        self.tray.setToolTip('Only Voice · Detenido')
        self.menu = QMenu()
        self.settings_action = self.menu.addAction('Configuración…', self.show_settings)
        self.toggle_action = self.menu.addAction('Activar filtro', self.toggle)
        self.menu.addSeparator()
        self.quit_action = self.menu.addAction('Salir', self.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.activated)
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(150)
        self.tray.show()
        self.refresh_devices()

    def preferences_changed(self):
        if self.loaded and not self.active and self.devices_loaded:
            self.save_timer.start(300)
            self.render()

    def save_preferences(self):
        options = self.selection()
        self.backend.submit('settings', lambda: self.application.save_settings(**options))

    def activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_settings()

    def show_settings(self):
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def submit(self, kind, function):
        if self.pending:
            return
        self.pending = True
        self.backend.submit(kind, function)
        self.render()

    def refresh_devices(self):
        self.window.refresh.setEnabled(False)
        self.backend.submit('devices', discover)

    def selection(self):
        return dict(source=self.window.source.currentData(), mode=self.window.mode.currentData(),
                    precision=self.window.precision.currentData())

    def toggle(self):
        if self.active:
            self.submit('job', self.application.stop)
        else:
            options = self.selection()
            self.submit('job', lambda: self.application.start(**options))

    def register(self, wav=None):
        source = self.window.source.currentData()
        self.submit('job', lambda: self.application.register(source=source, wav=wav))

    def details(self):
        self.backend.submit('details', self.application.details)

    def quit(self):
        if self.pending:
            self.show_settings()
            self.window.message.setText('Espera a que termine la operación antes de salir.')
            return
        self.quitting = True
        self.submit('quit', self.application.stop)

    def render(self):
        display = presentation(self.state, self.has_profile, self.window.mode.currentData())
        self.window.message.setText(display['message'])
        if WINDOWS and self.state.get('phase') == 'running':
            self.window.message.setText('Filtro activo. En tu llamada selecciona CABLE Output (VB-Audio Virtual Cable).')
        ready = self.loaded and self.devices_loaded and not self.pending
        self.window.action.setText('Un momento…' if self.pending else display['action'])
        self.window.action.setEnabled(ready and display['enabled'])
        self.toggle_action.setText(display['action'])
        self.toggle_action.setEnabled(ready and display['enabled'])
        self.quit_action.setEnabled(not self.pending)
        for control in (self.window.source, self.window.mode, self.window.record, self.window.import_wav):
            control.setEnabled(ready and not self.active)
        self.window.precision.setEnabled(ready and not self.active and self.window.mode.currentData() == 'voice')
        self.window.progress.setVisible(self.active and self.state.get('task') == 'profile')
        self.window.progress.setValue(int(self.state.get('progress', 0) * 100))
        for level, key in zip(self.window.levels, ('input_db', 'output_db')):
            level.setValue(int(max(0, min(60, self.state.get(key, -60) + 60))) if self.active else 0)
        self.tray.setToolTip('Only Voice · ' + display['badge'])
        self.tray.setIcon(icon(self.state.get('phase') == 'running' and self.active))

    def tick(self):
        snapshot = self.backend.take_update()
        if snapshot:
            self.state = snapshot['state']
            self.active = self.state['active']
            self.has_profile = snapshot['has_profile']
            if not self.loaded:
                settings = snapshot['settings']
                self.window.mode.setCurrentIndex(self.window.mode.findData(settings['mode']))
                self.window.precision.setCurrentIndex(self.window.precision.findData(settings['precision']))
                self.loaded = True
            self.render()
        while True:
            try:
                kind, value, error = self.backend.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'devices':
                self.window.refresh.setEnabled(True)
                if not error:
                    saved = self.application.settings()['source']
                    selected = self.window.source.currentData() if self.devices_loaded else saved
                    self.window.source.blockSignals(True)
                    self.window.source.clear()
                    self.window.source.addItem('Micrófono del sistema', None)
                    for item in value:
                        self.window.source.addItem(item['description'], item['name'])
                    index = self.window.source.findData(selected)
                    if selected and index == -1:
                        self.window.source.addItem(f'{selected} (desconectado)', selected)
                        index = self.window.source.count() - 1
                    self.window.source.setCurrentIndex(max(0, index))
                    self.window.source.blockSignals(False)
                    self.devices_loaded = bool(value)
                    if not value:
                        error = 'No se encontraron micrófonos. Conecta uno y pulsa Actualizar.'
            elif kind in ('job', 'quit'):
                self.pending = False
                if kind == 'quit' and not error:
                    self.backend.close()
                    self.tray.hide()
                    self.window.hide()
                    self.timer.stop()
                    self.app.quit()
                    return
                self.quitting = False
            elif kind == 'details' and not error:
                dialog = QMessageBox(self.window)
                dialog.setWindowTitle('Only Voice · Actividad')
                dialog.setText('Registro local de actividad')
                dialog.setDetailedText(value)
                dialog.exec()
            self.render()
            if error:
                self.window.message.setText(error)
                self.tray.showMessage('Only Voice', error, QSystemTrayIcon.MessageIcon.Warning)
                self.show_settings()


def main():
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName('Only Voice')
    app.setQuitOnLastWindowClosed(False)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, 'Only Voice', 'No hay una bandeja del sistema disponible. '
                             'Activa los iconos de bandeja del escritorio y vuelve a abrir Only Voice.')
        return 1
    try:
        with lock(Paths().file('tray.lock'), blocking=False):
            controller = TrayController(app)
            app.aboutToQuit.connect(controller.backend.close)
            return app.exec()
    except BlockingIOError:
        return 0  # The existing tray instance remains the sole controller.


if __name__ == '__main__':
    raise SystemExit(main())
