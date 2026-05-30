"""
MFlow — entry point.
Run: python main.py
"""
import sys, os, json, traceback, logging, faulthandler

# ── Faulthandler: catches C++ crashes (WebEngine, Resolve DLL) ───────────────
_LOG_DIR = os.path.join(os.path.expanduser("~"), ".mflow")
os.makedirs(_LOG_DIR, exist_ok=True)
_CRASH_LOG = os.path.join(_LOG_DIR, "crash.log")
_crash_f = open(_CRASH_LOG, "w", encoding="utf-8")
faulthandler.enable(_crash_f)

# ── OrderedDict shim: fusionscript DLL expects it in builtins on Python 3.10+ ─
import builtins
from collections import OrderedDict as _OD
if not hasattr(builtins, "OrderedDict"):
    builtins.OrderedDict = _OD

# ── Logging: always write to file + stderr so the terminal always has output ──
_LOG_DIR = os.path.join(os.path.expanduser("~"), ".mflow")
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_PATH = os.path.join(_LOG_DIR, "mflow.log")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("mflow")
log.info("MFlow starting — Python %s — %s", sys.version.split()[0], sys.platform)

# ── Make uncaught exceptions visible instead of silently closing ──────────────
def _excepthook(exc_type, exc_value, exc_tb):
    log.error("Uncaught exception:\n%s", "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    if sys.platform == "win32":
        input("\nPress Enter to close...")
sys.excepthook = _excepthook

# ── Path setup ────────────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ── Cross-platform env hints ──────────────────────────────────────────────────
def _setup_env():
    """Set environment variables needed across platforms."""
    if sys.platform == "win32":
        # Block Microsoft Store Python stubs from shadowing real Python
        parts = os.environ.get("PATH", "").split(os.pathsep)
        os.environ["PATH"] = os.pathsep.join(
            p for p in parts if "WindowsApps" not in p
        )
        # DaVinci Resolve DLL directory
        for rdir in [
            r"C:\Program Files\Blackmagic Design\DaVinci Resolve",
            r"C:\Program Files (x86)\Blackmagic Design\DaVinci Resolve",
        ]:
            if os.path.isdir(rdir) and rdir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = rdir + os.pathsep + os.environ["PATH"]
                try: os.add_dll_directory(rdir)
                except (AttributeError, OSError): pass
    elif sys.platform == "darwin":
        resolve_lib = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries"
        if os.path.isdir(resolve_lib):
            os.environ.setdefault("DYLD_LIBRARY_PATH", resolve_lib)
    else:  # Linux
        for ldir in ["/opt/resolve/libs", "/opt/resolve/lib"]:
            if os.path.isdir(ldir):
                os.environ.setdefault("LD_LIBRARY_PATH", ldir)

_setup_env()

try:
    from PySide6.QtWidgets import QApplication, QMainWindow
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEngineSettings
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtCore import Qt, QUrl, QTimer
except ImportError as e:
    log.error("PySide6 not installed: %s", e)
    log.error("Run: pip install PySide6")
    if sys.platform == "win32":
        input("\nPySide6 not found. Run install.py first. Press Enter...")
    sys.exit(1)

APP_HTML = os.path.join(HERE, "ui", "app.html")


class MFlowWindow(QMainWindow):
    def __init__(self, comp=None, fusion_app=None):
        super().__init__()
        self.setWindowTitle("MFlow")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.resize(940, 580)

        self._view = QWebEngineView()
        self.setCentralWidget(self._view)

        s = self._view.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,   True)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled,               True)
        s.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled,           False)

        self._channel = QWebChannel(self._view.page())
        try:
            from ui.backend import Backend
            self._backend = Backend(self, comp=comp, fusion_app=fusion_app)
        except Exception as e:
            log.error("Backend init failed: %s", e, exc_info=True)
            raise
        self._channel.registerObject("backend", self._backend)
        self._view.page().setWebChannel(self._channel)

        if not os.path.isfile(APP_HTML):
            log.error("app.html not found at: %s", APP_HTML)
            raise FileNotFoundError(f"app.html missing: {APP_HTML}")

        self._view.load(QUrl.fromLocalFile(APP_HTML))
        self._view.loadFinished.connect(self._on_page_ready)
        log.info("Window created, loading UI...")

    def _on_page_ready(self, ok):
        if not ok:
            log.error("app.html failed to load")
            return
        log.info("UI loaded")
        QTimer.singleShot(600, self._backend._announce_connection)

    def closeEvent(self, event):
        log.info("Closing MFlow")
        if hasattr(self, '_backend') and self._backend._watcher:
            self._backend._watcher.stop()
        super().closeEvent(event)


def main():
    # GPU acceleration: disable if user set gpu_acceleration=false in settings
    # Prevents WebEngine freezes on Nvidia+Optimus and some AMD setups
    try:
        with open(os.path.join(_LOG_DIR, "..", "MFlow", "settings.json"), encoding="utf-8") as _sf:
            _gpu = json.load(_sf).get("gpu_acceleration", True)
    except Exception:
        _gpu = True
    if not _gpu:
        os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                              "--disable-gpu --disable-software-rasterizer")
        log.info("GPU acceleration disabled by settings")

    app = QApplication(sys.argv)
    app.setApplicationName("MFlow")
    app.setApplicationVersion("2.1")

    comp = None
    try:
        from core.resolve_connection import get_resolve, get_comp
        from core.platform_config import settings_file
        custom = ""
        try:
            with open(settings_file(), encoding="utf-8") as f:
                custom = json.load(f).get("dvr_path", "")
        except Exception:
            pass
        resolve = get_resolve(custom)
        if resolve:
            comp = get_comp(resolve)
            log.info("Connected to Resolve")
        else:
            log.info("Resolve not found — running standalone")
    except Exception as e:
        log.warning("Resolve connection error: %s", e)

    try:
        win = MFlowWindow(comp=comp)
        win.show()
        code = app.exec()
        # Clean exit — remove crash log so we don't show stale crashes next launch
        try: _crash_f.close(); os.remove(_CRASH_LOG)
        except Exception: pass
        sys.exit(code)
    except Exception as e:
        log.error("Fatal error in MFlowWindow: %s", e, exc_info=True)
        if sys.platform == "win32":
            input("\nFatal error. Check ~/.mflow/mflow.log. Press Enter...")
        sys.exit(1)


if __name__ == "__main__":
    main()
