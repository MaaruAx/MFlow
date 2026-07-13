"""
Backend — QObject exposed to JavaScript via QWebChannel.
All Resolve API calls happen here. UI logic stays in app.html.
"""
import json, os, sys
from PySide6.QtCore import QObject, Slot, Signal, QTimer, QRunnable, QThreadPool
from PySide6.QtWidgets import QFileDialog, QApplication

from core.preset_manager  import (load_profiles, save_profiles, add_preset,
                                   delete_preset, new_profile, delete_profile,
                                   switch_profile, load_builtin, active_presets,
                                   reorder_presets as _reorder_presets_lib)
import logging
log = logging.getLogger("mflow")
from core.platform_config import settings_file, themes_dir, bundled_themes_dir, language_dir, win_subprocess_kwargs
from core.resolve_connection import warmup_fusion_api
from core.curve_engine    import (apply_bezier, apply_baked, apply_steps_kf,
                                   apply_overframe, bake_oscillator,
                                   bake_elastic_penner, bake_elastic_out,
                                   bake_bounce, bake_catenary, bake_pulse,
                                   bake_noise, bake_resonance, OverframePoint,
                                   _numeric_times, derive_squash_stretch,
                                   eval_bezier)


# ── Squash & stretch input resolution ─────────────────────────────────────────
# Detection is by INPUT SIGNATURE (which input IDs the tool actually has),
# not by tool.ID — we never actually confirmed what .ID reports for either
# tool below, and signature-based detection is strictly more robust anyway:
# it works even if the same visible "Transform" name maps to different
# internal IDs across Resolve versions, since it only cares about the
# inputs that actually matter for this feature.
#
# Both mappings below were built from REAL GetInputList() dumps against
# live tools, not guessed:
#
# 1. ResolveFX "Transform" (OFX-based, dragged from Filters, not Fusion's
#    native tool): scaleX/scaleY ("Ancho"/"Altura") are already independent
#    — no lock checkbox exists on this tool at all.
#
# 2. Fusion's native "Transform" tool: has UseSizeAndAspect ("Usar tamaño y
#    aspecto"), which when True locks size editing to Size+Aspect and makes
#    XSize/YSize read-only derived values; setting it False is what makes
#    XSize/YSize ("Tamaño (X)"/"Tamaño (Y)") independently keyframeable.
#    IMPORTANT: this tool ALSO has inputs literally called Width/Height
#    ("Anchura"/"Altura") — but those are sub-fields of ReferenceSize (the
#    canvas resolution the Size percentage is relative to), NOT animatable
#    object scale. They are deliberately NOT used here, and Width/Height is
#    deliberately excluded from the generic fallback below too, precisely
#    because this tool proves that pairing can silently mean the wrong
#    thing on a real, common tool.
def _find_squash_stretch_inputs_by_signature(by_id):
    """by_id is the set of INPS_ID strings present on the tool. Returns
    (width_id, height_id, lock_id_or_None) for the first matching known
    signature, or None if nothing matches."""
    if {"UseSizeAndAspect", "XSize", "YSize"} <= by_id:
        return ("XSize", "YSize", "UseSizeAndAspect")
    if {"scaleX", "scaleY"} <= by_id:
        return ("scaleX", "scaleY", None)
    # Lower-confidence generic fallbacks for tools not yet confirmed —
    # deliberately NOT including bare "Width"/"Height": confirmed above to
    # be a false friend (reference-size fields, not animatable scale) on at
    # least one common real tool, so it's excluded rather than risk quietly
    # writing keyframes to the wrong input on some future tool shaped the
    # same way.
    for w, h in (("SizeX", "SizeY"), ("Size.X", "Size.Y")):
        if w in by_id and h in by_id:
            lock = None
            for lock_candidate in ("LockAspect", "LockXY", "UseFrameFit"):
                if lock_candidate in by_id:
                    lock = lock_candidate
                    break
            return (w, h, lock)
    return None


def _resolve_squash_stretch_inputs(tool):
    """Given a live Fusion tool object, returns (width_id, height_id, lock_id)
    describing which two inputs squash & stretch should write keyframes to,
    and — if applicable — which boolean input must be unlocked first.
    lock_id is None when the tool has no such lock and can be written to
    directly (confirmed true for the ResolveFX Transform).

    Returns None if this tool isn't recognized by any known signature —
    callers must treat that as "squash & stretch isn't available for this
    tool" and say so clearly in the UI, never guess further."""
    try:
        inputs = tool.GetInputList()
        by_id = set()
        for inp in inputs.values():
            attrs = inp.GetAttrs()
            inp_id = attrs.get("INPS_ID", "")
            if inp_id:
                by_id.add(inp_id)
    except Exception as e:
        log.debug("[SquashStretch] Could not read input list: %s", e)
        return None

    match = _find_squash_stretch_inputs_by_signature(by_id)
    if match is None:
        try:
            tool_id = tool.ID
        except Exception:
            tool_id = "?"
        log.info("[SquashStretch] No known input signature matched for tool %r "
                  "— squash & stretch unavailable for this tool.", tool_id)
    return match


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
    _conn_changed_sig   = Signal(bool, str)  # internal: thread-safe connection_changed from workers
    _scan_done_sig      = Signal(object)     # internal: thread-safe pythons_scanned from ScanWorker
    curve_state_changed = Signal(str)        # full curve state JSON — dock windows sync from this
    flip_requested      = Signal()           # dock asks main window to run flipAll()

    def __init__(self, window, comp=None, fusion_app=None, resolve=None, parent=None):
        super().__init__(parent)
        self._fusion_app = fusion_app
        self._win      = window
        self._comp     = comp
        self._resolve  = resolve  # stored from startup or reconnect
        self._fu       = None    # cached Fusion scripting object
        # Free mode: Resolve injects 'app' directly into MFlow_Free.py at
        # script-launch time (see MFlow_Free.py) — there is no scriptapp()
        # call anywhere in that path, so we never obtain a `resolve` object
        # at all, only `fusion_app`. That injected reference is a one-time
        # snapshot for this script run; there is no documented API to
        # re-request a fresh one later. Studio mode always obtains BOTH via
        # get_resolve()/get_comp() at startup, so this combination
        # (fusion_app present, resolve absent) only ever happens in Free.
        self._is_free_mode = (fusion_app is not None and resolve is None)
        self._js_ready = False
        # Cache _fu immediately if resolve is available at startup
        if resolve:
            try:
                fu = resolve.Fusion()
                if fu:
                    self._fu = fu
                    log.info("[Init] Fusion object cached from startup resolve")
            except Exception as e:
                log.debug("[Init] Could not get Fusion at startup: %s", e)
        # Warm up the Python<->Fusion write-side scripting bridge now, at
        # startup, rather than letting the user's first real curve Apply be
        # the first write-side call of the session — see warmup_fusion_api().
        if self._comp is not None:
            warmup_fusion_api(self._comp)

        self._watcher  = None
        self._reconnecting = False        # guards against overlapping reconnect attempts
        self._reconnect_queued = False    # a click arrived while busy — service it once free
        self._reconnect_queued_path = ""
        self._auto_reconnect_timer = None  # background retry timer — None when not running
        self._profiles = load_profiles()
        self._settings = _rj(settings_file())
        self._mode     = "easing"
        self._phys_zeta    = 0.3
        self._phys_omega_n = 8.0
        self._phys_flipped = False
        self._el_amplitude = 1.0
        self._el_period    = 0.3
        self._el_direction = "in"       # 'in' | 'out'
        self._bounce_gamma = 4.0
        self._bounce_omega = 6.0
        self._bounce_dir   = "ceiling"  # 'ceiling' | 'floor'
        self._steps_n          = 8
        self._steps_from_start = False  # False='jump-end' (CSS default), True='jump-start'
        self._catenary_a   = 0.8
        self._catenary_reverse = False
        self._pulse_omega1 = 8.0
        self._pulse_omega2 = 2.0
        self._pulse_n      = 4.0
        self._pulse_reverse = False
        self._noise_freq   = 2.0
        self._noise_amp    = 0.5
        self._noise_seed   = 42
        self._noise_reverse = False
        self._res_gamma    = 2.0
        self._res_omega    = 8.0
        self._res_omega0   = 8.0
        self._res_reverse  = False
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
        self._use_playhead = bool(self._settings.get("use_playhead", True))
        self._precise_playhead = bool(self._settings.get("precise_playhead", False))
        # precise_playhead=False (default): if playhead is outside all segments,
        # snap to the nearest pair (closest keyframe boundary) instead of doing nothing.
        # precise_playhead=True: require the playhead to be strictly inside a segment.
        # When True, apply targets only the keyframe segment the playhead
        # currently sits inside (per spline, since each input can have a
        # different keyframe layout) — self._kf_from/_kf_to above are ignored
        # for the duration of that apply and restored immediately after.
        self._spline_clipboard = None  # {tool, input, keyframes}
        self._auto_comp = True        # auto-follow active Fusion comp
        self._switching_comp = False   # guard against re-entrant comp switches
        self._fps      = float(self._settings.get("bake_fps", 24))
        self._bake_density = max(1, int(self._settings.get("bake_density", 1)))
        # Squash & stretch — off by default; a button in the UI opens a
        # small popup to enable it and set intensity per apply, rather
        # than a persistent global switch like Auto-apply.
        self._squash_stretch_enabled = bool(self._settings.get("squash_stretch_enabled", False))
        self._squash_stretch_intensity = float(self._settings.get("squash_stretch_intensity", 1.0))
        self._squash_squash_intensity  = float(self._settings.get("squash_squash_intensity", 1.0))
        self._squash_invert = False  # swaps which axis gets stretch vs squash
        self._python_scan_cache = None  # cached result of scan_pythons()
        self._python_scan_time  = 0.0   # epoch when cache was last filled
        # Thread-safe delivery: worker threads emit this to invoke _apply_new_comp
        # on the main thread via Qt's automatic queued-connection mechanism.
        self._apply_comp_sig.connect(self._apply_new_comp)
        # Wire internal cross-thread signals to their public counterparts.
        # AutoConnection → QueuedConnection when emitted from a thread-pool worker,
        # guaranteeing delivery on the Qt main thread without a QMutex.
        self._conn_changed_sig.connect(self._on_worker_conn_failed)
        self._scan_done_sig.connect(self._deliver_scan_result)

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
        # If a watcher already exists (normal startup path — _start_watcher()
        # runs before JS finishes loading the page), this is the first safe
        # moment to scan: comp_scan_updated has no buffering, so firing it
        # any earlier is a guaranteed silent loss. See _start_watcher() for
        # the full explanation.
        if self._watcher is not None:
            self.scan_comp()
        # If Resolve wasn't running when MFlow launched, keep retrying quietly
        # instead of requiring a manual click on "Connect".
        self._ensure_auto_reconnect()

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

        # Disconnect WebChannel before the dialog closes to prevent Qt freeze
        # (QWebEngineView holds a render process; severing the channel first
        #  avoids a deadlock during garbage collection when the dialog is closed)
        def _cleanup_dock():
            try:
                view.page().setWebChannel(None)
                view.setPage(None)
            except Exception:
                pass
            self._dock_windows.pop(panel_id, None)
        dlg.finished.connect(_cleanup_dock)

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
        log.info("[Close-PY] close_window Slot invoked — calling self._win.close()")
        try:
            self._win.close()
        except Exception as e:
            log.error("[Close-PY] self._win.close() raised: %s", e, exc_info=True)

    # ── Resolve connection ────────────────────────────────────────────────────

    def set_comp(self, comp):
        self._comp = comp
        # Warm up the write-side scripting bridge for this (re)connection too
        # — see warmup_fusion_api(). Cheap, silent, non-fatal on failure.
        warmup_fusion_api(comp)
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
    def reconnect(self, custom_path="", _max_attempts=3):
        if self._is_free_mode:
            # First, the cheap and safe check: is the object Resolve handed
            # us at launch still answering? If so, there is nothing to
            # reconnect — report success immediately without touching the
            # external scriptapp() path at all (which risks handing back a
            # SEPARATE Fusion object than the one this session was built on
            # if it succeeds, silently desyncing anything already holding
            # the original reference).
            try:
                still_alive = self._fusion_app is not None and self._fusion_app.CurrentComp is not None
            except Exception:
                still_alive = False
            if still_alive:
                self.connection_changed.emit(True, "Connected (Free)")
                return
            # The injected reference is gone. Unlike Studio, we don't know
            # for certain the external scriptapp() path is meaningless here
            # — Resolve's own embedded interpreter runs in-process with
            # Resolve itself, so it may not be gated by the "External
            # scripting" preference the way a truly external process is.
            # Fall through to the normal attempt below as a best-effort; if
            # it also fails, the message afterward tells the user the
            # honest fallback (relaunch from Scripts > Comp).
            log.info("[Connect] Free mode: injected fusion_app is stale, "
                     "attempting external reconnect as a best-effort fallback")
        if self._reconnecting:
            # BUG FIX: this used to just `return` here — completely silent.
            # JS's doReconnect() already optimistically shows "Connecting…"
            # and disables the button BEFORE calling this Slot, so if an
            # unrelated attempt (e.g. a stale auto-retry that started before
            # Resolve was even open) happened to already be in flight, this
            # click was dropped with zero feedback — the button could stay
            # stuck on "Connecting…" until that unrelated attempt eventually
            # resolved on its own, with no guarantee of when or whether it
            # would. Queuing this request instead guarantees it always gets
            # serviced: as soon as the in-flight attempt finishes, exactly
            # one more attempt fires automatically using this call's args.
            log.debug("[Connect] Reconnect already in progress — queuing this request instead of dropping it")
            self._reconnect_queued_path = custom_path
            self._reconnect_queued = True
            return
        self._reconnecting = True
        # Emit immediately so the UI shows "Connecting…" right away
        self.connection_changed.emit(False, "Connecting\u2026")
        try:
            s = json.loads(self.get_settings())
            cp = custom_path.strip() or s.get("dvr_path", "")
        except Exception:
            cp = custom_path.strip()

        # Run get_resolve() on a thread-pool worker so the Qt main thread (and
        # the UI) stays responsive during the IPC call (which can take 2-5 s).
        # Background auto-reconnect passes _max_attempts=1 to avoid holding the
        # thread for ~16 s and reduce COM-level pressure on the Windows message pump.
        _self = self
        max_att = _max_attempts

        class _ConnectWorker(QRunnable):
            def run(self):
                import time
                try:
                    from core.resolve_connection import (probe_resolve_connection,
                                                          get_resolve_with_timeout,
                                                          get_comp_with_timeout as _gc)
                    log.info("[Connect] Starting connection attempt…")
                    log.info("[Connect] Module search path: %s", cp or "(auto)")

                    resolve = None
                    for attempt in range(max_att):
                        if attempt > 0:
                            log.info("[Connect] Retry %d/%d — waiting 2s…", attempt + 1, max_att)
                            time.sleep(2)
                        # Probe in a real separate process first — see
                        # probe_resolve_connection's docstring for why the
                        # thread-based timeout alone isn't sufficient (a
                        # hang here runs on a QThreadPool worker thread, not
                        # the main thread, but if the native call holds the
                        # GIL while stuck, that freezes every thread in the
                        # process including the main Qt event loop — this
                        # was NOT just a "leak one thread pool slot" risk).
                        if not probe_resolve_connection(cp, timeout=9.0):
                            log.warning("[Connect] Attempt %d — probe found Resolve "
                                        "unresponsive, skipping real attempt", attempt + 1)
                            continue
                        resolve = get_resolve_with_timeout(cp, timeout=8.0)
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
                        if _self._is_free_mode:
                            log.warning("[Connect] All attempts failed (Free mode fallback).")
                            _self._conn_changed_sig.emit(
                                False,
                                "Couldn't get a fresh connection. Close this window and "
                                "run Scripts > Comp > MFlow_Free again from Resolve.")
                        else:
                            log.warning("[Connect] All attempts failed. "
                                        "Ensure DaVinci Resolve is open and:\n"
                                        "  Preferences > System > General > "
                                        "External scripting using = Local")
                            _self._conn_changed_sig.emit(
                                False,
                                "Not connected \u2014 open Resolve and set "
                                "Preferences > General > External scripting: Local")
                except Exception as exc:
                    log.error("[Connect] Exception: %s", exc, exc_info=True)
                    _self._conn_changed_sig.emit(False, f"Connect error: {exc}")
                # NOTE: _reconnecting is deliberately NOT cleared here anymore.
                # BUG FIX: it used to be cleared in a `finally` right here, but
                # _apply_comp_sig.emit()/_conn_changed_sig.emit() only QUEUE
                # the result onto the main thread — they return immediately,
                # they don't wait for it to be processed. Clearing the guard
                # here meant there was a real window (confirmed via [PERF]
                # logs: a background attempt taking close to the auto-retry
                # timer's own 15s interval) where _reconnecting had already
                # gone back to False, but the main thread hadn't applied the
                # result yet — so the 15s timer's next tick saw "not
                # reconnecting, no comp yet" and fired a SECOND, fully
                # redundant connect attempt (duplicate Fusion connection,
                # duplicate watcher, duplicate comp scan — all visible
                # doubled up in the log). The guard is now cleared on the
                # main thread instead, in _apply_new_comp() and
                # _on_worker_conn_failed() below, after the result has
                # actually been applied — closing that window completely.

        QThreadPool.globalInstance().start(_ConnectWorker())

    def _deliver_scan_result(self, result):
        """Called on the Qt main thread by _scan_done_sig — safe to emit pythons_scanned."""
        self.pythons_scanned.emit(result)

    def _service_queued_reconnect(self):
        """If a manual reconnect click arrived while a previous attempt was
        still in flight, it was queued instead of dropped — this fires it
        now that the guard is free. Deliberately re-enters via a queued
        QTimer.singleShot(0, ...) rather than calling self.reconnect()
        directly, so this always runs as a fresh top-level call on the next
        event-loop iteration instead of nesting inside whichever signal
        handler just finished."""
        if self._reconnect_queued:
            self._reconnect_queued = False
            path = self._reconnect_queued_path
            log.debug("[Connect] Servicing queued reconnect request")
            QTimer.singleShot(0, lambda: self.reconnect(path))

    def _apply_new_comp(self, comp):
        """Called on the Qt main thread after a background reconnect succeeds
        (resolve was obtained; comp may or may not be present)."""
        try:
            if comp:
                # Stop the retry timer FIRST — before set_comp → _announce_connection
                # has a chance to call _ensure_auto_reconnect again.
                self._stop_auto_reconnect()
                log.info("[Connect] Applying comp to watcher")
                self.set_comp(comp)
            else:
                log.warning("[Connect] No comp available — Fusion page may not be active")
                self.connection_changed.emit(
                    False,
                    "Resolve found but no active Fusion comp \u2014 "
                    "open a composition or switch to the Fusion page")
        finally:
            # See the long comment in reconnect()'s worker for why this is
            # cleared HERE (main thread, after the result is fully applied)
            # rather than in the worker's own finally block.
            self._reconnecting = False
            self._service_queued_reconnect()

    def _on_worker_conn_failed(self, ok: bool, msg: str):
        """Main-thread landing point for _conn_changed_sig — the failure/
        exception path out of reconnect()'s background worker. See the long
        comment in that worker for why _reconnecting is cleared here instead
        of in the worker thread itself."""
        self._reconnecting = False
        self.connection_changed.emit(ok, msg)
        self._service_queued_reconnect()

    # ── Background auto-reconnect ────────────────────────────────────────────
    # Covers two cases the one-shot startup connect (main.py) can't handle:
    #  1. DaVinci Resolve wasn't running yet when MFlow launched.
    #  2. Resolve was running, then got closed mid-session (watcher reports
    #     disconnected). In both cases the UI previously required a manual
    #     click on "Connect" — this retries quietly in the background instead.

    def _ensure_auto_reconnect(self):
        """Start the background retry loop if we're not fully connected yet
        (resolve + comp both present) and it isn't already running."""
        if self._resolve is not None and self._comp is not None:
            return
        if self._auto_reconnect_timer is not None:
            return
        try:
            self._auto_reconnect_timer = QTimer(self)
            self._auto_reconnect_timer.setInterval(15000)
            self._auto_reconnect_timer.timeout.connect(self._auto_reconnect_tick)
            self._auto_reconnect_timer.start()
            log.info("[AutoReconnect] Background retry started (every 15s until connected)")
        except Exception as e:
            # Never let a timer setup failure take down the app — worst case
            # the user falls back to the manual Connect button, same as before.
            log.warning("[AutoReconnect] Could not start background retry: %s", e)
            self._auto_reconnect_timer = None

    def _auto_reconnect_tick(self):
        try:
            if self._resolve is not None and self._comp is not None:
                self._stop_auto_reconnect()
                return
            # Also skip if a reconnect attempt is already in flight — the
            # worker thread clears _reconnecting in its finally block before
            # _apply_new_comp runs on the main thread, creating a window where
            # comp is still None but an attempt is already connecting.
            if self._reconnecting:
                log.debug("[AutoReconnect] Tick skipped — reconnect already in flight")
                return
            log.debug("[AutoReconnect] Retry tick — attempting reconnect")
            self.reconnect(_max_attempts=1)
        except Exception as e:
            log.debug("[AutoReconnect] Tick error (will retry next interval): %s", e)

    def _stop_auto_reconnect(self):
        if self._auto_reconnect_timer is not None:
            try:
                self._auto_reconnect_timer.stop()
            except Exception:
                pass
            self._auto_reconnect_timer = None
            log.info("[AutoReconnect] Connected — background retry stopped")

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
            # Redundant safety net: _ensure_auto_reconnect() is a harmless no-op
            # if already connected or already retrying, so calling it here too
            # (in addition to js_ready/_on_disconnected) costs nothing and
            # covers any path that reports "not connected" without having
            # gone through those two hooks.
            self._ensure_auto_reconnect()

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
    def set_interacting(self, active: bool):
        """Wired to JS drag start/end (curve handles, physics parameter
        draggers). Pauses the comp watcher's polling while the user is
        actively dragging, so the ~150-240ms ActiveTool IPC round-trip
        (confirmed via [PERF] logging) can never land mid-gesture and
        stutter the interaction. Safe no-op if there's no watcher yet."""
        if self._watcher:
            self._watcher.set_interacting(active)

    def set_window_focused(self, focused: bool):
        """Called from main.py's QApplication.applicationStateChanged
        handler (not a JS-facing Slot — this is a pure OS/Qt-level concern).
        Pauses polling while MFlow isn't the active window. Deliberately
        does NOT affect the global Ctrl+R hotkey path (scan_comp()), which
        must keep working without window focus by design."""
        if self._watcher:
            self._watcher.set_focused(focused)

    def _set_always_on_top_native(self, widget, enabled: bool) -> bool:
        """Toggles topmost via the Win32 SetWindowPos API instead of Qt's
        setWindowFlags(). On Windows, setWindowFlags() destroys and
        recreates the widget's native HWND to apply the new window style —
        this is a real, confirmed cause of two separate symptoms: the
        taskbar icon silently disappearing (the freshly recreated HWND
        doesn't reliably keep the taskbar-visible extended style) and a
        general risk of anything bound to the OLD HWND (the global hotkey
        registration, native event filters) being silently orphaned.
        SetWindowPos changes z-order on the SAME HWND, in place — no
        destroy, no recreate, none of that risk. Returns True on success so
        the caller can fall back to the old behavior if this ever fails.
        """
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            from ctypes import wintypes

            # CRITICAL: without explicit argtypes, ctypes marshals plain
            # Python ints as 32-bit c_int by default. HWND_TOPMOST (-1) and
            # HWND_NOTOPMOST (-2) are pseudo-handles that must be passed as
            # a full pointer-width HWND — on 64-bit Windows, a 32-bit
            # marshaled -1 does NOT reliably sign-extend into the correct
            # 64-bit all-ones handle the API expects, so the call fails
            # silently (returns 0, no Python exception raised at all).
            # This was confirmed the hard way: three separate test sessions
            # all silently fell back to the old setWindowFlags() path with
            # zero diagnostic output, because failure-via-return-0 wasn't
            # even being logged before, only failure-via-exception. Setting
            # argtypes/restype explicitly makes ctypes marshal HWND_TOPMOST
            # correctly instead of guessing.
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.SetWindowPos.argtypes = [
                wintypes.HWND, wintypes.HWND,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wintypes.UINT,
            ]
            user32.SetWindowPos.restype = wintypes.BOOL

            hwnd = wintypes.HWND(int(widget.winId()))
            HWND_TOPMOST = wintypes.HWND(-1)
            HWND_NOTOPMOST = wintypes.HWND(-2)
            SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x0002, 0x0001, 0x0010
            insert_after = HWND_TOPMOST if enabled else HWND_NOTOPMOST

            ok = user32.SetWindowPos(
                hwnd, insert_after, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
            )
            if not ok:
                err = ctypes.get_last_error()
                log.warning("[AOT-PY] SetWindowPos returned 0 (failed) — "
                            "GetLastError=%d (%s)", err, ctypes.FormatError(err))
                return False
            return True
        except Exception as e:
            log.warning("[AOT-PY] Native SetWindowPos raised: %s", e, exc_info=True)
            return False

    @Slot(bool)
    def set_always_on_top(self, enabled: bool):
        from PySide6.QtCore import Qt
        flag = Qt.WindowType.WindowStaysOnTopHint

        # applySettingsUI() calls this unconditionally on every launch and
        # every settings save, regardless of whether the value actually
        # changed — meaning this was the very first native call touching
        # the window after creation, every single time, even when there
        # was nothing to do. Skipping the no-op case removes that as a
        # variable entirely while we track down the taskbar icon issue,
        # and is simply correct regardless: no reason to touch the native
        # window at all for a state it's already in.
        #
        # NOTE: self._win.windowFlags() is NOT a reliable source for this —
        # the native SetWindowPos path below never calls setWindowFlags(),
        # so Qt's own flag bookkeeping goes stale the first time the native
        # path is used and never reflects reality again. Track it ourselves.
        already_on_top = getattr(self, "_is_topmost", False)
        if already_on_top == enabled:
            log.debug("[AOT-PY] set_always_on_top(%s) — already in that state, no-op", enabled)
            return
        self._is_topmost = enabled

        if hasattr(self._win, "_log_taskbar_style"):
            self._win._log_taskbar_style(f"before set_always_on_top({enabled})")

        if self._set_always_on_top_native(self._win, enabled):
            log.info("[AOT-PY] set_always_on_top(%s) via SetWindowPos — no HWND recreation", enabled)
        else:
            # Fallback for non-Windows platforms or if the native call
            # itself failed — same behavior this always had, kept only as
            # a safety net now that the native path is the default.
            flags = self._win.windowFlags()
            log.info("[AOT-PY] set_always_on_top(%s) — flags before=%s", enabled, flags)
            if enabled: flags |= flag
            else: flags &= ~flag
            self._win.setWindowFlags(flags)
            self._win.show()
            log.info("[AOT-PY] set_always_on_top(%s) — flags after=%s (native frame, "
                     "no decoration hints stripped)", enabled, self._win.windowFlags())

        if hasattr(self._win, "_log_taskbar_style"):
            self._win._log_taskbar_style(f"after set_always_on_top({enabled})")

        # All dock windows
        for dlg in getattr(self, '_dock_windows', {}).values():
            if dlg and dlg.isVisible():
                if self._set_always_on_top_native(dlg, enabled):
                    continue
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
        # MUST wait for js_ready() the same way _announce_connection already
        # does — comp_scan_updated has no buffering on the QWebChannel side,
        # so a scan that completes before JS has called connect() on it is
        # silently lost forever, with no error anywhere. Confirmed happening
        # in production: the very first auto-scan on a fast machine finished
        # and emitted before "UI loaded — waiting for JS js_ready()" even
        # printed. If JS is already listening (a reconnect well after
        # startup, not the initial launch), scan immediately instead of
        # waiting on a signal that already fired.
        if self._js_ready:
            QTimer.singleShot(0, self.scan_comp)
        # else: js_ready() below scans once JS actually confirms it's listening.

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
        # Clear the resolve reference — it points at a dead process, and the
        # reconnect guard `_ensure_auto_reconnect` checks `self._resolve is None`
        # to decide whether to start retrying.
        # We deliberately DO NOT clear self._comp here: keeping the stale
        # reference costs nothing (all call sites wrap it in try/except) and
        # avoids breaking Ctrl+Z during the brief reconnect window.
        self._resolve = None
        self.connection_changed.emit(False, "Disconnected — reconnecting\u2026")
        self._ensure_auto_reconnect()

    def _on_comp_scan(self, scan_result: dict):
        """Forward comp-wide scan result to JS as JSON."""
        log.info("[Scan] Comp scan complete: %d tools with keyframes", len(scan_result))
        for tool_name, inputs in scan_result.items():
            log.debug("[Scan]   %s: %d input(s)", tool_name, len(inputs))
        self._last_comp_scan = scan_result
        try:
            payload = {}
            for tool_name, inputs in scan_result.items():
                payload[tool_name] = {
                    k: {"label": v["label"], "kf_count": v["kf_count"]}
                    for k, v in inputs.items()
                }
            json_payload = json.dumps(payload)
        except Exception as e:
            # This is the one thing the old code could never tell us: if
            # building or serializing the payload ever raised, the "Comp
            # scan complete" log line above would already have printed,
            # making a silent failure here look identical to success in
            # the log. Never again — log it loud and explicit.
            log.error("[Scan] Failed to build/serialize scan payload — "
                      "comp_scan_updated was NEVER emitted: %s", e, exc_info=True)
            return
        self.comp_scan_updated.emit(json_payload)
        log.info("[Scan] comp_scan_updated emitted — %d bytes, %d tool(s)",
                 len(json_payload), len(payload))

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
        # 1b. Free mode: the object Resolve injected directly at script
        # launch time (see MFlow_Free.py) is a live Fusion reference that
        # was never being tried here at all — every path above and below
        # this one assumes an external scriptapp()-style connection, which
        # Free never has. This was the direct cause of list_comps() and
        # anything else routed through _get_fusion() silently failing for
        # every Free session, regardless of whether the injected reference
        # was still perfectly valid.
        if self._fusion_app:
            try:
                _ = self._fusion_app.GetCurrentComp  # liveness check
                self._fu = self._fusion_app
                return self._fusion_app
            except Exception as e:
                log.debug("[Fusion] self._fusion_app liveness check failed: %s", e)
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
        self._phys_flipped = bool(d.get("phys_flipped",  self._phys_flipped))
        self._el_amplitude = float(d.get("el_amplitude", self._el_amplitude))
        self._el_period    = float(d.get("el_period",    self._el_period))
        self._el_direction = d.get("el_direction",        self._el_direction)
        self._bounce_gamma = float(d.get("bounce_gamma", self._bounce_gamma))
        self._bounce_omega = float(d.get("bounce_omega", self._bounce_omega))
        self._bounce_dir   = d.get("bounce_dir",          self._bounce_dir)
        self._catenary_a   = float(d.get("catenary_a",   self._catenary_a))
        self._catenary_reverse = bool(d.get("catenary_reverse", self._catenary_reverse))
        self._pulse_omega1 = float(d.get("pulse_omega1", self._pulse_omega1))
        self._pulse_omega2 = float(d.get("pulse_omega2", self._pulse_omega2))
        self._pulse_n      = float(d.get("pulse_n",      self._pulse_n))
        self._pulse_reverse = bool(d.get("pulse_reverse", self._pulse_reverse))
        self._noise_freq   = float(d.get("noise_freq",   self._noise_freq))
        self._noise_amp    = float(d.get("noise_amp",    self._noise_amp))
        self._noise_seed   = int(d.get("noise_seed",     self._noise_seed))
        self._noise_reverse = bool(d.get("noise_reverse", self._noise_reverse))
        self._res_gamma    = float(d.get("res_gamma",    self._res_gamma))
        self._res_omega    = float(d.get("res_omega",    self._res_omega))
        self._res_omega0   = float(d.get("res_omega0",   self._res_omega0))
        self._res_reverse  = bool(d.get("res_reverse",   self._res_reverse))
        self._steps_n          = int(d.get("steps_n",          self._steps_n))
        self._steps_from_start = bool(d.get("steps_from_start", self._steps_from_start))
        if self._auto_apply and self._comp:
            self._auto_timer.start(280)   # debounce 280 ms
        # Notify dock windows so they can mirror the main window's current curve
        self.curve_state_changed.emit(data_json)
        self._last_curve_json = data_json   # cache for dock init pull

    @Slot(result=str)
    def get_curve_state(self) -> str:
        """Dock windows call this once on init to pull the latest curve state."""
        return getattr(self, '_last_curve_json', '{}')

    @Slot()
    def request_flip(self):
        """Dock's INVERT button: ask the main window to execute flipAll()."""
        self.flip_requested.emit()

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

    @Slot(bool)
    def set_use_playhead(self, enabled: bool):
        """Toggle playhead-driven apply range."""
        self._use_playhead = bool(enabled)
        self._settings["use_playhead"] = self._use_playhead
        try:
            _wj(settings_file(), self._settings)
        except Exception as e:
            log.warning("[Playhead] Could not persist setting: %s", e)
        log.info("[Playhead] Playhead-driven range %s",
                  "enabled" if self._use_playhead else "disabled")

    @Slot(bool)
    def set_precise_playhead(self, enabled: bool):
        """When True, the playhead must be strictly inside a segment.
        When False (default), snaps to the nearest segment if the playhead
        is outside all segment boundaries — more forgiving for quick edits."""
        self._precise_playhead = bool(enabled)
        self._settings["precise_playhead"] = self._precise_playhead
        try:
            _wj(settings_file(), self._settings)
        except Exception as e:
            log.warning("[Playhead] Could not persist precise setting: %s", e)
        log.info("[Playhead] Precise mode %s",
                  "ON" if self._precise_playhead else "OFF (fuzzy snap)")

    def _playhead_segment(self, spline):
        """Find which two consecutive keyframes the playhead currently sits
        between, on THIS spline's own keyframe times (each input can have a
        different keyframe layout, so this is computed per-spline, not once
        per apply). Returns (kf_from, kf_to) as 1-based ordinal indices —
        same convention set_kf_range already uses — or None if the playhead
        isn't inside any segment (before the first keyframe, after the last,
        or fewer than 2 keyframes total)."""
        playhead = None
        try:
            playhead = float(self._comp.GetAttrs().get("COMPN_CurrentTime"))
        except Exception:
            # Fallback: same defensive pattern as undo_resolve/redo_resolve —
            # self._comp may be momentarily stale during a reconnect window.
            try:
                comp = self._fu.GetCurrentComp() if self._fu else None
                if comp:
                    playhead = float(comp.GetAttrs().get("COMPN_CurrentTime"))
            except Exception:
                playhead = None
        if playhead is None:
            log.debug("[Playhead] Could not read current time")
            return None

        try:
            kf = spline.GetKeyFrames()
            times = _numeric_times(kf) if kf else []
        except Exception as e:
            log.debug("[Playhead] GetKeyFrames failed: %s", e)
            times = []
        if len(times) < 2:
            return None

        for i in range(len(times) - 1):
            t0, t1 = float(times[i]), float(times[i + 1])
            if t0 <= playhead <= t1:
                return (i + 1, i + 2)   # 1-based, matches set_kf_range's convention
        return None

    def _playhead_segments(self, spline, scope):
        """Like _playhead_segment but returns a LIST of (kf_from, kf_to) pairs
        according to scope:
          'single'         — only the pair containing the playhead (same as _playhead_segment)
          'playhead_behind'— all pairs from the first to the one containing the playhead
          'playhead_ahead' — all pairs from the one containing the playhead to the last
          'all'            — all consecutive pairs across the full keyframe range
        Returns [] if the playhead is outside all segments (for 'single'/'behind'/'ahead')
        or if there are fewer than 2 keyframes.
        """
        playhead = None
        try:
            playhead = float(self._comp.GetAttrs().get("COMPN_CurrentTime"))
        except Exception:
            try:
                comp = self._fu.GetCurrentComp() if self._fu else None
                if comp:
                    playhead = float(comp.GetAttrs().get("COMPN_CurrentTime"))
            except Exception:
                pass
        try:
            kf = spline.GetKeyFrames()
            times = _numeric_times(kf) if kf else []
        except Exception:
            times = []
        n = len(times)
        if n < 2:
            return []
        all_pairs = [(i + 1, i + 2) for i in range(n - 1)]
        if scope == 'all':
            return all_pairs
        # Find which segment the playhead sits in
        seg_idx = None
        if playhead is not None:
            for i in range(n - 1):
                if float(times[i]) <= playhead <= float(times[i + 1]):
                    seg_idx = i
                    break
        if seg_idx is None:
            if self._precise_playhead or playhead is None:
                return []   # strict mode: playhead must be inside a segment
            # Fuzzy mode (default): snap to the nearest segment boundary.
            # This is the "closest keyframes" behaviour — if the playhead is
            # before the first keyframe we use the first segment; if it's after
            # the last we use the last segment.
            if playhead <= float(times[0]):
                seg_idx = 0
            elif playhead >= float(times[-1]):
                seg_idx = n - 2
            else:
                # Between two non-consecutive keyframes shouldn't happen once
                # the strict loop above runs, but handle it defensively.
                best, best_i = float('inf'), 0
                for i in range(n - 1):
                    mid = (float(times[i]) + float(times[i+1])) / 2
                    d = abs(playhead - mid)
                    if d < best:
                        best, best_i = d, i
                seg_idx = best_i
            log.debug("[Playhead] Fuzzy snap: playhead=%.1f snapped to segment %d→%d",
                      playhead, seg_idx+1, seg_idx+2)
        if scope == 'single':
            return [all_pairs[seg_idx]]
        if scope == 'playhead_behind':
            return all_pairs[:seg_idx + 1]
        if scope == 'playhead_ahead':
            return all_pairs[seg_idx:]
        return [all_pairs[seg_idx]]   # safe fallback

    @Slot(str)
    def apply_curve_playhead(self, scope: str = "single"):
        """Apply the current curve to multiple keyframe segments determined by
        the playhead position and the requested scope (single/playhead_behind/
        playhead_ahead/all). Each spline gets its own segment list computed
        independently so tools with different keyframe layouts all work correctly."""
        self._do_apply(scope=scope)

    @Slot(bool)
    def set_global_hotkey_enabled(self, enabled: bool):
        """Toggle the global Ctrl+R -> Scan All hotkey (Windows only).
        Persists immediately so it survives restarts, and applies live via
        the window's RegisterHotKey/UnregisterHotKey wrapper — no restart
        needed either way."""
        enabled = bool(enabled)
        self._settings["global_scan_hotkey"] = enabled
        try:
            _wj(settings_file(), self._settings)
        except Exception as e:
            log.warning("[Hotkey] Could not persist setting: %s", e)
        try:
            if enabled:
                ok = False
                if self._win is not None and hasattr(self._win, "_register_global_hotkey"):
                    ok = self._win._register_global_hotkey()
                if not ok:
                    self.status_changed.emit(
                        "Global Ctrl+R unavailable here (Windows only, "
                        "or already bound by another app)", "var(--love)")
            else:
                if self._win is not None and hasattr(self._win, "_unregister_global_hotkey"):
                    self._win._unregister_global_hotkey()
        except Exception as e:
            # A failed toggle must never take down Settings or the app —
            # worst case the hotkey silently stays in its previous state.
            log.warning("[Hotkey] Toggle failed: %s", e)

    # ── Presets ───────────────────────────────────────────────────────────────

    @Slot(str)
    def load_library(self, library):
        # ROOT FIX: self._mode used to only change on startup/settings-restore,
        # never when the user switched tabs in the UI (JS calls load_library()
        # directly with the new library, bypassing self._mode entirely). Every
        # internal self.load_library(self._mode) call (new_profile, switch_profile,
        # delete_preset) was therefore often refreshing the WRONG library — whatever
        # tab was active at startup, not whatever the user was actually looking at.
        # Keeping self._mode in sync here, at the single choke point both JS and
        # internal callers go through, fixes all of those at once.
        self._mode = library
        # Reads only this mode's file for the active profile — with the
        # per-profile/per-mode storage layout, this can never pick up (or
        # clobber, on a later save) another mode's presets.
        user = active_presets(self._profiles, library)
        log.debug(
            "[Profile] load_library(%r): active_profile=%r, "
            "user_in_active_profile=%d, total_active_profile_entries=%d",
            library, self._profiles.get("active"), len(user),
            len(active_presets(self._profiles)))
        self.presets_updated.emit(json.dumps(user))

    @Slot(str)
    def save_preset(self, preset_json):
        log.info("[Preset-Save] save_preset Slot invoked — raw=%s", preset_json)
        try:
            p = json.loads(preset_json)
        except Exception as e:
            log.error("[Preset-Save] Could not parse preset JSON from JS: %s", e)
            self.status_changed.emit(f"Save failed: bad data ({e})", "#eb6f92")
            return
        name = p.get("name", "")
        lib = p.get("library", "easing")
        active = self._profiles.get("active", "Default")
        if not name:
            log.warning("[Preset-Save] Preset has empty name — refusing to save. payload=%r", p)
            self.status_changed.emit("Preset needs a name", "var(--gold)")
            return
        log.info("[Preset-Save] Saving name=%r library=%r into profile=%r", name, lib, active)
        self._profiles = add_preset(self._profiles, p)
        # Verify the write actually landed on disk instead of trusting silently.
        on_disk = active_presets(self._profiles, lib)
        found = any(x.get("name") == name for x in on_disk)
        log.info("[Preset-Save] Post-write verification: %d preset(s) now in %s/%s.json — "
                 "target name present=%s", len(on_disk), active, lib, found)
        if not found:
            log.error("[Preset-Save] Write did NOT persist to disk — check file permissions "
                       "for the profiles folder.")
            self.status_changed.emit("Save failed — could not write to disk", "#eb6f92")
        self.load_library(lib)

    @Slot(int)
    def delete_preset(self, idx):
        active = self._profiles.get("active", "Default")
        log.info("[Preset-Delete] delete_preset Slot invoked — idx=%d mode=%r profile=%r",
                 idx, self._mode, active)
        self._profiles, ok = delete_preset(self._profiles, idx, self._mode)
        log.info("[Preset-Delete] result ok=%s — %d preset(s) remain in %s/%s.json",
                 ok, len(active_presets(self._profiles, self._mode)), active, self._mode)
        if not ok:
            self.status_changed.emit("Could not delete preset", "var(--gold)")
        self.load_library(self._mode)

    @Slot(str)
    def new_profile(self, name):
        before_active = self._profiles.get("active")
        before_keys   = list(self._profiles.get("profiles", []))
        self._profiles = new_profile(self._profiles, name.strip())
        after_active = self._profiles.get("active")
        after_keys   = list(self._profiles.get("profiles", []))
        log.debug(
            "[Profile] new_profile(name=%r) — before: active=%r keys=%r | "
            "after: active=%r keys=%r | mode=%r",
            name, before_active, before_keys, after_active, after_keys, self._mode)
        if after_active == before_active and after_keys == before_keys:
            log.warning(
                "[Profile] new_profile(%r) did NOT change state — name empty, "
                "already existed, or collided after strip()", name)
        self._emit_profiles()
        # BUG FIX: this was missing — new_profile() correctly creates an empty
        # list and makes it active on the Python side, but without this call
        # the preset grid in JS never re-fetches, so it kept showing whatever
        # library was last loaded (e.g. Default's presets) even though the
        # new profile really was empty underneath.
        self.load_library(self._mode)

    @Slot(str)
    def delete_profile(self, name):
        before_active = self._profiles.get("active")
        self._profiles = delete_profile(self._profiles, name)
        after_active = self._profiles.get("active")
        log.info("[Profile] delete_profile(%r) — active: %r -> %r", name, before_active, after_active)
        self._emit_profiles()
        # BUG FIX: this call was missing. When the deleted profile was the
        # active one, delete_profile() correctly switches self._profiles["active"]
        # to another profile on the Python side, but without re-fetching here
        # the JS grid (allPresets) kept showing whatever the now-deleted
        # profile's presets were. Those "ghost" cards looked like they
        # belonged to the newly active profile (e.g. Default) since that's
        # what the dropdown now shows — but their index no longer matched any
        # real file, so trying to delete them there silently failed (idx out
        # of range against the real, usually-empty, file). Same class of bug
        # as the one already fixed in new_profile().
        self.load_library(self._mode)

    @Slot(str)
    def switch_profile(self, name):
        self._profiles = switch_profile(self._profiles, name)
        self.load_library(self._mode)

    def _emit_profiles(self):
        self.profiles_updated.emit(json.dumps({
            "names":  list(self._profiles.get("profiles", [])),
            "active": self._profiles.get("active"),
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

    @Slot(bool)
    def set_squash_stretch_enabled(self, enabled: bool):
        self._squash_stretch_enabled = bool(enabled)
        log.info("[SquashStretch] %s", "enabled" if enabled else "disabled")

    @Slot(float)
    def set_squash_stretch_intensity(self, value: float):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return
        self._squash_stretch_intensity = max(0.0, min(3.0, value))

    @Slot(float)
    def set_squash_squash_intensity(self, value: float):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return
        self._squash_squash_intensity = max(0.0, min(3.0, value))

    @Slot(bool)
    def set_squash_invert(self, inverted: bool):
        # There's no reliable way to know from the tool's inputs alone
        # whether "width" or "height" is actually the axis the primary
        # motion is moving along (e.g. a vertical fall should stretch
        # along Y and squash along X, not the other way around) — so
        # rather than guess, this is a simple manual override.
        self._squash_invert = bool(inverted)

    @Slot()
    def undo_resolve(self):
        """Forward Ctrl+Z from MFlow window to Resolve's comp undo.
        Tries self._comp first; falls back to fu.GetCurrentComp() if that
        fails (covers the brief window after watcher disconnect before reconnect)."""
        if self._comp:
            try:
                self._comp.Undo()
                log.debug("[Undo] comp.Undo() OK")
                return
            except Exception as e:
                log.debug("[Undo] comp.Undo() failed (%s) — trying fu fallback", e)
        # Fallback: ask Fusion for the current comp directly
        if self._fu:
            try:
                comp = self._fu.GetCurrentComp()
                if comp:
                    comp.Undo()
                    log.debug("[Undo] comp.Undo() via fu.GetCurrentComp() OK")
                    self._comp = comp   # opportunistically refresh stale ref
            except Exception as e:
                log.debug("[Undo] fu fallback Undo failed: %s", e)

    @Slot()
    def redo_resolve(self):
        """Forward Ctrl+Shift+Z from MFlow window to Resolve's comp redo."""
        if self._comp:
            try:
                self._comp.Redo()
                log.debug("[Redo] comp.Redo() OK")
                return
            except Exception as e:
                log.debug("[Redo] comp.Redo() failed (%s) — trying fu fallback", e)
        if self._fu:
            try:
                comp = self._fu.GetCurrentComp()
                if comp:
                    comp.Redo()
                    log.debug("[Redo] comp.Redo() via fu.GetCurrentComp() OK")
                    self._comp = comp
            except Exception as e:
                log.debug("[Redo] fu fallback Redo failed: %s", e)

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
                # BUG FIX: once Squash & Stretch writes keyframes to a
                # tool's width/height inputs (e.g. TamañoX/TamañoY), the
                # next scan sees them as ordinary animated inputs — so an
                # unfiltered "apply to everything on this tool" (auto-apply,
                # or Apply pressed again) would sweep them up too and
                # overwrite the derived squash/stretch curve with the
                # PRIMARY curve using THEIR OWN endpoints as anchors (which,
                # for an oscillating curve that starts/ends near 1.0, means
                # it collapses back toward ~1.0 — exactly the "reverts to
                # 1.0 a second later" symptom). Excluding them here means
                # they can only ever be written by _apply_squash_stretch
                # itself, never by a blind sweep. Explicit single-input
                # selection (the branch above) is intentionally NOT
                # filtered — if the user deliberately picks that exact
                # input, that's not a blind sweep.
                ss_pair = _resolve_squash_stretch_inputs(tool) if self._squash_stretch_enabled else None
                excluded = {ss_pair[0], ss_pair[1]} if ss_pair else set()
                targets = {k: v for k, v in all_inp.items() if k not in excluded} if excluded else all_inp
                if excluded and not targets:
                    self.apply_done.emit(False,
                        "Only Squash & Stretch's own inputs are animated on this tool \u2014 "
                        "nothing else to apply to")
                    return
            work_items.append((tool, targets))

        applied = 0
        no_spline = 0
        no_segment = 0   # playhead mode: inputs skipped because the playhead
                          # wasn't inside any keyframe segment on that spline
        failed = 0
        tool_names = []
        squash_stretch_msgs = []
        squash_stretch_done_for = set()  # tool ids already handled this apply
        try:
            self._comp.StartUndo("MFlow: Apply")
            self._comp.Lock()
            for tool_obj, inp_dict in work_items:
                tool_names.append(tool_obj.Name)
                for inp_id, meta in inp_dict.items():
                    spline = self._get_spline(meta["input_obj"])
                    if spline is None:
                        no_spline += 1
                        log.warning(f"[MFlow] _do_apply: no BezierSpline for '{inp_id}' on '{tool_obj.Name}'")
                        continue
                    if self._use_playhead:
                        # scope may be 'single','playhead_behind','playhead_ahead','all'
                        ph_scope = scope if scope in (
                            'single','playhead_behind','playhead_ahead','all'
                        ) else 'single'
                        segs = self._playhead_segments(spline, ph_scope)
                        if not segs:
                            no_segment += 1
                            log.info("[Playhead] '%s' on '%s' — playhead not "
                                     "inside a keyframe segment, skipped",
                                     inp_id, tool_obj.Name)
                            continue
                        # Collapse the list of segments into a single contiguous
                        # range (first segment's kf_from → last segment's kf_to)
                        # and issue ONE apply call, not N.  Calling apply_bezier
                        # N times on the same spline accumulates handle mutations
                        # across reads — each call reads back the spline AFTER the
                        # previous write, causing LH/RH offsets to compound and
                        # pushing values out of range (visible as a red node on
                        # PolyPath / normalized parameters).
                        _saved_from, _saved_to = self._kf_from, self._kf_to
                        self._kf_from = segs[0][0]
                        self._kf_to   = segs[-1][1]
                        try:
                            ok = self._apply_one(spline, fps)
                        finally:
                            self._kf_from, self._kf_to = _saved_from, _saved_to
                        if ok:
                            applied += 1
                        else:
                            failed += 1
                    else:
                        ok = self._apply_one(spline, fps)
                        if ok:
                            applied += 1
                        else:
                            failed += 1
                    # Squash & stretch fires once per TOOL (not per input) —
                    # using the first successfully-applied spline on this
                    # tool as the reference to derive velocity from.
                    if ok and self._squash_stretch_enabled and id(tool_obj) not in squash_stretch_done_for:
                        squash_stretch_done_for.add(id(tool_obj))
                        ss_ok, ss_msg = self._apply_squash_stretch(tool_obj, spline, fps)
                        if not ss_ok and ss_msg:
                            squash_stretch_msgs.append(ss_msg)
            self._comp.Unlock()
            self._comp.EndUndo(True)
        except Exception as e:
            try: self._comp.Unlock(); self._comp.EndUndo(True)
            except Exception: pass
            self.apply_done.emit(False, f"Exception: {e}")
            return

        names_str = ", ".join(tool_names) if tool_names else "?"
        ss_suffix = (" \u2014 Squash & Stretch: " + "; ".join(squash_stretch_msgs)) if squash_stretch_msgs else ""
        if applied:
            extra = f" ({no_segment} skipped — playhead outside their keyframe range)" if no_segment else ""
            self.apply_done.emit(True, f"Applied to {applied} input(s) on: {names_str}{extra}{ss_suffix}")
        elif no_segment > 0 and failed == 0 and no_spline == 0:
            self.apply_done.emit(False,
                "Playhead isn't inside a keyframe segment \u2014 move it between "
                "two keyframes on the curve you want to edit, then try again.")
        elif no_spline > 0 and failed == 0:
            self.apply_done.emit(False,
                f"No BezierSpline found on {no_spline} input(s). "
                f"Right-click the parameter in Fusion > Animate to create keyframes first.")
        elif failed > 0:
            self.apply_done.emit(False,
                f"Apply failed on {failed} input(s). "
                f"See mflow.log in your user folder \\.mflow\\ for [MFlow] details.")
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
                                        log.warning(f"[MFlow] _get_spline: PolyPath → Displacement BezierSpline '{sub_tool.Name}'")
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

    def _bake_current_mode_frames(self, spline, fps):
        """Mirrors _apply_one's mode branching, but RETURNS the
        [(frame,value)] representation instead of writing it to Fusion.
        Used only to derive squash & stretch from whatever the primary
        curve currently is — including easing/overframe (bezier-handle)
        modes, which don't otherwise produce a plain frame list at all,
        by sampling eval_bezier the same way the canvas preview does."""
        mode = self._mode
        kf_from, kf_to = self._kf_from, self._kf_to

        if mode in ("easing", "overframe"):
            r = self._bake_range(spline, kf_from=kf_from, kf_to=kf_to)
            if not r:
                return None
            t0, v0, t1, v1 = r
            h1, h2 = self._h1, self._h2
            n = 100
            frames = []
            for i in range(n + 1):
                x = i / n
                y = eval_bezier(x, h1, h2)
                frame = t0 + x * (t1 - t0)
                value = v0 + y * (v1 - v0)
                frames.append((frame, value))
            return frames

        r = self._bake_range(spline, kf_from=kf_from, kf_to=kf_to)
        if not r:
            return None
        t0, v0, t1, v1 = r

        if mode == "elastic":
            if self._el_direction == "out":
                return bake_elastic_out(t0, v0, t1, v1, fps,
                                        amplitude=self._el_amplitude,
                                        period=self._el_period,
                                        flip_to_mid=self._phys_flipped,
                                        density=self._bake_density)
            return bake_elastic_penner(t0, v0, t1, v1, fps,
                                       amplitude=self._el_amplitude,
                                       period=self._el_period,
                                       flip_to_mid=self._phys_flipped,
                                       density=self._bake_density)
        if mode in ("spring", "bounce_osc"):
            return bake_oscillator(t0, v0, t1, v1, fps,
                                   zeta=self._phys_zeta,
                                   omega_n=self._phys_omega_n,
                                   density=self._bake_density)
        if mode == "bounce":
            return bake_bounce(t0, v0, t1, v1, fps,
                               gamma=self._bounce_gamma,
                               omega=self._bounce_omega,
                               flipped=(self._bounce_dir == "floor"),
                               density=self._bake_density)
        if mode == "catenary":
            return bake_catenary(t0, v0, t1, v1, fps, a=self._catenary_a,
                                 reverse=self._catenary_reverse,
                                 density=self._bake_density)
        if mode == "pulse":
            return bake_pulse(t0, v0, t1, v1, fps,
                              omega1=self._pulse_omega1,
                              omega2=self._pulse_omega2,
                              n=self._pulse_n,
                              reverse=self._pulse_reverse,
                              density=self._bake_density)
        if mode == "noise":
            return bake_noise(t0, v0, t1, v1, fps,
                              freq=self._noise_freq,
                              amp=self._noise_amp,
                              seed=self._noise_seed,
                              reverse=self._noise_reverse,
                              density=self._bake_density)
        if mode == "resonance":
            return bake_resonance(t0, v0, t1, v1, fps,
                                  gamma=self._res_gamma,
                                  omega=self._res_omega,
                                  omega0=self._res_omega0,
                                  reverse=self._res_reverse,
                                  density=self._bake_density)
        return None

    def _apply_squash_stretch(self, tool, primary_spline, fps):
        """Applies squash & stretch to `tool`'s width/height inputs,
        derived from the SAME curve configuration as the normal apply
        (same mode, params, and kf_from/kf_to range), using
        primary_spline to derive velocity from.

        REQUIRES both target inputs to already have at least 2 keyframes
        set manually in Fusion first — matching what MFlow already
        assumes everywhere else (reshape existing animation, never
        create it from scratch). A live test against a real Transform
        confirmed that assigning a fresh comp.BezierSpline({...}) to a
        previously-static input doesn't reliably create a working spline
        in this environment (only the first keyframe stuck; a second
        attempt raised TypeError) — so that path is deliberately never
        attempted here. If either input has no spline yet, this fails
        with a clear, actionable message instead.

        Must be called from inside the same StartUndo/Lock block as the
        primary apply, so a single Ctrl+Z undoes everything together.

        Returns (ok: bool, message: str|None) — message is set on any
        failure, None on clean success.
        """
        resolved = _resolve_squash_stretch_inputs(tool)
        if resolved is None:
            return False, f"Squash & stretch isn't available for '{tool.Name}' (no recognized size inputs)"
        width_id, height_id, lock_id = resolved

        try:
            by_id_obj = {}
            for inp in tool.GetInputList().values():
                iid = inp.GetAttrs().get("INPS_ID", "")
                if iid:
                    by_id_obj[iid] = inp
        except Exception as e:
            return False, f"Could not read '{tool.Name}'\u2019s inputs: {e}"

        width_inp  = by_id_obj.get(width_id)
        height_inp = by_id_obj.get(height_id)
        if width_inp is None or height_inp is None:
            return False, f"Squash & stretch inputs not found on '{tool.Name}'"

        width_spline  = self._get_spline(width_inp)
        height_spline = self._get_spline(height_inp)
        if width_spline is None or height_spline is None:
            missing = [i for i, s in ((width_id, width_spline), (height_id, height_spline)) if s is None]
            return False, (f"Add at least 2 keyframes to {' and '.join(missing)} "
                            f"on '{tool.Name}' first, then try Squash & Stretch again")

        if lock_id:
            try:
                cur = tool.GetInput(lock_id)
                if cur:
                    tool.SetInput(lock_id, 0)
                    log.info("[SquashStretch] Unlocked %s on '%s'", lock_id, tool.Name)
            except Exception as e:
                log.warning("[SquashStretch] Could not unlock %s on '%s': %s", lock_id, tool.Name, e)

        frames = self._bake_current_mode_frames(primary_spline, fps)
        if not frames:
            return False, "Could not derive a curve to base squash & stretch on"

        stretch_frames, squash_frames = derive_squash_stretch(
            frames, stretch_intensity=self._squash_stretch_intensity,
            squash_intensity=self._squash_squash_intensity)
        if self._squash_invert:
            stretch_frames, squash_frames = squash_frames, stretch_frames
        t_start, t_end = frames[0][0], frames[-1][0]

        ok1 = apply_baked(width_spline, stretch_frames, t_start=t_start, t_end=t_end)
        ok2 = apply_baked(height_spline, squash_frames, t_start=t_start, t_end=t_end)
        if not (ok1 and ok2):
            return False, f"Squash & stretch partially failed writing keyframes on '{tool.Name}'"
        return True, None

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

        if mode == "steps":
            # Special-cased like easing/overframe above: true flat plateaus
            # with hard jumps can't be represented as a sampled frame array
            # fed through the generic apply_baked() — see apply_steps_kf's
            # own docstring for why.
            return apply_steps_kf(spline, t0, v0, t1, v1,
                                  n_steps=self._steps_n,
                                  from_start=self._steps_from_start)
        if mode == "elastic":
            if self._el_direction == "out":
                frames = bake_elastic_out(t0, v0, t1, v1, fps,
                                          amplitude=self._el_amplitude,
                                          period=self._el_period,
                                          flip_to_mid=self._phys_flipped,
                                          density=self._bake_density)
            else:
                frames = bake_elastic_penner(t0, v0, t1, v1, fps,
                                             amplitude=self._el_amplitude,
                                             period=self._el_period,
                                             flip_to_mid=self._phys_flipped,
                                             density=self._bake_density)
            return apply_baked(spline, frames, t_start=t0, t_end=t1)
        if mode in ("spring", "bounce_osc"):
            frames = bake_oscillator(t0, v0, t1, v1, fps,
                                     zeta=self._phys_zeta,
                                     omega_n=self._phys_omega_n,
                                     density=self._bake_density)
            return apply_baked(spline, frames, t_start=t0, t_end=t1)
        if mode == "bounce":
            frames = bake_bounce(t0, v0, t1, v1, fps,
                                 gamma=self._bounce_gamma,
                                 omega=self._bounce_omega,
                                 flipped=(self._bounce_dir == "floor"),
                                 density=self._bake_density)
            return apply_baked(spline, frames, t_start=t0, t_end=t1)
        if mode == "catenary":
            frames = bake_catenary(t0, v0, t1, v1, fps, a=self._catenary_a,
                                   reverse=self._catenary_reverse,
                                   density=self._bake_density)
            return apply_baked(spline, frames, t_start=t0, t_end=t1)
        if mode == "pulse":
            frames = bake_pulse(t0, v0, t1, v1, fps,
                                omega1=self._pulse_omega1,
                                omega2=self._pulse_omega2,
                                n=self._pulse_n,
                                reverse=self._pulse_reverse,
                                density=self._bake_density)
            return apply_baked(spline, frames, t_start=t0, t_end=t1)
        if mode == "noise":
            frames = bake_noise(t0, v0, t1, v1, fps,
                                freq=self._noise_freq,
                                amp=self._noise_amp,
                                seed=self._noise_seed,
                                reverse=self._noise_reverse,
                                density=self._bake_density)
            return apply_baked(spline, frames, t_start=t0, t_end=t1)
        if mode == "resonance":
            frames = bake_resonance(t0, v0, t1, v1, fps,
                                    gamma=self._res_gamma,
                                    omega=self._res_omega,
                                    omega0=self._res_omega0,
                                    reverse=self._res_reverse,
                                    density=self._bake_density)
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
        self._bake_density = max(1, int(self._settings.get("bake_density", 1)))
        self._use_playhead = bool(self._settings.get("use_playhead", True))
        self._precise_playhead = bool(self._settings.get("precise_playhead", False))
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
                # QTimer.singleShot from a QRunnable thread has no event loop;
                # use the internal signal for guaranteed main-thread delivery.
                backend_ref._scan_done_sig.emit(result)

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
        _wkw = win_subprocess_kwargs()  # suppresses spontaneous console windows on Windows

        def _probe(exe):
            try:
                r = sp.run([exe, "--version"], capture_output=True, text=True, timeout=5, **_wkw)
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
                               capture_output=True, text=True, timeout=5, **_wkw)
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

    @Slot(str)
    def reorder_presets(self, presets_json: str):
        """Replace the active profile's preset list *for the current mode
        only* with the given JSON array (used by the sort menu so no
        duplicates are created).

        BUG FIX: this used to overwrite self._profiles["profiles"][active] —
        which held every mode's presets mixed into one flat list — with just
        the current mode's presets from JS. Sorting in any one tab silently
        deleted every preset saved under every OTHER mode in that profile.
        With per-mode storage, this call can only ever touch self._mode's
        own file, so that data loss is no longer possible."""
        try:
            presets = json.loads(presets_json)
            if not isinstance(presets, list):
                return
            self._profiles = _reorder_presets_lib(self._profiles, self._mode, presets)
            self.load_library(self._mode)
        except Exception as e:
            log.warning("[Preset] reorder_presets failed: %s", e)

    @Slot()
    def export_presets_dialog(self):
        """Open a Save File dialog to export user presets for the active library."""
        presets = active_presets(self._profiles, self._mode)
        if not presets:
            self.status_changed.emit("No user presets to export", "var(--muted)")
            return
        path, _ = QFileDialog.getSaveFileName(
            None, "Export Presets",
            f"MFlow_presets_{self._mode}.json", "JSON (*.json)")
        if not path:
            return
        try:
            _wj(path, presets)
            self.status_changed.emit(f"Presets exported: {path}", "#9ccfd8")
        except Exception as e:
            self.status_changed.emit(f"Export failed: {e}", "#eb6f92")

    @Slot()
    def import_presets_dialog(self):
        """Open a file dialog to import presets from a JSON file."""
        path, _ = QFileDialog.getOpenFileName(
            None, "Import Presets", "", "JSON (*.json)")
        if not path:
            return
        try:
            data = _rj(path)
            if not isinstance(data, list):
                self.status_changed.emit("Invalid preset file", "#eb6f92")
                return
            for p in data:
                if isinstance(p, dict) and p.get("name"):
                    self._profiles = add_preset(self._profiles, p)
            self.load_library(self._mode)
            self.status_changed.emit(f"Imported {len(data)} preset(s)", "#9ccfd8")
        except Exception as e:
            self.status_changed.emit(f"Import failed: {e}", "#eb6f92")

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



