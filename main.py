"""
FusionFlow — Studio / standalone entry point.
Run:  python main.py
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEngineScript
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QIcon

APP_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "app.html")


class MFlowWindow(QMainWindow):
    def __init__(self, comp=None, fusion_app=None):
        super().__init__()
        self.setWindowTitle("FusionFlow")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.resize(940, 580)

        # ── WebEngine view ────────────────────────────────────────────────────
        self._view = QWebEngineView()
        self.setCentralWidget(self._view)

        # Allow loading Google Fonts from local file URL
        s = self._view.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,   True)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled,               True)
        s.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled,           False)

        # ── WebChannel ────────────────────────────────────────────────────────
        self._channel = QWebChannel(self._view.page())
        from ui.backend import Backend
        self._backend = Backend(self, comp=comp, fusion_app=fusion_app)
        self._channel.registerObject("backend", self._backend)
        self._view.page().setWebChannel(self._channel)

        # ── Load HTML ─────────────────────────────────────────────────────────
        self._view.load(QUrl.fromLocalFile(APP_HTML))

        # Announce connection status only AFTER page + WebChannel are ready
        # (loadFinished fires when HTML/JS is ready but QWebChannel needs ~300ms more)
        self._view.loadFinished.connect(self._on_page_ready)

    def _on_page_ready(self, ok):
        if not ok:
            return
        # Delay to let QWebChannel JS handshake complete
        from PySide6.QtCore import QTimer
        QTimer.singleShot(600, self._backend._announce_connection)

    def closeEvent(self, event):
        if hasattr(self, '_backend') and self._backend._watcher:
            self._backend._watcher.stop()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("FusionFlow")
    app.setApplicationVersion("2.0")
    app.setStyleSheet("* { font-family: 'JetBrains Mono', monospace; }")

    # Try Resolve connection (Studio mode)
    comp = None
    try:
        from core.resolve_connection import get_resolve, get_comp
        from core.platform_config import settings_file
        custom = ""
        try:
            with open(settings_file()) as f:
                custom = json.load(f).get("dvr_path", "")
        except Exception:
            pass
        resolve = get_resolve(custom)
        if resolve:
            comp = get_comp(resolve)
    except Exception:
        pass

    win = MFlowWindow(comp=comp)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print(f"\n[MFlow] Error fatal:\n{e}")
        traceback.print_exc()
        input("\nPresiona Enter para cerrar...")
