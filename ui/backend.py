"""
Backend — QObject exposed to JavaScript via QWebChannel.
All Resolve API calls happen here. UI logic stays in app.html.
"""
import json, os, sys
from PySide6.QtCore import QObject, Slot, Signal, QTimer, QRunnable, QThreadPool
from PySide6.QtWidgets import QFileDialog, QApplication

from core.preset_manager  import (load_profiles, save_profiles, add_preset,
                                   delete_preset, new_profile, delete_profile,
                                   switch_profile, load_builtin, active_presets)
import logging
log = logging.getLogger("mflow")
from core.platform_config import settings_file, themes_dir, bundled_themes_dir, language_dir
from core.curve_engine    import (apply_bezier, apply_baked, apply_steps,
                                   apply_overframe, bake_oscillator,
                                   bake_elastic_penner, OverframePoint)


def _rj(path):
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except Exception: return {}

def _wj(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=2)
    except Exception: pass


class Backend(QObject):
    # ── Python → JavaScript signals ───────────────────────────────────────────
    presets_updated    = Signal(str)   # JSON list
    profiles_updated   = Signal(str)   # JSON {names, active}
    tool_updated       = Signal(str)   # JSON {name, inputs: {id: {label, kf_count}}}
    comp_scan_updated  = Signal(str)   # JSON {tool_name: {inp_id: {label, kf_count}}}
    connection_changed = Signal(bool, str)   # connected, detail text
    status_changed     = Signal(str, str)    # message, hex color
    apply_done         = Signal(bool, str)   # success, message
    settings_signal    = Signal(str)         # JSON settings dict
    pythons_scanned    = Signal(str)         # JSON {pythons, active, versions} — async result
    themes_updated     = Signal(str)         # JSON [{name, filename}] — themes/ folder listing
    load_theme_result  = Signal(str)         # JSON theme object
    comp_list_updated  = Signal(str)         # JSON [{id, name, active}]
    spline_copied      = Signal(str)         # removed — kept stub for compat
    _apply_comp_sig    = Signal(object)      # internal: thread-safe cross-thread comp delivery

    def __init__(self, window, comp=None, fusion_app=None, resolve=None, parent=None):
        super().__init__(parent)
        self._fusion_app = fusion_app
        self._win      = window
        self._comp     = comp
        self._resolve  = resolve  # stored from startup or reconnect
        self._fu       = None    # cached Fusion scripting object
        # Cache _fu immediately if resolve is available at startup
        if resolve:
            try:
                fu = resolve.Fusion()
                if fu:
                    self._fu = fu
                    log.info("[Init] Fusion object cached from startup resolve")
            except Exception as e:
                log.debug("[Init] Could not get Fusion at startup: %s", e)
        self._watcher  = None
        self._profiles = load_profiles()
        self._settings = _rj(settings_file())
        self._mode     = "easing"
        self._phys_zeta    = 0.3
        self._phys_omega_n = 8.0
        self._el_amplitude = 1.0
        self._el_period    = 0.3
        self._auto_apply = False
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(lambda: self._do_apply(False))
        self._h1       = [0.42, 0.0]
        self._h2       = [0.58, 1.0]
        self._of_points = []          # list of dicts from JS
        self._sel_inp  = None         # (tool_name, inp_id)
        self._sel_tools = {}          # {tool_name: {inp_id: meta}} — comp scan selection
        self._kf_from  = 1           # 1-based start keyframe index (1 = first)
        self._kf_to    = 0           # 1-based end keyframe index (0 = last)
        self._spline_clipboard = None  # {tool, input, keyframes}
        self._auto_comp = True        # auto-follow active Fusion comp
        self._switching_comp = False   # guard against re-entrant comp switches
        self._fps      = float(self._settings.get("bake_fps", 24))
        self._python_scan_cache = None  # cached result of scan_pythons()
        self._python_scan_time  = 0.0   # epoch when cache was last filled
        # Thread-safe delivery: worker threads emit this to invoke _apply_new_comp
        # on the main thread via Qt's automatic queued-connection mechanism.
        self._apply_comp_sig.connect(self._apply_new_comp)

        # Start watcher if we already have a comp
        if comp:
            self._start_watcher()
            QTimer.singleShot(200, self._announce_connection)

    # ── Window control ────────────────────────────────────────────────────────

    @Slot()
    def js_ready(self):
        """Called by JS once QWebChannel is fully initialised. Replaces the
        old 600 ms blind timer — connection is announced exactly when JS can
        handle it."""
        self._js_ready = True
        self._announce_connection()
        # Also push presets & profiles so the UI is fully populated immediately
        self.load_library(self._mode)
        self._emit_profiles()
        # Push saved settings so JS restores theme/auto-apply/etc on startup
        self.settings_signal.emit(json.dumps(self._settings))

    @Slot(float)
    def set_zoom_factor(self, factor: float):
        """Scale the entire WebEngine view using Qt's native zoom.
        Qt remaps mouse coordinates automatically — no resize_window needed."""
        try:
            view = getattr(self._win, '_view', None)
            if view:
                view.setZoomFactor(max(0.5, min(2.5, float(factor))))
        except Exception:
            pass

    @Slot()
    def start_system_move(self):
        try: self._win.windowHandle().startSystemMove()
        except Exception: pass

    @Slot(str, result=str)
    def get_dock_html(self, panel_id: str) -> str:
        """Return styled HTML snippet for the requested panel."""
        label = {'left': 'Presets', 'right': 'Preview / Params', 'curve': 'Curve Editor'}.get(panel_id, panel_id)
        return (
            f'<div style="padding:20px;color:#908caa;font-family:Monaspace,monospace;font-size:7pt;line-height:1.8">'
            f'<div style="color:#9ccfd8;font-weight:700;font-size:8pt;margin-bottom:8px">{label}</div>'
            f'Panel externo conectado al mismo backend.<br>'
            f'El contenido nativo de este panel (presets, preview, etc.)<br>'
            f'se integrará en una próxima versión.<br><br>'
            f'<span style="color:#6e6a86">El backend está compartido — Apply y toda la lógica funcionan desde aquí.</span>'
            f'</div>'
        )

    @Slot(str, str)
    def open_external_dock(self, panel_id: str, title: str):
        """Open a panel in a separate PySide6 window loading dock.html."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebEngineCore import QWebEngineSettings
        from PySide6.QtWebChannel import QWebChannel
        from PySide6.QtCore import QUrl, Qt
        import os

        if not hasattr(self, '_dock_windows'):
            self._dock_windows = {}

        # If already open, bring to front
        existing = self._dock_windows.get(panel_id)
        if existing and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return

        dlg = QDialog(None)  # None parent = truly independent window
        dlg.setWindowTitle(f"MFlow — {title}")
        dlg.resize(400, 500)
        dlg.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint
        )

        view = QWebEngineView(dlg)
        s = view.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

        channel = QWebChannel(view.page())
        channel.registerObject("backend", self)
        view.page().setWebChannel(channel)

        dock_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.html")
        url = QUrl.fromLocalFile(dock_path)
        url.setQuery(f"dock={panel_id}")
        view.load(url)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(view)

        dlg.show()
        self._dock_windows[panel_id] = dlg

    @Slot()
    def toggle_maximize(self):
        if self._win.isMaximized():
            self._win.showNormal()
        else:
            self._win.showMaximized()

    @Slot()
    def minimize_window(self):
        self._win.showMinimized()

    @Slot()
    def close_window(self):
        self._win.close()

    # ── Resolve connection ────────────────────────────────────────────────────

    def set_comp(self, comp):
        self._comp = comp
        # Try to populate _fu from _resolve if not already cached
        if self._fu is None and self._resolve:
            try:
                fu = self._resolve.Fusion()
                if fu:
                    self._fu = fu
                    log.info("[Connect] _fu populated from _resolve in set_comp")
            except Exception as e:
                log.debug("[Connect] Could not get Fusion from _resolve in set_comp: %s", e)
        if self._watcher:
            self._watcher.stop()
            self._watcher = None
        self._start_watcher()
        self._announce_connection()

    @Slot(str)
    def reconnect(self, custom_path=""):
        # Emit immediately so the UI shows "Connecting…" right away
        self.connection_changed.emit(False, "Connecting\u2026")
        try:
            s = json.loads(self.get_settings())
            cp = custom_path.strip() or s.get("dvr_path", "")
        except Exception:
            cp = custom_path.strip()

        # Run get_resolve() on a thread-pool worker so the Qt main thread (and
        # the UI) stays responsive during the IPC call (which can take 2-5 s).
        _self = self

        class _ConnectWorker(QRunnable):
            def run(self):
                import time
                try:
                    from core.resolve_connection import get_resolve, get_comp as _gc
                    log.info("[Connect] Starting connection attempt…")
                    log.info("[Connect] Module search path: %s", cp or "(auto)")

                    resolve = None
                    for attempt in range(3):
                        if attempt > 0:
                            log.info("[Connect] Retry %d/3 — waiting 2s…", attempt + 1)
                            time.sleep(2)
                        resolve = get_resolve(cp)
                        if resolve:
                            break
                        log.warning("[Connect] Attempt %d failed — resolve=None", attempt + 1)

                    if resolve:
                        log.info("[Connect] Resolve object obtained successfully")
                        _self._resolve = resolve
                        try:
                            _self._fu = resolve.Fusion()
                            log.info("[Connect] Fusion object cached: %s",
                                     "OK" if _self._fu else "None — Fusion page may not be active")
                        except Exception as e:
                            log.warning("[Connect] Could not cache Fusion object: %s", e)
                            _self._fu = None
                        log.info("[Connect] Getting active Fusion comp…")
                        comp = _gc(resolve)
                        if comp:
                            log.info("[Connect] Comp found, name='%s'",
                                     _self._get_comp_name(comp))
                        else:
                            log.warning("[Connect] No active Fusion comp — "
                                        "open a comp on the Fusion page in DaVinci Resolve")
                        # Emit via _apply_comp_sig: Qt auto-queues this onto the
                        # main-thread event loop (QTimer.singleShot from a
                        # QRunnable thread has no event loop and silently drops).
                        _self._apply_comp_sig.emit(comp)
                    else:
                        log.warning("[Connect] All attempts failed. "
                                    "Ensure DaVinci Resolve is open and:\n"
                                    "  Preferences > System > General > "
                                    "External scripting using = Local")
                        _self.connection_changed.emit(
                            False,
                            "Not connected \u2014 open Resolve and set "
                            "Preferences > General > External scripting: Local")
                except Exception as exc:
                    log.error("[Connect] Exception: %s", exc, exc_info=True)
                    _self.connection_changed.emit(False, f"Connect error: {exc}")

        QThreadPool.globalInstance().start(_ConnectWorker())

    def _apply_new_comp(self, comp):
        """Called on the Qt main thread after a background reconnect succeeds."""
        if comp:
            log.info("[Connect] Applying comp to watcher")
            self.set_comp(comp)
        else:
            log.warning("[Connect] No comp available — Fusion page may not be active")
            self.connection_changed.emit(
                False,
                "Resolve found but no active Fusion comp \u2014 "
                "open a composition or switch to the Fusion page")

    def _announce_connection(self):
        if self._comp:
            try:
                comp_name = self._get_comp_name(self._comp)
                log.info("[Announce] Comp name resolved: '%s'", comp_name)
                edition = "Resolve"
                ver_str = ""
                try:
                    fu = (self._comp.GetFusion() if callable(getattr(self._comp, "GetFusion", None))
                          else getattr(self._comp, "Fusion", None))
                    if fu:
                        # Version number
                        v = getattr(fu, "Version", None)
                        if callable(v): v = v()
                        if isinstance(v, dict):
                            maj = v.get("VersionMajor") or v.get("Major", "")
                            ver_str = f"v{maj}" if maj else ""
                        elif v:
                            ver_str = f"v{str(v)[:4]}"
                        # Studio detection: IsRegistered exists and returns True only in Studio
                        is_reg = getattr(fu, "IsRegistered", None)
                        if callable(is_reg) and is_reg():
                            edition = "Studio"
                        # Fallback: try accessing Resolve object — only works in Studio
                        elif hasattr(fu, "GetResolve"):
                            try:
                                r = fu.GetResolve()
                                if r: edition = "Studio"
                            except Exception:
                                pass
                except Exception:
                    pass
                label = f"Connected · DaVinci {edition}"
                if ver_str: label += f" {ver_str}"
                self.connection_changed.emit(True, label)
            except Exception:
                self.connection_changed.emit(True, "Connected")
        else:
            self.connection_changed.emit(False, "Not connected")

    @Slot(int, int)
    def resize_window(self, w: int, h: int):
        self._win.resize(w, h)

    @Slot(str)
    def start_system_resize(self, edge: str):
        from PySide6.QtCore import Qt
        E = Qt.Edge
        edges = {
            'right':  E.RightEdge,
            'left':   E.LeftEdge,
            'top':    E.TopEdge,
            'bottom': E.BottomEdge,
            'br': E.RightEdge  | E.BottomEdge,
            'bl': E.LeftEdge   | E.BottomEdge,
            'tr': E.RightEdge  | E.TopEdge,
            'tl': E.LeftEdge   | E.TopEdge,
        }.get(edge, E.RightEdge | E.BottomEdge)
        try:
            self._win.windowHandle().startSystemResize(edges)
        except Exception:
            pass

    @Slot(bool)
    def set_always_on_top(self, enabled: bool):
        from PySide6.QtCore import Qt
        flag = Qt.WindowType.WindowStaysOnTopHint
        # Main window
        flags = self._win.windowFlags()
        if enabled: flags |= flag
        else: flags &= ~flag
        self._win.setWindowFlags(flags)
        self._win.show()
        # All dock windows
        for dlg in getattr(self, '_dock_windows', {}).values():
            if dlg and dlg.isVisible():
                f = dlg.windowFlags()
                if enabled: f |= flag
                else: f &= ~flag
                dlg.setWindowFlags(f)
                dlg.show()

    @Slot(bool)
    def set_auto_apply(self, enabled: bool):
        self._auto_apply = enabled
        if not enabled:
            self._auto_timer.stop()

    @Slot(result=str)
    def get_debug_info(self) -> str:
        import platform as _pl, sys as _sys
        lines = []
        lines.append(f"=== MFlow Debug ===")
        lines.append(f"Python:    {_sys.version}")
        lines.append(f"Platform:  {_pl.platform()}")
        lines.append(f"Mode:      {self._mode}  zeta={self._phys_zeta:.3f}  omega={self._phys_omega_n:.2f}")
        lines.append(f"Connected: {self._comp is not None}  watcher={bool(self._watcher and self._watcher._timer.isActive())}")

        if self._comp:
            try:
                ca = self._comp.GetAttrs()
                lines.append(f"Comp:      {ca.get('COMPS_Name','?')}  fps={ca.get('COMPN_FPS','?')}  frame={ca.get('COMPN_CurrentTime','?')}")
            except Exception as e:
                lines.append(f"Comp:      error reading attrs ({e})")

            tool = None
            try:
                tool = self._comp.ActiveTool
                if tool:
                    ta = tool.GetAttrs()
                    lines.append(f"ActiveTool: {ta.get('TOOLS_Name','?')} ({ta.get('TOOLS_RegID','?')})")
                else:
                    lines.append("ActiveTool: None")
            except Exception as e:
                lines.append(f"ActiveTool: error ({e})")

            if tool:
                lines.append("--- Inputs ---")
                try:
                    for inp in (tool.GetInputList() or {}).values():
                        try:
                            ia = inp.GetAttrs()
                            iid = ia.get("INPS_ID", "?")
                            if not iid or iid == "?":
                                continue
                            # Try GetKeyFrames on input directly
                            kf_count = "?"
                            kf_range = "?"
                            obj_used = "inp"
                            try:
                                sd = inp.GetKeyFrames()
                                if isinstance(sd, dict):
                                    kf_count = len(sd)
                                    if kf_count >= 2:
                                        times = sorted(sd.keys(), key=float)
                                        kf_range = f"{float(times[0]):.0f}→{float(times[-1]):.0f}"
                            except Exception:
                                pass
                            # Try connected tool if input returned nothing
                            if kf_count in ("?", 0, 1):
                                try:
                                    out = inp.GetConnectedOutput()
                                    if out:
                                        ct = out.GetTool()
                                        if ct:
                                            sd2 = ct.GetKeyFrames()
                                            if isinstance(sd2, dict):
                                                kf_count = len(sd2)
                                                obj_used = f"tool({ct.GetAttrs().get('TOOLS_RegID','?')})"
                                                if kf_count >= 2:
                                                    times = sorted(sd2.keys(), key=float)
                                                    kf_range = f"{float(times[0]):.0f}→{float(times[-1]):.0f}"
                                except Exception:
                                    pass
                            lines.append(f"  {iid}: kf={kf_count} range={kf_range} via={obj_used}")
                        except Exception as e:
                            lines.append(f"  (input error: {e})")
                except Exception as e:
                    lines.append(f"  GetInputList error: {e}")

        return "\n".join(lines)

    def _start_watcher(self):
        if self._comp is None:
            log.warning("[Watcher] Cannot start — comp is None")
            return
        from core.resolve_connection import ResolveWatcher
        log.info("[Watcher] Starting watcher on comp")
        self._watcher = ResolveWatcher(self._comp, fu=self._fu, parent=self)
        self._watcher.tool_changed.connect(self._on_tool_changed)
        self._watcher.disconnected.connect(self._on_disconnected)
        self._watcher.comp_scan_updated.connect(self._on_comp_scan)
        self._watcher.comp_changed.connect(self._on_watcher_comp_changed)
        self._watcher.start()
        # Auto-scan on every fresh watcher: startup, reconnect, and auto-follow.
        QTimer.singleShot(600, self.scan_comp)

    def _on_watcher_comp_changed(self):
        """Watcher's _comp_check (fingerprint) confirmed the user switched comps."""
        if not self._auto_comp or self._switching_comp:
            return
        fu = self._get_fusion()
        if not fu:
            return
        try:
            current = fu.GetCurrentComp()
            if not current:
                return
            log.info("[AutoComp] Watcher detected comp switch — following")
            self._do_switch_comp(fu, current)
        except Exception as e:
            log.debug("[AutoComp] comp-change handling failed: %s", e)

    def _on_tool_changed(self, name, inputs):
        if name:
            log.debug("[Watcher] Active tool: '%s' (%d animated inputs)", name, len(inputs))
        # Comp-change detection handled by watcher's _comp_check (1500 ms, fingerprint-based).
        # Removed inline _comps_match here — it called GetToolList twice per 500 ms poll.
        payload = {
            "name": name,
            "inputs": {
                k: {"label": v["label"], "kf_count": v["kf_count"]}
                for k, v in inputs.items()
            }
        }
        self.tool_updated.emit(json.dumps(payload))

    def _on_disconnected(self):
        log.warning("[Watcher] Connection lost after repeated poll failures")
        self._fu = None
        self.connection_changed.emit(False, "Disconnected — click Connect")

    def _on_comp_scan(self, scan_result: dict):
        """Forward comp-wide scan result to JS as JSON."""
        log.info("[Scan] Comp scan complete: %d tools with keyframes", len(scan_result))
        for tool_name, inputs in scan_result.items():
            log.debug("[Scan]   %s: %d input(s)", tool_name, len(inputs))
        self._last_comp_scan = scan_result
        payload = {}
        for tool_name, inputs in scan_result.items():
            payload[tool_name] = {
                k: {"label": v["label"], "kf_count": v["kf_count"]}
                for k, v in inputs.items()
            }
        self.comp_scan_updated.emit(json.dumps(payload))

    @Slot()
    def scan_comp(self):
        """Trigger a full comp scan. Result arrives via comp_scan_updated signal."""
        if self._watcher is None:
            log.warning("[Scan] scan_comp called but watcher is None — not connected")
            self.status_changed.emit("Not connected", "#eb6f92")
            return
        log.info("[Scan] Manual scan triggered")
        self.status_changed.emit("Scanning composition…", "var(--muted)")
        self._watcher.scan_all_tools()

    # ── Fusion / comp helpers ─────────────────────────────────────────────────

    def _get_fusion(self):
        """Return the Fusion scripting object, trying all known paths."""
        # 0. Cached from startup or previous connect
        if self._fu:
            try:
                _ = self._fu.GetCurrentComp  # liveness check
                return self._fu
            except Exception:
                self._fu = None
        # 1. Via stored resolve
        if self._resolve:
            try:
                fu = self._resolve.Fusion()
                if fu:
                    self._fu = fu
                    return fu
            except Exception as e:
                log.debug("[Fusion] _resolve.Fusion() raised: %s", e)
        # 2. Via comp object
        if self._comp:
            try:
                fn = getattr(self._comp, "GetFusion", None)
                fu = fn() if callable(fn) else None
                if fu:
                    self._fu = fu
                    return fu
                else:
                    log.debug("[Fusion] comp.GetFusion() returned None")
            except Exception as e:
                log.debug("[Fusion] comp.GetFusion() raised: %s", e)
        # 3. bmd.scriptapp fallback (only available inside Fusion process)
        try:
            import bmd  # type: ignore
            fu = bmd.scriptapp("Fusion")
            if fu:
                self._fu = fu
                return fu
        except Exception as e:
            log.debug("[Fusion] bmd.scriptapp('Fusion') raised: %s", e)
        log.warning("[Fusion] All paths to Fusion object failed")
        return None

    def _get_comp_name(self, comp) -> str:
        """
        Return a human-readable name for a comp object.
        Strategy:
        1. Try GetAttrs single-key form (COMPS_FileName)
        2. Scan timeline clips — find which clip owns this comp, return clip name
        3. Fall back to project/timeline name
        """
        if comp is None:
            return ""

        # 1. Direct attribute — works on Fusion standalone
        try:
            v = comp.GetAttrs("COMPS_FileName")
            if v and isinstance(v, str) and v.strip():
                import os as _os
                return _os.path.splitext(_os.path.basename(v.strip()))[0]
        except Exception:
            pass
        try:
            attrs = comp.GetAttrs()
            if isinstance(attrs, dict):
                for key in ("COMPS_FileName", "COMPS_Name", "CompName"):
                    v = attrs.get(key)
                    if v and isinstance(v, str) and v.strip():
                        return v.strip()
        except Exception:
            pass

        # 2. Scan timeline — find clip that owns this comp
        if self._resolve:
            try:
                proj = self._resolve.GetProjectManager().GetCurrentProject()
                if proj:
                    tl = proj.GetCurrentTimeline()
                    if tl:
                        track_count = tl.GetTrackCount("video")
                        for t in range(1, track_count + 1):
                            items = tl.GetItemListInTrack("video", t) or []
                            for item in items:
                                try:
                                    if item.GetFusionCompCount() == 0:
                                        continue
                                    clip_comp = item.GetFusionCompByIndex(1)
                                    if clip_comp is None:
                                        continue
                                    # Compare by checking if they have the same keyframes/tools
                                    # (object identity doesn't work across IPC)
                                    if self._comps_match(comp, clip_comp):
                                        name = item.GetName()
                                        if name:
                                            return name
                                except Exception:
                                    continue
            except Exception as e:
                log.debug("[get_comp_name] Timeline scan failed: %s", e)

        # 3. Timeline name as last resort
        if self._resolve:
            try:
                proj = self._resolve.GetProjectManager().GetCurrentProject()
                if proj:
                    tl = proj.GetCurrentTimeline()
                    if tl:
                        return tl.GetName()
                    return proj.GetName()
            except Exception:
                pass

        return "Composition"

    def _comps_match(self, comp_a, comp_b) -> bool:
        """
        Compare two comp objects by their tool names — since object identity
        doesn't work across IPC boundaries in DaVinci.
        """
        try:
            def _tool_names(c):
                tools = c.GetToolList(False)
                if not tools:
                    return frozenset()
                return frozenset(t.Name for _, t in tools.items())
            return _tool_names(comp_a) == _tool_names(comp_b)
        except Exception:
            return False

    # ── Comp listing ──────────────────────────────────────────────────────────

    @Slot(bool)
    def list_comps(self, auto_mode: bool = True):
        """
        Emit comp_list_updated.
        auto_mode=True:  report current comp name only — NO switching (avoids feedback loop).
        auto_mode=False: list all Fusion comps in memory for manual selection.
        """
        fu = self._get_fusion()
        if fu is None:
            log.warning("[list_comps] No Fusion object available — cannot list compositions")
            self.comp_list_updated.emit(json.dumps([]))
            return
        try:
            if auto_mode:
                current = fu.GetCurrentComp()
                if current:
                    name = self._get_comp_name(current) or "Active Composition"
                    log.debug("[list_comps] Auto: active = '%s'", name)
                    self.comp_list_updated.emit(json.dumps([
                        {"id": "current", "name": name, "active": True}
                    ]))
                else:
                    self.comp_list_updated.emit(json.dumps([]))
                return
            # Manual mode — scan timeline clips for real clip names
            log.info("[list_comps] Manual mode — scanning timeline + GetCompList")
            comps = []
            seen_fps = set()  # deduplicate by tool-name fingerprint

            # fingerprint of currently active comp for marking active
            active_fp = None
            if self._comp:
                try:
                    t2 = self._comp.GetToolList(False)
                    if t2: active_fp = frozenset(x.Name for _, x in t2.items())
                except Exception: pass

            # 1. Timeline clips — preferred (have real clip names)
            if self._resolve:
                try:
                    proj = self._resolve.GetProjectManager().GetCurrentProject()
                    tl   = proj.GetCurrentTimeline() if proj else None
                    if tl:
                        track_count = tl.GetTrackCount("video")
                        for tr in range(1, track_count + 1):
                            for ii, item in enumerate(tl.GetItemListInTrack("video", tr) or []):
                                try:
                                    if item.GetFusionCompCount() == 0: continue
                                    cc = item.GetFusionCompByIndex(1)
                                    if cc is None: continue
                                    tt = cc.GetToolList(False)
                                    tids = {x.ID for _, x in (tt or {}).items()}
                                    if tids == {"AudioDisplay","MediaIn","MediaOut"}: continue
                                    fp = frozenset(x.Name for _, x in (tt or {}).items())
                                    if fp in seen_fps: continue
                                    seen_fps.add(fp)
                                    name = item.GetName() or f"Clip {ii+1}"
                                    comps.append({"id": f"clip:{tr}:{ii}",
                                                  "name": name,
                                                  "active": fp == active_fp})
                                    log.debug("[list_comps] clip '%s' active=%s", name, fp==active_fp)
                                except Exception as e:
                                    log.debug("[list_comps] clip err: %s", e)
                except Exception as e:
                    log.debug("[list_comps] timeline scan err: %s", e)

            # 2. GetCompList for Fusion Effects / standalone comps not on clips
            raw = fu.GetCompList()
            log.info("[list_comps] GetCompList: %d entries", len(raw) if raw else 0)
            if raw:
                for k, c in raw.items():
                    try:
                        tt = c.GetToolList(False)
                        tids = {x.ID for _, x in (tt or {}).items()}
                        if tids == {"AudioDisplay","MediaIn","MediaOut"}: continue
                        fp = frozenset(x.Name for _, x in (tt or {}).items())
                        if fp in seen_fps: continue
                        seen_fps.add(fp)
                        comps.append({"id": str(k),
                                      "name": f"Fusion Effect {k}",
                                      "active": fp == active_fp})
                    except Exception as e:
                        log.debug("[list_comps] effect err %s: %s", k, e)

            if not comps:
                self.comp_list_updated.emit(json.dumps([])); return

            comps.sort(key=lambda c: (0 if c["active"] else 1, c["name"].lower()))
            self.comp_list_updated.emit(json.dumps(comps))

        except Exception as e:
            log.error("[list_comps] Error: %s", e, exc_info=True)
            self.comp_list_updated.emit(json.dumps([]))

    @Slot(str)
    def set_active_comp(self, comp_id: str):
        """Switch MFlow to a different composition."""
        fu = self._get_fusion()
        if fu is None:
            self.status_changed.emit("Cannot switch comp — not connected", "#eb6f92")
            return
        try:
            if comp_id == 'current':
                new_comp = fu.GetCurrentComp()
                if not new_comp:
                    self.status_changed.emit("No active comp on Fusion page", "#eb6f92")
                    return
                self._do_switch_comp(fu, new_comp)

            elif comp_id.startswith('clip:'):
                _, tr_s, ii_s = comp_id.split(':', 2)
                tr, ii = int(tr_s), int(ii_s)
                proj = self._resolve.GetProjectManager().GetCurrentProject()
                tl   = proj.GetCurrentTimeline() if proj else None
                if tl:
                    items = tl.GetItemListInTrack("video", tr) or []
                    if ii < len(items):
                        clip_comp = items[ii].GetFusionCompByIndex(1)
                        if clip_comp:
                            try:
                                clip_comp.SetActive()
                                log.info("[set_active_comp] SetActive called on clip comp")
                            except Exception:
                                pass
                # Defer GetCurrentComp by 100 ms — lets Resolve process SetActive
                # without blocking the Qt main thread with time.sleep()
                QTimer.singleShot(100, lambda: self._finalize_clip_comp(fu))

            else:
                raw = fu.GetCompList()
                if not raw or comp_id not in raw:
                    self.status_changed.emit("Comp not found", "#eb6f92")
                    return
                self._do_switch_comp(fu, raw[comp_id])

        except Exception as e:
            self._switching_comp = False
            self.status_changed.emit(f"Switch comp failed: {e}", "#eb6f92")
            log.error("[set_active_comp] Error: %s", e, exc_info=True)

    def _finalize_clip_comp(self, fu):
        """Continuation of set_active_comp for clip: comps — runs after 100 ms delay."""
        try:
            new_comp = fu.GetCurrentComp()
            if not new_comp:
                self.status_changed.emit("Could not activate clip comp", "#eb6f92")
                return
            self._do_switch_comp(fu, new_comp)
        except Exception as e:
            self.status_changed.emit(f"Switch comp failed: {e}", "#eb6f92")
            log.error("[set_active_comp] _finalize_clip_comp error: %s", e, exc_info=True)

    def _do_switch_comp(self, fu, new_comp):
        """Shared finalization for all comp-switch paths."""
        self._switching_comp = True
        try:
            if self._watcher:
                self._watcher.stop()
                self._watcher = None
            self._last_comp_scan = {}
            self._apply_new_comp(new_comp)  # creates new watcher synchronously
            name = self._get_comp_name(new_comp)
            log.info("[set_active_comp] Switched to '%s'", name)
            self.status_changed.emit(f"Switched to: {name}", "#9ccfd8")
            log.info("[AutoComp] Comp switch complete — watcher will auto-scan")
            # Update the comp selector label in the toolbar
            QTimer.singleShot(0, lambda: self.list_comps(True))
        finally:
            self._switching_comp = False

    # ── i18n ─────────────────────────────────────────────────────────────────

    @Slot(result=str)
    def get_i18n(self) -> str:
        """Return the JSON string of the active language file."""
        lang = self._settings.get("language", "en")
        base = language_dir()
        path = os.path.join(base, f"{lang}.json")
        if not os.path.isfile(path):
            path = os.path.join(base, "en.json")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read()
        except Exception as exc:
            log.warning("[i18n] Could not load language file: %s", exc)
            return "{}"

    @Slot(result=str)
    def list_languages(self) -> str:
        """Return a JSON array of {code, label} objects for all available languages."""
        base = language_dir()
        langs = []
        for fname in sorted(os.listdir(base)):
            if not fname.endswith(".json"):
                continue
            code = fname[:-5]
            try:
                with open(os.path.join(base, fname), "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                label = data.get("_meta", {}).get("language", code)
            except Exception:
                label = code
            langs.append({"code": code, "label": label})
        return json.dumps(langs)

    # ── State from JS ─────────────────────────────────────────────────────────

    @Slot(str)
    def set_curve_state(self, data_json):
        """JS calls this whenever h1/h2/mode/overframe_points change."""
        d = json.loads(data_json)
        self._h1       = d.get("h1", self._h1)
        self._h2       = d.get("h2", self._h2)
        self._mode     = d.get("mode", self._mode)
        self._of_points    = d.get("of_points", [])
        self._phys_zeta    = float(d.get("phys_zeta",    self._phys_zeta))
        self._phys_omega_n = float(d.get("phys_omega_n", self._phys_omega_n))
        self._el_amplitude = float(d.get("el_amplitude", self._el_amplitude))
        self._el_period    = float(d.get("el_period",    self._el_period))
        if self._auto_apply and self._comp:
            self._auto_timer.start(280)   # debounce 280 ms

    @Slot(str, str)
    def select_input(self, tool_name, inp_id):
        self._sel_inp = (tool_name, inp_id)

    @Slot(str)
    def select_tools(self, data_json):
        """
        Called from JS when user selects/deselects nodes in the comp scan panel.
        Uses _last_comp_scan cache — never triggers a new scan that would emit
        comp_scan_updated and reset the JS selection state.
        """
        if self._watcher is None:
            return
        try:
            selection = json.loads(data_json)
        except Exception:
            return

        if not selection:
            self._sel_tools = {}
            return

        cache = getattr(self, '_last_comp_scan', {})
        new_sel = {}
        for tool_name, inp_ids in selection.items():
            tool_inputs = cache.get(tool_name, {})
            filtered = {iid: tool_inputs[iid] for iid in inp_ids if iid in tool_inputs}
            if filtered:
                new_sel[tool_name] = filtered
        self._sel_tools = new_sel

    @Slot(int, int)
    def set_kf_range(self, from_idx, to_idx):
        """from_idx and to_idx are 1-based real indices. to_idx=0 still accepted as last-kf fallback."""
        self._kf_from = max(1, from_idx)
        self._kf_to   = max(0, to_idx)

    @Slot(bool)
    def set_auto_comp(self, enabled: bool):
        self._auto_comp = enabled
        log.info("[AutoComp] Auto-follow %s", "enabled" if enabled else "disabled")

    # ── Presets ───────────────────────────────────────────────────────────────

    @Slot(str)
    def load_library(self, library):
        builtin = load_builtin(library)
        user    = [p for p in active_presets(self._profiles)
                   if p.get("library") == library]
        self.presets_updated.emit(json.dumps(builtin + user))

    @Slot(str)
    def save_preset(self, preset_json):
        p = json.loads(preset_json)
        self._profiles = add_preset(self._profiles, p)
        self.load_library(p.get("library", "easing"))

    @Slot(int)
    def delete_preset(self, idx):
        self._profiles = delete_preset(self._profiles, idx)
        self.load_library(self._mode)

    @Slot(str)
    def new_profile(self, name):
        self._profiles = new_profile(self._profiles, name.strip())
        self._emit_profiles()

    @Slot(str)
    def delete_profile(self, name):
        self._profiles = delete_profile(self._profiles, name)
        self._emit_profiles()

    @Slot(str)
    def switch_profile(self, name):
        self._profiles = switch_profile(self._profiles, name)
        self.load_library(self._mode)

    def _emit_profiles(self):
        self.profiles_updated.emit(json.dumps({
            "names":  list(self._profiles["profiles"].keys()),
            "active": self._profiles["active"],
        }))

    # ── Apply ─────────────────────────────────────────────────────────────────

    @Slot()
    def apply_curve(self):
        self._do_apply(scope="single")

    @Slot()
    def apply_curve_selected(self):
        """Apply to all selected nodes from the comp scan, or active tool if none selected."""
        self._do_apply(scope="selected")

    # Keep old name as alias so any existing connections don't break
    @Slot()
    def apply_curve_all(self):
        self._do_apply(scope="selected")

    @Slot()
    def undo_resolve(self):
        """Forward Ctrl+Z from MFlow window to Resolve's comp undo."""
        if self._comp:
            try:
                self._comp.Undo()
                log.debug("[Undo] comp.Undo() called")
            except Exception as e:
                log.debug("[Undo] comp.Undo() failed: %s", e)

    @Slot()
    def redo_resolve(self):
        """Forward Ctrl+Shift+Z from MFlow window to Resolve's comp redo."""
        if self._comp:
            try:
                self._comp.Redo()
                log.debug("[Redo] comp.Redo() called")
            except Exception as e:
                log.debug("[Redo] comp.Redo() failed: %s", e)

    def _do_apply(self, all_inputs=None, scope="single"):
        # Legacy call from auto-apply timer passes all_inputs bool — normalise
        if all_inputs is True:
            scope = "selected"
        elif all_inputs is False:
            scope = "single"

        if self._comp is None:
            self.apply_done.emit(False, "Not connected to Resolve")
            return

        fps = self._fps
        try:
            fps = float(self._comp.GetAttrs().get("COMPN_FPS", fps))
        except Exception:
            pass

        if self._watcher is None:
            self.apply_done.emit(False, "Watcher not running")
            return

        # Build the list of (tool, inputs_dict) to process
        work_items = []  # list of (tool_obj, {inp_id: meta})

        if scope == "selected":
            if not self._sel_tools:
                self.apply_done.emit(False, "No nodes selected — select inputs in the Scan panel first")
                return
            # Multi-node: use everything the user selected in the comp scan
            for tool_name, inp_dict in self._sel_tools.items():
                try:
                    tool_list = self._comp.GetToolList(False)
                    tool_obj = next(
                        (t for t in tool_list.values() if t.Name == tool_name), None
                    ) if tool_list else None
                    if tool_obj and inp_dict:
                        work_items.append((tool_obj, inp_dict))
                except Exception:
                    pass
            if not work_items:
                self.apply_done.emit(False, "No nodes selected — use Scan All and select nodes first")
                return
        else:
            # Single-node: active tool only (original behaviour)
            try:
                tool = self._comp.ActiveTool
            except Exception:
                self.apply_done.emit(False, "Could not read active tool")
                return
            if not tool:
                self.apply_done.emit(False, "No tool selected in Fusion")
                return
            all_inp = self._watcher._animated_inputs(tool)
            if not all_inp:
                self.apply_done.emit(False, "No animated inputs found on this tool")
                return
            if scope == "single" and self._sel_inp:
                _, sel_id = self._sel_inp
                targets = {sel_id: all_inp[sel_id]} if sel_id in all_inp else all_inp
            else:
                targets = all_inp
            work_items.append((tool, targets))

        applied = 0
        no_spline = 0
        failed = 0
        tool_names = []
        try:
            self._comp.StartUndo("MFlow: Apply")
            self._comp.Lock()
            for tool_obj, inp_dict in work_items:
                tool_names.append(tool_obj.Name)
                for inp_id, meta in inp_dict.items():
                    spline = self._get_spline(meta["input_obj"])
                    if spline is None:
                        no_spline += 1
                        print(f"[MFlow] _do_apply: no BezierSpline for '{inp_id}' on '{tool_obj.Name}'")
                        continue
                    if self._apply_one(spline, fps):
                        applied += 1
                    else:
                        failed += 1
            self._comp.Unlock()
            self._comp.EndUndo(True)
        except Exception as e:
            try: self._comp.Unlock(); self._comp.EndUndo(True)
            except Exception: pass
            self.apply_done.emit(False, f"Exception: {e}")
            return

        names_str = ", ".join(tool_names) if tool_names else "?"
        if applied:
            self.apply_done.emit(True, f"Applied to {applied} input(s) on: {names_str}")
        elif no_spline > 0 and failed == 0:
            self.apply_done.emit(False,
                f"No BezierSpline found on {no_spline} input(s). "
                f"Right-click the parameter in Fusion > Animate to create keyframes first.")
        elif failed > 0:
            self.apply_done.emit(False,
                f"Apply failed on {failed} input(s). "
                f"Check the terminal for [MFlow] lines.")
        else:
            self.apply_done.emit(False, "No animated inputs found.")

    def _get_spline(self, inp):
        """
        Return the BezierSpline object for GetKeyFrames/SetKeyFrames.

        Architecture for animated Point2D params (Center, Pivot):
          Center inp → PolyPath tool
                           └── Displacement input → BezierSpline (timing/easing)

        The PolyPath stores path geometry (PolyLine XY points).
        The Displacement BezierSpline controls timing along the path and has
        proper RH/LH handles — it's what we apply bezier easing to.

        For scalar params (Size, Angle, etc.): directly connected BezierSpline.
        """
        try:
            out = inp.GetConnectedOutput()
            if out:
                tool = out.GetTool()
                if tool:
                    reg = ""
                    try: reg = str(tool.GetAttrs().get("TOOLS_RegID", ""))
                    except Exception: pass

                    if "BezierSpline" in reg:
                        # Standard scalar case — BezierSpline has handles in GetKeyFrames
                        get_kf = getattr(tool, "GetKeyFrames", None)
                        if callable(get_kf):
                            sd = get_kf()
                            if isinstance(sd, dict) and len(sd) >= 2:
                                return tool

                    elif "PolyPath" in reg:
                        # Point2D motion path: navigate into PolyPath's inputs to
                        # find the Displacement BezierSpline (controls easing/timing).
                        try:
                            for sub_inp in tool.GetInputList().values():
                                try:
                                    sub_out = sub_inp.GetConnectedOutput()
                                    if not sub_out: continue
                                    sub_tool = sub_out.GetTool()
                                    if not sub_tool: continue
                                    sub_reg = str(sub_tool.GetAttrs().get("TOOLS_RegID", ""))
                                    if "BezierSpline" not in sub_reg: continue
                                    get_kf = getattr(sub_tool, "GetKeyFrames", None)
                                    if not callable(get_kf): continue
                                    sd = get_kf()
                                    if isinstance(sd, dict) and len(sd) >= 2:
                                        print(f"[MFlow] _get_spline: PolyPath → Displacement BezierSpline '{sub_tool.Name}'")
                                        return sub_tool
                                except Exception:
                                    continue
                        except Exception:
                            pass
        except Exception:
            pass

        # Fallback: input directly (sub-inputs, compound types, no connected tool)
        try:
            get_kf = getattr(inp, "GetKeyFrames", None)
            if callable(get_kf):
                sd = get_kf()
                if isinstance(sd, dict) and len(sd) >= 2:
                    return inp
        except Exception:
            pass

        return None

    def _apply_one(self, spline, fps):
        mode = self._mode
        h1, h2 = self._h1, self._h2
        kf_from, kf_to = self._kf_from, self._kf_to

        if mode == "easing":
            return apply_bezier(spline, h1, h2, kf_from=kf_from, kf_to=kf_to)
        if mode == "overframe":
            pts = [OverframePoint(
                t=p["t"], v=p["v"],
                lh=p.get("lh", [-0.1, 0.0]),
                rh=p.get("rh", [0.1, 0.0]),
                tangent=p.get("tangent", "smooth"),
            ) for p in self._of_points]
            return apply_overframe(spline, h1, h2, pts, kf_from=kf_from, kf_to=kf_to) if pts else apply_bezier(spline, h1, h2, kf_from=kf_from, kf_to=kf_to)

        # spring / elastic / bounce — use anchor-aware range
        r = self._bake_range(spline, kf_from=kf_from, kf_to=kf_to)
        if not r: return False
        t0, v0, t1, v1 = r

        if mode == "elastic":
            frames = bake_elastic_penner(t0, v0, t1, v1, fps,
                                         amplitude=self._el_amplitude,
                                         period=self._el_period)
            return apply_baked(spline, frames, t_start=t0, t_end=t1)
        if mode in ("spring", "bounce"):
            frames = bake_oscillator(t0, v0, t1, v1, fps,
                                     zeta=self._phys_zeta,
                                     omega_n=self._phys_omega_n)
            return apply_baked(spline, frames, t_start=t0, t_end=t1)
        return apply_bezier(spline, h1, h2, kf_from=kf_from, kf_to=kf_to)

    def _bake_range(self, spline, kf_from=1, kf_to=0):
        """
        Like _kf_range but detects when the spline is already baked (dense kfs)
        and recovers the original user anchors instead of using index positions.

        Strategy: find the two 'anchor' keyframes — the ones at the true boundaries
        of the baked range. We identify them as the keyframes that have the largest
        gap to their neighbors, i.e. they are isolated points at the edges of a
        dense baked cluster.
        """
        try:
            get_kf = getattr(spline, "GetKeyFrames", None)
            if not callable(get_kf): return None
            sd = get_kf()
            if not isinstance(sd, dict) or len(sd) < 2: return None
            times = sorted(sd.keys(), key=lambda x: float(x))
            n = len(times)
            fts = [float(t) for t in times]

            # Compute gaps between consecutive keyframes
            gaps = [fts[i+1] - fts[i] for i in range(n-1)]
            avg_gap = sum(gaps) / len(gaps) if gaps else 1.0

            # A "baked" spline has many keyframes with gap ≈ 1 frame (at fps).
            # Anchors are the outermost keyframes of the selected range.
            # If the spline looks baked (avg_gap < 3), find the true boundary
            # anchors by looking for the first and last keyframe that are
            # significantly farther from their neighbor than the average.
            is_baked = (n > 10 and avg_gap < 3.0)

            if is_baked:
                # Find anchor candidates: keyframes with gap > 2x avg on either side
                threshold = max(avg_gap * 2.0, 2.0)
                left_anchor_i  = 0  # default: first kf
                right_anchor_i = n - 1  # default: last kf

                # Walk from left to find the first large gap (= right boundary of left anchor)
                for i in range(n - 1):
                    if gaps[i] > threshold:
                        left_anchor_i = i
                        break

                # Walk from right to find the last large gap (= left boundary of right anchor)
                for i in range(n - 2, -1, -1):
                    if gaps[i] > threshold:
                        right_anchor_i = i + 1
                        break

                # Apply kf_from/kf_to as segment indices on anchors, not on all kfs
                # For baked splines we treat the detected anchors as the full range
                t0 = fts[left_anchor_i]
                t1 = fts[right_anchor_i]
            else:
                # Not baked — use normal index-based range
                i0 = max(0, kf_from - 1)
                i1 = (n - 1) if kf_to == 0 else min(n - 1, kf_to - 1)
                if i1 <= i0: i1 = min(i0 + 1, n - 1)
                t0 = fts[i0]
                t1 = fts[i1]

            def _v(t, k):
                try:
                    v = spline.GetInput(t)
                    if v is not None: return float(v)
                except Exception:
                    pass
                e = sd[k]
                if isinstance(e, dict):
                    for key in (1, 1.0, "Value"):
                        if key in e and isinstance(e[key], (int, float)):
                            return float(e[key])
                    return 0.0
                return float(e) if isinstance(e, (int, float)) else 0.0

            k0 = times[[abs(float(t)-t0) for t in times].index(min(abs(float(t)-t0) for t in times))]
            k1 = times[[abs(float(t)-t1) for t in times].index(min(abs(float(t)-t1) for t in times))]
            return t0, _v(t0, k0), t1, _v(t1, k1)
        except Exception:
            return None

    def _kf_range(self, spline, kf_from=1, kf_to=0):
        """Read t0,v0,t1,v1 using 1-based kf_from/kf_to indices. kf_to=0 means last.
        Uses GetInput for values so baked intermediate keyframes don't corrupt v0/v1."""
        try:
            get_kf = getattr(spline, "GetKeyFrames", None)
            if not callable(get_kf): return None
            sd = get_kf()
            if not isinstance(sd, dict) or len(sd) < 2: return None
            times = sorted(sd.keys(), key=lambda x: float(x))
            n = len(times)
            i0 = max(0, kf_from - 1)
            i1 = (n - 1) if kf_to == 0 else min(n - 1, kf_to - 1)
            if i1 <= i0: i1 = min(i0 + 1, n - 1)
            k0, k1 = times[i0], times[i1]
            t0, t1 = float(k0), float(k1)

            def _v(t, entry):
                # GetInput is the authoritative source for the actual value at a time
                try:
                    v = spline.GetInput(t)
                    if v is not None: return float(v)
                except Exception:
                    pass
                # Fallback: parse the kf entry dict
                if isinstance(entry, dict):
                    for key in (1, 1.0, "Value"):
                        if key in entry and isinstance(entry[key], (int, float)):
                            return float(entry[key])
                    return 0.0
                return float(entry) if isinstance(entry, (int, float)) else 0.0

            return t0, _v(t0, sd[k0]), t1, _v(t1, sd[k1])
        except Exception:
            return None

    # ── Overframe baked presets ───────────────────────────────────────────────

    # ── Settings ──────────────────────────────────────────────────────────────

    @Slot(result=str)
    def get_settings(self):
        return json.dumps(self._settings)

    @Slot(str)
    def save_settings(self, s_json):
        self._settings = json.loads(s_json)
        self._fps = float(self._settings.get("bake_fps", 24))
        _wj(settings_file(), self._settings)
        self.settings_signal.emit(s_json)

    @Slot(result=str)
    def scan_pythons(self) -> str:
        """Start an async Python-binary scan. Returns cache immediately if
        available (< 120 s old); otherwise kicks off a QRunnable worker that
        emits ``pythons_scanned`` when done, and returns a sentinel so the UI
        can show a spinner."""
        import time
        now = time.monotonic()
        if self._python_scan_cache and (now - self._python_scan_time) < 120:
            return self._python_scan_cache

        # Kick off background scan — result arrives via pythons_scanned signal
        backend_ref = self

        class _ScanWorker(QRunnable):
            def run(self):
                result = backend_ref._do_scan_pythons()
                backend_ref._python_scan_cache = result
                backend_ref._python_scan_time  = time.monotonic()
                # Signal must be emitted on the Qt thread; use a zero-delay timer
                QTimer.singleShot(0, lambda: backend_ref.pythons_scanned.emit(result))

        QThreadPool.globalInstance().start(_ScanWorker())
        # Return stale cache or scanning placeholder
        if self._python_scan_cache:
            return self._python_scan_cache
        return json.dumps({"pythons": [], "active": sys.executable,
                           "versions": {}, "scanning": True})

    def _do_scan_pythons(self) -> str:
        """Blocking scan — runs in a thread pool worker, never on the Qt main thread."""
        import glob, subprocess as sp, platform
        found = {}

        def _probe(exe):
            try:
                r = sp.run([exe, "--version"], capture_output=True, text=True, timeout=5)
                ver = (r.stdout + r.stderr).strip().replace("Python ", "")
                if ver and "3." in ver:
                    found[exe] = ver
            except Exception:
                pass

        _probe(sys.executable)
        if platform.system() == "Windows":
            base = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python")
            for exe in glob.glob(os.path.join(base, "Python3*", "python.exe")):
                _probe(exe)
            for ver in ("3.12", "3.11", "3.10", "3.9"):
                try:
                    r = sp.run(["py", f"-{ver}", "-c", "import sys;print(sys.executable)"],
                               capture_output=True, text=True, timeout=5)
                    exe = r.stdout.strip()
                    if exe and os.path.isfile(exe):
                        _probe(exe)
                except Exception:
                    pass
        else:
            import shutil
            for name in ("python3", "python3.13", "python3.12", "python3.11", "python3.10", "python3.9"):
                exe = shutil.which(name)
                if exe:
                    _probe(exe)

        clean = {k: v for k, v in found.items()
                 if "WindowsApps" not in k and "PythonSoftwareFoundation" not in k}
        active = self._settings.get("python_path", "") or sys.executable
        return json.dumps({"pythons": list(clean.keys()), "active": active,
                           "versions": clean})

    @Slot(str)
    def set_python_path(self, path: str):
        self._settings["python_path"] = path
        _wj(settings_file(), self._settings)

    @Slot()
    def export_settings(self):
        path, _ = QFileDialog.getSaveFileName(
            None, "Export Settings", "fusionflow-settings.json", "JSON (*.json)")
        if path:
            _wj(path, self._settings)
            self.status_changed.emit("Settings exported", "#9ccfd8")

    @Slot()
    def import_settings(self):
        path, _ = QFileDialog.getOpenFileName(
            None, "Import Settings", "", "JSON (*.json)")
        if path:
            d = _rj(path)
            if d:
                self._settings = d
                _wj(settings_file(), d)
                self.settings_signal.emit(json.dumps(d))
                self.status_changed.emit("Settings imported", "#9ccfd8")

    # ── Theme folder ──────────────────────────────────────────────────────────

    @Slot(str, str)
    def export_theme_dialog(self, name: str, json_data: str):
        """Open a Save File dialog and write the theme JSON."""
        safe = "".join(c for c in name if c.isalnum() or c in " _-").strip() or "theme"
        path, _ = QFileDialog.getSaveFileName(
            None, "Export Theme", safe + ".json", "JSON (*.json)")
        if not path:
            return
        try:
            data = json.loads(json_data)
            _wj(path, data)
            self.status_changed.emit(f"Theme exported: {path}", "#9ccfd8")
        except Exception as e:
            self.status_changed.emit(f"Theme export failed: {e}", "#eb6f92")

    @Slot()
    def list_themes(self):
        """Scan themes/ folder (user AppData) and bundled themes/ (install dir)."""
        seen = {}  # filename → entry, user themes override bundled
        # Bundled first (lower priority)
        try:
            bdir = bundled_themes_dir()
            if os.path.isdir(bdir):
                for fname in sorted(os.listdir(bdir)):
                    if not fname.endswith(".json"):
                        continue
                    try:
                        data = _rj(os.path.join(bdir, fname))
                        key = fname[:-5]
                        seen[key] = {"name": data.get("name", key), "filename": key, "bundled": True}
                    except Exception:
                        pass
        except Exception:
            pass
        # User themes (higher priority — override bundled with same key)
        try:
            tdir = themes_dir()
            for fname in sorted(os.listdir(tdir)):
                if not fname.endswith(".json"):
                    continue
                try:
                    data = _rj(os.path.join(tdir, fname))
                    key = fname[:-5]
                    seen[key] = {"name": data.get("name", key), "filename": key, "bundled": False}
                except Exception:
                    pass
        except Exception:
            pass
        self.themes_updated.emit(json.dumps(sorted(seen.values(), key=lambda x: x["name"])))

    @Slot(str)
    def load_theme(self, name: str):
        """Load a theme JSON from user or bundled themes/ folder."""
        for tdir in [themes_dir(), bundled_themes_dir()]:
            if not os.path.isdir(tdir):
                continue
            path = os.path.join(tdir, name + ".json")
            if not os.path.isfile(path):
                path = os.path.join(tdir, name)
            if os.path.isfile(path):
                try:
                    data = _rj(path)
                    self.load_theme_result.emit(json.dumps(data))
                    return
                except Exception:
                    pass
        self.status_changed.emit(f"Theme not found: {name}", "#eb6f92")

    @Slot(str, str)
    def save_theme(self, name: str, json_data: str):
        """Save a theme JSON to themes/ folder."""
        tdir = themes_dir()
        safe = "".join(c for c in name if c.isalnum() or c in " _-").strip() or "theme"
        path = os.path.join(tdir, safe + ".json")
        try:
            data = json.loads(json_data)
            data["name"] = name
            _wj(path, data)
            self.status_changed.emit(f"Theme saved: {name}", "#9ccfd8")
            self.list_themes()
        except Exception as e:
            self.status_changed.emit(f"Theme save failed: {e}", "#eb6f92")



