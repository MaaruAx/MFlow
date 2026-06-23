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
    from PySide6.QtCore import Qt, QUrl, QTimer, QAbstractNativeEventFilter
    from PySide6.QtGui import QColor, QIcon
except ImportError as e:
    log.error("PySide6 not installed: %s", e)
    log.error("Run: pip install PySide6")
    if sys.platform == "win32":
        input("\nPySide6 not found. Run install.py first. Press Enter...")
    sys.exit(1)

APP_HTML = os.path.join(HERE, "ui", "app.html")

def _resource(relative):
    """Resuelve rutas para frozen (PyInstaller) y desarrollo."""
    base = getattr(sys, "_MEIPASS", HERE)
    return os.path.join(base, relative)


# Arbitrary id for our single registered hotkey — only needs to be unique
# within this process, since RegisterHotKey scopes ids per-HWND.
HOTKEY_ID_SCAN_ALL = 1


class _GlobalHotkeyFilter(QAbstractNativeEventFilter):
    """Catches WM_HOTKEY messages registered via user32.RegisterHotKey so the
    Scan All shortcut (Ctrl+R) works even when MFlow's window doesn't have OS
    focus. Windows-only — RegisterHotKey is never called on other platforms,
    so this filter simply never receives a matching message there and is a
    harmless no-op. Defensive on every line: a malformed/unexpected native
    message must never crash the app, only skip silently."""
    def __init__(self, hotkey_id, callback):
        super().__init__()
        self._hotkey_id = hotkey_id
        self._callback = callback

    def nativeEventFilter(self, eventType, message):
        try:
            if eventType == b"windows_generic_MSG":
                import ctypes.wintypes as wt
                msg = wt.MSG.from_address(int(message))
                WM_HOTKEY = 0x0312
                if msg.message == WM_HOTKEY and msg.wParam == self._hotkey_id:
                    try:
                        self._callback()
                    except Exception as e:
                        log.warning("[Hotkey] Callback raised: %s", e)
        except Exception as e:
            log.debug("[Hotkey] Native event filter error (ignored): %s", e)
        return False, 0


class MFlowWindow(QMainWindow):
    def __init__(self, comp=None, fusion_app=None, resolve=None):
        super().__init__()
        self.setWindowTitle("MFlow")
        self.setWindowIcon(QIcon(_resource("MFlow.ico")))
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.resize(940, 580)
        self._hotkey_filter = None   # kept alive here — installNativeEventFilter
                                      # does not hold a strong ref in PySide6

        self._view = QWebEngineView()
        self.setCentralWidget(self._view)
        # Eliminates white flash before CSS loads — must be set before loadUrl()
        self._view.page().setBackgroundColor(QColor("#121217"))

        s = self._view.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,   True)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled,               True)
        s.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled,           False)

        self._channel = QWebChannel(self._view.page())
        try:
            from ui.backend import Backend
            self._backend = Backend(self, comp=comp, fusion_app=fusion_app, resolve=resolve)
        except Exception as e:
            log.error("Backend init failed: %s", e, exc_info=True)
            raise
        self._channel.registerObject("backend", self._backend)
        self._view.page().setWebChannel(self._channel)

        # ── Global Ctrl+R → Scan All (opt-in, Windows only) ────────────────────
        # Reads the persisted setting directly off the backend's already-loaded
        # settings dict — avoids a second disk read and stays in sync with
        # whatever save_settings() last wrote.
        try:
            if bool(self._backend._settings.get("global_scan_hotkey", False)):
                self._register_global_hotkey()
        except Exception as e:
            log.debug("[Hotkey] Startup registration skipped: %s", e)

        # ── qwebchannel.js injection ──────────────────────────────────────────
        # Qt 6.7+ blocks qrc:// resources from file:// pages (security policy).
        # The <script src="qrc:///qtwebchannel/qwebchannel.js"> tag in app.html
        # fails silently, leaving QWebChannel undefined in JS.  As a result:
        #   * backend is never assigned -> every if(backend)btn.click() is a no-op
        #   * js_ready() is never called -> connection never announced, presets
        #     never loaded, the UI appears open but completely non-functional.
        # Fix: inject the script at DocumentCreation via QWebEngineScript, which
        # runs before any <script> tags and is not subject to the qrc:// ban.
        try:
            from PySide6.QtWebEngineCore import QWebEngineScript
            from PySide6.QtCore import QFile, QIODevice
            _qwc = QFile(":/qtwebchannel/qwebchannel.js")
            if _qwc.open(QIODevice.OpenModeFlag.ReadOnly):
                _js = bytes(_qwc.readAll()).decode("utf-8", errors="replace")
                _qwc.close()
                _script = QWebEngineScript()
                _script.setName("__qwebchannel_inject__")
                _script.setSourceCode(_js)
                _script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
                _script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
                self._view.page().scripts().insert(_script)
                log.debug("qwebchannel.js injected via QWebEngineScript")
            else:
                log.warning("Could not read qrc:///qtwebchannel/qwebchannel.js -- "
                            "UI may not respond if Qt version >= 6.7")
        except Exception as _e:
            log.warning("qwebchannel.js injection skipped: %s", _e)

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
        log.info("UI loaded — waiting for JS js_ready() signal")

    # ── Global Ctrl+R hotkey (Scan All, works without window focus) ────────
    # Windows-only: RegisterHotKey/UnregisterHotKey are Win32 APIs with no
    # direct equivalent wired up here for macOS/Linux. Calling these methods
    # on other platforms is always safe — they detect the platform and
    # return False/no-op instead of raising, so the rest of the app (and the
    # Settings toggle that drives this) never has to special-case the OS.
    def _register_global_hotkey(self):
        if sys.platform != "win32":
            log.info("[Hotkey] Global hotkeys are Windows-only — skipped on %s", sys.platform)
            return False
        try:
            import ctypes
            MOD_CONTROL = 0x0002
            VK_R = 0x52
            # Pass NULL (None) as hwnd so WM_HOTKEY is posted to the calling
            # thread's message queue — this is more reliable with Qt's event
            # loop than tying the message to a specific window handle.
            ok = ctypes.windll.user32.RegisterHotKey(None, HOTKEY_ID_SCAN_ALL, MOD_CONTROL, VK_R)
            if not ok:
                err = ctypes.windll.kernel32.GetLastError()
                log.warning("[Hotkey] RegisterHotKey failed (Win32 error %d) — "
                            "Ctrl+R may already be bound by another running app", err)
                return False
            # Install the native filter once and keep a strong reference on
            # self — PySide6 does not keep one, and a garbage-collected
            # filter silently stops receiving events with no error anywhere.
            if self._hotkey_filter is None:
                self._hotkey_filter = _GlobalHotkeyFilter(
                    HOTKEY_ID_SCAN_ALL, self._on_global_scan_hotkey)
                app = QApplication.instance()
                if app is not None:
                    app.installNativeEventFilter(self._hotkey_filter)
            log.info("[Hotkey] Global Ctrl+R registered — Scan All works without window focus")
            return True
        except Exception as e:
            log.warning("[Hotkey] Could not register global hotkey: %s", e)
            return False

    def _unregister_global_hotkey(self):
        if sys.platform != "win32":
            return
        try:
            import ctypes
            ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID_SCAN_ALL)
            log.debug("[Hotkey] Global Ctrl+R unregistered")
        except Exception as e:
            # Most common cause: it was never registered (toggle was already
            # off) — not an error, just log quietly.
            log.debug("[Hotkey] Unregister skipped/failed (likely already off): %s", e)

    def _on_global_scan_hotkey(self):
        """Called from the native event filter when WM_HOTKEY fires. Windows
        dispatches WM_HOTKEY through the same message pump Qt's event loop
        already processes, so this runs on the Qt main thread — safe to call
        backend slots directly, no cross-thread marshalling needed."""
        try:
            if hasattr(self, '_backend') and self._backend is not None:
                log.info("[Hotkey] Global Ctrl+R triggered — Scan All")
                self._backend.scan_comp()
        except Exception as e:
            log.warning("[Hotkey] Scan trigger from global hotkey failed: %s", e)

    def closeEvent(self, event):
        log.info("Closing MFlow")
        self._unregister_global_hotkey()
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
    app.setApplicationVersion("2.5.0")

    # ── Ícono en barra de tareas (Windows) ───────────────────────────────────
    # Sin AppUserModelID, Windows agrupa el exe bajo el ícono del launcher de
    # Python en lugar del de MFlow.
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "MFlow.MFlow.2.5.0"
        )
    app.setWindowIcon(QIcon(_resource("MFlow.ico")))

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
            resolve = None
            log.info("Resolve not found — running standalone")
    except Exception as e:
        log.warning("Resolve connection error: %s", e)
        resolve = None

    try:
        win = MFlowWindow(comp=comp, resolve=resolve)
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
