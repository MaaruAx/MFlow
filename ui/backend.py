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
from core.platform_config import settings_file
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
    connection_changed = Signal(bool, str)   # connected, detail text
    status_changed     = Signal(str, str)    # message, hex color
    apply_done         = Signal(bool, str)   # success, message
    settings_signal    = Signal(str)         # JSON settings dict
    pythons_scanned    = Signal(str)         # JSON {pythons, active, versions} — async result

    def __init__(self, window, comp=None, fusion_app=None, parent=None):
        super().__init__(parent)
        self._fusion_app = fusion_app
        self._win      = window
        self._comp     = comp
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
        self._fps      = float(self._settings.get("bake_fps", 24))
        self._js_ready = False        # True once JS signals it's fully initialised
        self._python_scan_cache = None  # cached result of scan_pythons()
        self._python_scan_time  = 0.0   # epoch when cache was last filled

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
        if self._watcher:
            self._watcher.stop()
            self._watcher = None
        self._start_watcher()
        self._announce_connection()

    @Slot(str)
    def reconnect(self, custom_path=""):
        from core.resolve_connection import get_resolve, get_comp
        self.connection_changed.emit(False, "Connecting…")
        try:
            s = json.loads(self.get_settings())
            cp = custom_path.strip() or s.get("dvr_path", "")
        except Exception:
            cp = custom_path.strip()
        resolve = get_resolve(cp)
        if resolve:
            from core.resolve_connection import get_comp as _gc
            self.set_comp(_gc(resolve))
        else:
            self.connection_changed.emit(False, "Not connected — check Preferences > External Scripting")

    def _announce_connection(self):
        if self._comp:
            try:
                comp_name = self._comp.GetAttrs().get("COMPS_Name", "Fusion")
                edition = "Free"
                ver_str = ""
                try:
                    fu = (self._comp.GetFusion() if hasattr(self._comp, "GetFusion")
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
        edges = {
            'right':  Qt.Edge.RightEdge,
            'left':   Qt.Edge.LeftEdge,
            'bottom': Qt.Edge.BottomEdge,
            'br': Qt.Edge.RightEdge | Qt.Edge.BottomEdge,
            'bl': Qt.Edge.LeftEdge  | Qt.Edge.BottomEdge,
        }.get(edge, Qt.Edge.RightEdge | Qt.Edge.BottomEdge)
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
            return
        from core.resolve_connection import ResolveWatcher
        self._watcher = ResolveWatcher(self._comp, self)
        self._watcher.tool_changed.connect(self._on_tool_changed)
        self._watcher.disconnected.connect(self._on_disconnected)
        self._watcher.start()

    def _on_tool_changed(self, name, inputs):
        payload = {
            "name": name,
            "inputs": {
                k: {"label": v["label"], "kf_count": v["kf_count"]}
                for k, v in inputs.items()
            }
        }
        self.tool_updated.emit(json.dumps(payload))

    def _on_disconnected(self):
        self.connection_changed.emit(False, "Disconnected")

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
        self._do_apply(all_inputs=False)

    @Slot()
    def apply_curve_all(self):
        self._do_apply(all_inputs=True)

    def _do_apply(self, all_inputs):
        if self._comp is None:
            self.apply_done.emit(False, "Not connected to Resolve")
            return
        try:
            tool = self._comp.ActiveTool
        except Exception:
            self.apply_done.emit(False, "Could not read active tool")
            return
        if not tool:
            self.apply_done.emit(False, "No tool selected in Fusion")
            return

        fps = self._fps
        try:
            fps = float(self._comp.GetAttrs().get("COMPN_FPS", fps))
        except Exception:
            pass

        if self._watcher is None:
            self.apply_done.emit(False, "Watcher not running")
            return

        all_inp = self._watcher._animated_inputs(tool)
        if not all_inp:
            self.apply_done.emit(False, "No animated inputs found on this tool")
            return

        if all_inputs:
            targets = all_inp
        elif self._sel_inp:
            _, sel_id = self._sel_inp
            targets = {sel_id: all_inp[sel_id]} if sel_id in all_inp else all_inp
        else:
            targets = all_inp

        applied = 0
        no_spline = 0
        failed = 0
        try:
            self._comp.StartUndo("MFlow: Apply")
            self._comp.Lock()
            for inp_id, meta in targets.items():
                spline = self._get_spline(meta["input_obj"])
                if spline is None:
                    no_spline += 1
                    print(f"[MFlow] _do_apply: no BezierSpline for input '{inp_id}'")
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

        if applied:
            self.apply_done.emit(True, f"Applied to {applied} input(s) on '{tool.Name}'")
        elif no_spline > 0 and failed == 0:
            self.apply_done.emit(False,
                f"No BezierSpline found on {no_spline} input(s). "
                f"Right-click the parameter in Fusion > Animate to create keyframes first.")
        elif failed > 0:
            self.apply_done.emit(False,
                f"Apply failed on {failed} input(s). "
                f"Check the terminal for [MFlow] lines.")
        else:
            self.apply_done.emit(False, "No animated inputs found on active tool.")

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
        if mode == "easing":
            return apply_bezier(spline, h1, h2)
        if mode == "overframe":
            pts = [OverframePoint(
                t=p["t"], v=p["v"],
                lh=p.get("lh", [-0.1, 0.0]),
                rh=p.get("rh", [0.1, 0.0]),
                tangent=p.get("tangent", "smooth"),
            ) for p in self._of_points]
            return apply_overframe(spline, h1, h2, pts) if pts else apply_bezier(spline, h1, h2)
        r = self._kf_range(spline)
        if mode == "elastic":
            if not r: return False
            t0, v0, t1, v1 = r
            frames = bake_elastic_penner(t0, v0, t1, v1, fps,
                                         amplitude=self._el_amplitude,
                                         period=self._el_period)
            return apply_baked(spline, frames)
        if mode in ("spring", "bounce"):
            if not r: return False
            t0, v0, t1, v1 = r
            frames = bake_oscillator(t0, v0, t1, v1, fps,
                                     zeta=self._phys_zeta,
                                     omega_n=self._phys_omega_n)
            return apply_baked(spline, frames)
        return apply_bezier(spline, h1, h2)

    def _kf_range(self, spline):
        """Read t0,v0,t1,v1 from the spline object (PlainInput or BezierSpline tool)."""
        try:
            get_kf = getattr(spline, "GetKeyFrames", None)
            if not callable(get_kf): return None
            sd = get_kf()
            if not isinstance(sd, dict) or len(sd) < 2: return None
            times = sorted(sd.keys(), key=lambda x: float(x))
            k0, k1 = times[0], times[-1]
            def _v(k):
                e = sd[k]
                if isinstance(e, dict):
                    for key in (1, 1.0, "Value"):
                        if key in e and isinstance(e[key], (int, float)):
                            return float(e[key])
                    return 0.0
                return float(e) if isinstance(e, (int, float)) else 0.0
            return float(k0), _v(k0), float(k1), _v(k1)
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


