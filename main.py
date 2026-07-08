"""
MFlow — entry point.
Run: python main.py
"""
import sys, os, json, traceback, logging, faulthandler

# ── Multiprocessing child detection ──────────────────────────────────────────
# On Windows, the "spawn" start method (used by core.resolve_connection's
# probe_resolve_connection) always re-executes this file in the child
# process to rebuild enough of the namespace to unpickle the target
# function — this happens regardless of the if __name__=="__main__" guard
# further down, which only skips re-running main(), not this module's
# top-level statements.
#
# IMPORTANT: multiprocessing.parent_process() is NOT usable here — it's
# only populated by BaseProcess._bootstrap(), which runs AFTER
# multiprocessing.spawn.prepare() has already re-executed this file via
# runpy.run_path(main_path, run_name="__mp_main__"). At the point this
# module-level code runs in the child, parent_process() still reports None,
# so a check based on it silently never triggers — confirmed the hard way:
# every probe kept opening its own handle onto the shared mflow.log and
# crash.log (crash.log in "w" mode, truncating it) despite that earlier
# guard, because it always evaluated to "not a child" even inside a child.
#
# __name__ == "__mp_main__" is set synchronously by that same run_path()
# call, before a single line of this module executes — this is the
# officially correct signal for exactly this situation.
_IS_MP_CHILD = (__name__ == "__mp_main__")

# ── Faulthandler: catches C++ crashes (WebEngine, Resolve DLL) ───────────────
_LOG_DIR = os.path.join(os.path.expanduser("~"), ".mflow")
os.makedirs(_LOG_DIR, exist_ok=True)
_CRASH_LOG = os.path.join(_LOG_DIR, "crash.log")
if not _IS_MP_CHILD:
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

if _IS_MP_CHILD:
    # This is a probe worker, not the real app — it must never open its own
    # handle onto mflow.log (the parent process already owns that file, and
    # sharing it was the direct cause of the logging-corruption crash this
    # guard exists to prevent). Instead it gets its OWN file, keyed by PID,
    # so every diagnostic line survives somewhere on disk without any two
    # processes ever touching the same handle.
    _PROBE_LOG_PATH = os.path.join(_LOG_DIR, f"probe_{os.getpid()}.log")
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [PID:%(process)d] [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(_PROBE_LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
else:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [PID:%(process)d] [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(_LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ]
    )
log = logging.getLogger("mflow")
if not _IS_MP_CHILD:
    log.info("MFlow starting — Python %s — %s", sys.version.split()[0], sys.platform)
    # Diagnostic probe logs are per-PID and only meant to survive long enough
    # to be inspected after a repro — clear last session's before this one
    # writes new ones, so ~/.mflow doesn't grow unbounded over time.
    try:
        import glob
        for _old in glob.glob(os.path.join(_LOG_DIR, "probe_*.log")):
            try:
                os.remove(_old)
            except OSError:
                pass
    except Exception as _e:
        log.debug("Could not clean up old probe logs: %s", _e)

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
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
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


class _LoggedPage(QWebEnginePage):
    """QWebEnginePage subclass that forwards JS console.log/warn/error output
    to the Python logger so keyboard events and JS errors are visible in
    ~/.mflow/mflow.log without needing browser DevTools."""

    _JS_LEVELS = {0: log.info, 1: log.warning, 2: log.error, 3: log.debug}

    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        # PySide6 passes level as JavaScriptConsoleMessageLevel enum, not int.
        # Use .value to get 0=info, 1=warning, 2=error.
        fn = self._JS_LEVELS.get(level.value, log.debug)
        src = (source_id or '').split('/')[-1] or 'js'
        fn('[JS %s:%d] %s', src, line_number, message)


class _GlobalHotkeyFilter(QAbstractNativeEventFilter):
    """Catches WM_HOTKEY messages registered via user32.RegisterHotKey so
    global shortcuts work even when MFlow's window doesn't have OS
    focus. Windows-only — RegisterHotKey is never called on other platforms,
    so this filter simply never receives a matching message there and is a
    harmless no-op. Defensive on every line: a malformed/unexpected native
    message must never crash the app, only skip silently."""
    def __init__(self, hotkey_id, callback):
        super().__init__()
        self._hotkey_id = hotkey_id
        self._callback  = callback

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
    def _apply_native_titlebar_style(self):
        """
        Windows-only, purely cosmetic — makes the *native* titlebar dark to
        match MFlow's theme, and requests a Mica backdrop where the OS
        supports it. Fails silently everywhere else (older Windows 10, non-
        Windows) since neither of these is required for the app to work.

        Note on Mica specifically: it only shows through areas of the window
        that AREN'T covered by opaque content. Since the QWebEngineView fills
        the entire client area, the visible effect is limited to the thin
        native titlebar strip itself (where the system icon/min/max/close
        live) — it will NOT blur behind the app's own UI. That's an OS-level
        constraint (would need DwmExtendFrameIntoClientArea + a transparent
        margin to go further), not something worth chasing for a hidden strip.
        """
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            dwmapi = ctypes.windll.dwmapi
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20   # Win10 1809+ / Win11
            DWMWA_SYSTEMBACKDROP_TYPE     = 38   # Win11 22H2+ only
            DWMSBT_MAINWINDOW             = 2    # = Mica

            dark = ctypes.c_int(1)
            dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(dark), ctypes.sizeof(dark))

            backdrop = ctypes.c_int(DWMSBT_MAINWINDOW)
            dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), DWMWA_SYSTEMBACKDROP_TYPE,
                ctypes.byref(backdrop), ctypes.sizeof(backdrop))
        except Exception as e:
            log.debug("[Titlebar] DWM styling unavailable (older Windows?): %s", e)

    def _log_taskbar_style(self, context: str):
        """Reads the actual Win32 extended window style (GWL_EXSTYLE) and
        owner (GW_OWNER) and logs whether WS_EX_APPWINDOW (forces a taskbar
        entry) and WS_EX_TOOLWINDOW (hides from the taskbar) are set. This
        is ground truth from the OS itself — unlike Qt's own windowFlags(),
        which can go stale relative to reality (confirmed happening with
        the native SetWindowPos always-on-top path).

        IMPORTANT: EXSTYLE bits alone don't tell the whole story — a window
        with a non-null owner (GW_OWNER) is hidden from the taskbar by
        Windows regardless of EXSTYLE, unless WS_EX_APPWINDOW is explicitly
        set to override that. The first repro's data ruled out the EXSTYLE
        bits themselves (0x100/WS_EX_WINDOWEDGE, completely normal, never
        changed) — owner is the next most likely explanation and wasn't
        being checked at all before.
        """
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            GW_OWNER = 4
            WS_EX_APPWINDOW  = 0x00040000
            WS_EX_TOOLWINDOW = 0x00000080
            user32 = ctypes.windll.user32
            get_style = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
            get_style.restype = ctypes.c_longlong if hasattr(user32, "GetWindowLongPtrW") else ctypes.c_long
            style = get_style(hwnd, GWL_EXSTYLE)
            owner = user32.GetWindow(ctypes.c_void_p(hwnd), GW_OWNER)
            log.info("[Taskbar] %-28s hwnd=0x%x owner=0x%x  GWL_EXSTYLE=0x%x  "
                     "WS_EX_APPWINDOW=%s  WS_EX_TOOLWINDOW=%s",
                     context, hwnd, owner or 0, style & 0xFFFFFFFF,
                     bool(style & WS_EX_APPWINDOW), bool(style & WS_EX_TOOLWINDOW))
        except Exception as e:
            log.debug("[Taskbar] Could not read GWL_EXSTYLE/owner at '%s': %s", context, e)

    def showEvent(self, event):
        super().showEvent(event)
        self._log_taskbar_style("showEvent (fires every show, not just first)")
        if not getattr(self, "_titlebar_styled", False):
            self._titlebar_styled = True
            log.info("[AOT-PY] initial showEvent — windowFlags=%s", self.windowFlags())
            self._apply_native_titlebar_style()
            self._log_taskbar_style("after _apply_native_titlebar_style")
            # Also check a couple seconds later — some shell taskbar
            # registration happens asynchronously relative to window
            # creation, so a bit that looks fine at showEvent time could
            # still be altered shortly after by something else entirely.
            QTimer.singleShot(2000, lambda: self._log_taskbar_style("+2s after first show"))

    def changeEvent(self, event):
        super().changeEvent(event)
        try:
            from PySide6.QtCore import QEvent
            if event.type() == QEvent.Type.WindowStateChange:
                state = "minimized" if self.isMinimized() else (
                    "maximized" if self.isMaximized() else "normal")
                self._log_taskbar_style(f"changeEvent WindowStateChange -> {state}")
        except Exception as e:
            log.debug("[Taskbar] changeEvent logging failed: %s", e)

    def __init__(self, comp=None, fusion_app=None, resolve=None):
        super().__init__()
        self.setWindowTitle("MFlow")
        _ico_path = _resource("MFlow.ico")
        _ico_exists = os.path.isfile(_ico_path)
        _icon = QIcon(_ico_path)
        log.info("[Taskbar] MFlow.ico path=%s  exists_on_disk=%s  QIcon.isNull()=%s",
                 _ico_path, _ico_exists, _icon.isNull())
        self.setWindowIcon(_icon)
        if hasattr(QApplication, "instance") and QApplication.instance():
            QApplication.instance().setWindowIcon(_icon)
        # Native OS window frame (no FramelessWindowHint): gives us back
        # correct Snap/Aero, drop shadow, multi-monitor DPI handling, and
        # native resize/move — all of which were fighting with QWebEngineView
        # under a frameless window and were the main remaining flicker cause.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        # WA_NoSystemBackground: stops the OS from painting the widget background
        # before Qt does — eliminates the white/black flash between frames on Windows.
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        # WA_OpaquePaintEvent: tells Qt this widget paints every pixel itself,
        # removing the implicit background erase that can cause a visible
        # flicker on resize and focus changes.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.resize(940, 580)
        self._hotkey_filter = None   # kept alive here — installNativeEventFilter
                                      # does not hold a strong ref in PySide6

        self._view = QWebEngineView()
        # _LoggedPage forwards JS console output to the Python log
        self._view.setPage(_LoggedPage(self._view))
        # Suppress background erase on the view — same flicker fix as the window.
        self._view.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._view.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setCentralWidget(self._view)
        # Eliminates white flash before CSS loads — must be set before loadUrl()
        self._view.page().setBackgroundColor(QColor("#121217"))

        # Disable the built-in Ctrl+R → Reload shortcut at the Qt level so the
        # JS keydown listener receives the event instead of the browser eating it.
        for _act in (QWebEnginePage.WebAction.Reload,
                     QWebEnginePage.WebAction.ReloadAndBypassCache):
            self._view.page().action(_act).setEnabled(False)

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

        # ── Boot-theme injection (eliminates startup theme flash) ──────────────
        # app.html's :root{} block paints default colors immediately on load;
        # the real saved theme only used to arrive later via the JS<->Python
        # settings round-trip, causing a visible flash of default colors on
        # every launch. Resolving the theme here and injecting it as a plain
        # JS global (same DocumentCreation technique as qwebchannel.js above)
        # lets app.html's own first-body-script apply it before first paint —
        # see the inline <script> right after <body> in app.html.
        try:
            self._apply_boot_theme_injection()
        except Exception as _e:
            log.warning("[Theme] Boot-theme injection skipped: %s", _e)

        if not os.path.isfile(APP_HTML):
            log.error("app.html not found at: %s", APP_HTML)
            raise FileNotFoundError(f"app.html missing: {APP_HTML}")

        self._view.load(QUrl.fromLocalFile(APP_HTML))
        self._view.loadFinished.connect(self._on_page_ready)
        log.info("Window created, loading UI...")

    def _apply_boot_theme_injection(self):
        """Reads the saved theme name from settings.json, resolves it to its
        JSON file (same lookup order as Backend.load_theme: user themes/
        folder first, then the bundled one), and injects it as
        window.__MFLOW_BOOT_THEME__ before the page loads. Deliberately
        defensive at every step — a missing/corrupt settings file, a theme
        name that no longer resolves to any file, or bad JSON must never
        stop the app from launching. Worst case: no injection happens and
        the page just falls back to its normal (slightly-delayed) theme
        load, exactly like before this fix existed."""
        from core.platform_config import settings_file, themes_dir, bundled_themes_dir
        theme_name = ""
        try:
            with open(settings_file(), encoding="utf-8") as f:
                theme_name = (json.load(f).get("theme") or "").strip()
        except Exception:
            pass
        if not theme_name:
            return  # Default theme — nothing to inject, page's own :root{} is already correct
        data = None
        for tdir in (themes_dir(), bundled_themes_dir()):
            for candidate in (theme_name + ".json", theme_name):
                path = os.path.join(tdir, candidate)
                if os.path.isfile(path):
                    try:
                        with open(path, encoding="utf-8") as f:
                            data = json.load(f)
                        break
                    except Exception as e:
                        log.debug("[Theme] Could not read %s: %s", path, e)
            if data is not None:
                break
        if not isinstance(data, dict):
            log.debug("[Theme] Boot theme %r not found on disk — skipping injection", theme_name)
            return
        from PySide6.QtWebEngineCore import QWebEngineScript
        js = "window.__MFLOW_BOOT_THEME__ = " + json.dumps(data) + ";"
        script = QWebEngineScript()
        script.setName("__mflow_boot_theme__")
        script.setSourceCode(js)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        self._view.page().scripts().insert(script)
        log.info("[Theme] Boot theme %r injected for flash-free startup", theme_name)

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
            MOD_CONTROL  = 0x0002
            MOD_NOREPEAT = 0x4000
            VK_R = 0x52
            ok = ctypes.windll.user32.RegisterHotKey(
                None, HOTKEY_ID_SCAN_ALL, MOD_CONTROL | MOD_NOREPEAT, VK_R)
            if not ok:
                err = ctypes.windll.kernel32.GetLastError()
                log.warning("[Hotkey] RegisterHotKey failed (Win32 error %d) — "
                            "Ctrl+R may already be bound by another app", err)
                return False
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
        """Every step here is independently try/excepted, and the window is
        ALWAYS allowed to close at the end regardless of what happened above
        — this used to be a bare sequence of calls with no exception
        handling at all, so a single failure partway through (e.g. the
        comp watcher's .stop() raising because the underlying comp
        reference had gone stale after Resolve closed) would escape
        closeEvent entirely and could leave the native close button looking
        like it does nothing. Closing must never be blockable by an
        internal error."""
        log.info("[Close-PY] closeEvent entered — native close signal received by Qt")
        log.info("Closing MFlow")
        try:
            self._unregister_global_hotkey()
        except Exception as e:
            log.warning("[Close-PY] _unregister_global_hotkey failed (ignored): %s", e)
        try:
            if hasattr(self, '_backend') and self._backend is not None and self._backend._watcher:
                self._backend._watcher.stop()
        except Exception as e:
            log.warning("[Close-PY] watcher.stop() failed (ignored): %s", e)
        try:
            super().closeEvent(event)
        except Exception as e:
            log.warning("[Close-PY] super().closeEvent() raised (ignored, forcing accept): %s", e)
        finally:
            # Belt-and-suspenders: guarantee the close is accepted even if
            # something above threw before event.accept() would normally
            # have been called by the base implementation.
            try:
                if not event.isAccepted():
                    event.accept()
            except Exception:
                pass
        log.info("[Close-PY] closeEvent finished — event.isAccepted()=%s", event.isAccepted())


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

    # Windows groups unpackaged Python apps under the python.exe taskbar icon
    # unless we give the process its own AppUserModelID — must be set before
    # QApplication() creates the native window, or it has no effect. This is
    # deliberately the ONLY call to this API in the app — a second, later
    # call used to exist right after QApplication() was constructed, which
    # is already too late per the constraint above and just overwrote this
    # one with a different (equally ineffective) ID string. Removed as dead,
    # confusing leftover code.
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MFlow.MFlow.2.5.0")
        except Exception as e:
            log.debug("[Taskbar] Could not set AppUserModelID: %s", e)

    app = QApplication(sys.argv)
    app.setApplicationName("MFlow")
    app.setApplicationVersion("2.5.0")
    app.setWindowIcon(QIcon(_resource("MFlow.ico")))

    comp = None
    try:
        from core.resolve_connection import (probe_resolve_connection,
                                              get_resolve_with_timeout, get_comp_with_timeout)
        from core.platform_config import settings_file
        custom = ""
        try:
            with open(settings_file(), encoding="utf-8") as f:
                custom = json.load(f).get("dvr_path", "")
        except Exception:
            pass
        # Two layers of defense against a hung Resolve scripting bridge:
        #  1. probe_resolve_connection() tests the waters in a genuinely
        #     separate OS process first — if IT hangs, it gets forcibly
        #     killed, which is guaranteed to work regardless of what's
        #     stuck inside (unlike a thread timeout — see that function's
        #     docstring for why a thread-based guard alone isn't enough).
        #  2. Only once the probe confirms Resolve is currently responsive
        #     do we attempt the real connection, still under the
        #     thread-based timeout as a secondary safety net for the small
        #     window between the probe and this call.
        resolve = None
        if probe_resolve_connection(custom, timeout=6.0):
            resolve = get_resolve_with_timeout(custom, timeout=6.0)
        if resolve:
            comp = get_comp_with_timeout(resolve, timeout=4.0)
            log.info("Connected to Resolve")
        else:
            resolve = None
            log.info("Resolve not found or unresponsive — running standalone")
    except Exception as e:
        log.warning("Resolve connection error: %s", e)
        resolve = None

    try:
        win = MFlowWindow(comp=comp, resolve=resolve)
        win.show()

        def _on_app_state_changed(state):
            # ApplicationActive = MFlow is the focused window; anything else
            # (Inactive/Suspended/Hidden) means focus moved elsewhere — most
            # commonly the user working in Resolve's own viewport. Wrapped
            # in try/except since this fires often and must never be able
            # to take the app down.
            try:
                active = (state == Qt.ApplicationState.ApplicationActive)
                if hasattr(win, "_backend") and win._backend is not None:
                    win._backend.set_window_focused(active)
            except Exception as e:
                log.debug("[Focus] applicationStateChanged handler failed: %s", e)

        app.applicationStateChanged.connect(_on_app_state_changed)

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
    # REQUIRED for multiprocessing (used by core.resolve_connection's
    # probe_resolve_connection) to work correctly once this is packaged as
    # a PyInstaller executable. Without this, a frozen exe spawning a new
    # "spawn"-context process can re-execute the entire app from the top in
    # the child instead of just running the probe worker — the same class
    # of fork-bomb bug already hit and fixed once before in MPaste. Must be
    # the very first thing that runs, before any other code.
    import multiprocessing
    multiprocessing.freeze_support()
    main()
