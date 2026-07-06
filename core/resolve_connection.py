"""
Resolve connection and live watcher (undo-stack strategy from friend's script).
All API calls stay on the main thread — watcher uses QTimer, never QThread.

Exception: the very first connection bootstrap (get_resolve_with_timeout /
get_comp_with_timeout below) runs in a short-lived daemon thread purely to
enforce a hard time limit. That's a startup-only safety net, not a change to
the "Fusion API calls happen on the main thread" rule the ongoing watcher
follows — see the docstring on _run_with_timeout for why it's safe here
specifically.
"""
import importlib, importlib.util, os, sys, time, logging, threading
from PySide6.QtCore import QObject, QTimer, Signal
from core.platform_config import resolve_module_paths, fusionscript_path

# Thresholds (ms) for the perf instrumentation below — tuned to only log
# calls that are slow enough to be perceptible (a 500ms-cadence timer
# blocking the main thread for >30ms starts eating into frame budget;
# >150ms is squarely in "visible stall / flicker" territory).
_SLOW_MS  = 30
_VSLOW_MS = 150


def _run_with_timeout(fn, args=(), timeout=6.0, name="worker"):
    """Runs fn(*args) in a daemon thread and waits at most `timeout` seconds.

    Why this is safe here even though the rest of this module insists Fusion
    API calls stay on the main thread: this helper is only ever used for the
    ONE-TIME startup bootstrap (get_resolve/get_comp), before any comp,
    watcher, or UI exists yet — there is no concurrent main-thread Fusion
    call it could race with. Once a comp is obtained, everything else in
    this file (ResolveWatcher) goes back to calling the API exclusively from
    the main thread via QTimer, as documented at the top of this file.

    Python threads can't be force-killed, so if fn() really is stuck forever
    (e.g. a dead scripting socket that never responds), the thread leaks for
    the process lifetime — but it's a daemon thread, so it can never block
    interpreter shutdown, and this call always returns within `timeout`
    seconds regardless. A bounded wait that might leak one idle thread is a
    strictly better trade than an unbounded hang that kills the whole app
    before a window is even shown.

    Returns (value, error, timed_out). Exactly one of (value being usable) /
    (error being not None) / (timed_out being True) describes the outcome.
    """
    log = logging.getLogger("mflow")
    box = {"value": None, "error": None, "done": False}

    def _worker():
        try:
            box["value"] = fn(*args)
        except Exception as e:
            box["error"] = e
        finally:
            box["done"] = True

    try:
        t = threading.Thread(target=_worker, name=f"MFlow-{name}", daemon=True)
        t.start()
        t.join(timeout)
    except Exception as e:
        # Even starting/joining a thread should never be able to take the
        # app down — fail safe as if it simply timed out.
        log.warning("[%s] Could not run with timeout guard: %s", name, e)
        return None, None, True

    if not box["done"]:
        log.warning("[%s] Timed out after %.1fs — continuing without it. "
                    "(The attempt keeps running in the background as an "
                    "orphaned daemon thread and its result will be discarded.)",
                    name, timeout)
        return None, None, True
    if box["error"] is not None:
        log.warning("[%s] Raised: %s", name, box["error"])
        return None, box["error"], False
    return box["value"], None, False


def get_resolve(custom_path: str = ""):
    """
    Obtain the Resolve scripting object, handling multiple-Python-version conflicts.
    Strips Microsoft Store App Execution Aliases from PATH, clears stale imports,
    adds Resolve DLL directory before importing.
    """
    import logging
    log = logging.getLogger("mflow")

    if sys.platform == "win32":
        parts = os.environ.get("PATH", "").split(os.pathsep)
        os.environ["PATH"] = os.pathsep.join(
            p for p in parts if
            "WindowsApps" not in p and
            "windowsapps" not in p.lower()
        )
        resolve_dirs = [
            r"C:\Program Files\Blackmagic Design\DaVinci Resolve",
            r"C:\Program Files (x86)\Blackmagic Design\DaVinci Resolve",
        ]
        for rdir in resolve_dirs:
            if os.path.isdir(rdir):
                log.info("[get_resolve] Found Resolve dir: %s", rdir)
                if rdir not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = rdir + os.pathsep + os.environ["PATH"]
                try: os.add_dll_directory(rdir)
                except (AttributeError, OSError): pass
                break
        else:
            log.warning("[get_resolve] Resolve install dir not found in standard locations")

    import builtins
    from collections import OrderedDict as _OD
    if not hasattr(builtins, "OrderedDict"):
        builtins.OrderedDict = _OD

    # Force-remove cached module so Python re-imports fresh on each attempt
    for _k in ("DaVinciResolveScript", "fusionscript"):
        if _k in sys.modules:
            log.debug("[get_resolve] Removing stale sys.modules['%s']", _k)
        sys.modules.pop(_k, None)

    search_paths = resolve_module_paths(custom_path)
    log.info("[get_resolve] Module search paths: %s", search_paths)
    for p in search_paths:
        if os.path.isdir(p):
            log.debug("[get_resolve] Adding to sys.path: %s", p)
            if p not in sys.path:
                sys.path.insert(0, p)
        else:
            log.debug("[get_resolve] Path does not exist: %s", p)

    # Method 1: DaVinciResolveScript module (preferred)
    try:
        import DaVinciResolveScript as _dvr  # noqa
        log.info("[get_resolve] DaVinciResolveScript imported OK")
        r = _dvr.scriptapp("Resolve")
        if r:
            log.info("[get_resolve] scriptapp('Resolve') returned object — connected")
            return r
        log.warning("[get_resolve] scriptapp('Resolve') returned None — "
                    "Resolve is not running OR External Scripting is not set to Local.\n"
                    "  Fix: DaVinci Resolve > Preferences > System > General > "
                    "External scripting using = Local")
    except ImportError as e:
        log.warning("[get_resolve] DaVinciResolveScript import failed: %s", e)
        log.warning("[get_resolve] Searched paths: %s", search_paths)
    except Exception as e:
        log.error("[get_resolve] Unexpected error importing DaVinciResolveScript: %s", e,
                  exc_info=True)

    # Method 2: fusionscript DLL direct load
    fsp = fusionscript_path()
    log.info("[get_resolve] fusionscript path: %s", fsp or "(not found)")
    if fsp:
        try:
            spec = importlib.util.spec_from_file_location("fusionscript", fsp)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                r = mod.scriptapp("Resolve")
                if r:
                    log.info("[get_resolve] fusionscript fallback succeeded")
                    return r
                log.warning("[get_resolve] fusionscript.scriptapp('Resolve') returned None")
        except Exception as e:
            log.warning("[get_resolve] fusionscript fallback failed: %s", e)

    log.warning("[get_resolve] All methods failed — returning None")
    return None



def get_comp(resolve):
    try:
        f = resolve.Fusion()
        if not f:
            return None
        # CurrentComp works in both Free and Studio
        # GetCurrentComp() fails silently in Free
        comp = getattr(f, "CurrentComp", None)
        if comp is None:
            comp = f.GetCurrentComp()
        return comp
    except Exception:
        return None


def get_resolve_with_timeout(custom_path: str = "", timeout: float = 6.0):
    """Bounded version of get_resolve() for use at app startup, before any
    window exists. If DaVinci was closed uncleanly and left a stale
    scripting socket behind, scriptapp("Resolve") can hang indefinitely
    waiting for a response that will never come — which previously meant
    the whole app appeared to die on launch with no window, no error,
    nothing. Standalone installs (no guarantee Resolve is even installed,
    let alone running cleanly) need this guaranteed not to happen.
    See _run_with_timeout for exactly why running this one bootstrap call
    off the main thread is safe."""
    value, _err, timed_out = _run_with_timeout(
        get_resolve, args=(custom_path,), timeout=timeout, name="get_resolve")
    if timed_out:
        logging.getLogger("mflow").warning(
            "[get_resolve] Continuing in standalone mode after timeout.")
    return value


def get_comp_with_timeout(resolve, timeout: float = 4.0):
    """Bounded version of get_comp() — see get_resolve_with_timeout. Lower
    risk than get_resolve (resolve is already confirmed live at this point)
    but guarded with the same mechanism for consistency: a single hung call
    here shouldn't be able to take the whole app down either."""
    value, _err, timed_out = _run_with_timeout(
        get_comp, args=(resolve,), timeout=timeout, name="get_comp")
    return value


def _probe_worker(custom_path, queue):
    """Runs in a genuinely separate OS process (see probe_resolve_connection
    for why). Only ever used to test whether get_resolve() currently
    responds — the resolve object it obtains is a native handle tied to
    THIS process and cannot be sent back across the process boundary, so
    this just reports success/failure. If it reports success, the caller
    then makes its OWN get_resolve() call directly, now with much higher
    confidence it won't hang."""
    try:
        r = get_resolve(custom_path)
        queue.put(("ok", bool(r)))
    except Exception as e:
        queue.put(("error", str(e)))


def probe_resolve_connection(custom_path: str = "", timeout: float = 6.0) -> bool:
    """Tests whether get_resolve() currently responds, using a real separate
    process instead of a thread.

    Why this exists: get_resolve_with_timeout() (the thread-based guard)
    turned out to be insufficient in the field — confirmed by a real hang
    that outlasted its timeout and required force-killing the app. The
    likely cause: if the native fusionscript call blocks on its IPC wait
    WITHOUT releasing Python's GIL, every thread in the process freezes
    with it — including the thread that was supposed to be enforcing the
    timeout, since the GIL itself becomes unavailable to it. A thread
    timeout cannot recover from that under any circumstances; the call
    truly never returns control to Python.

    A separate OS process has its own GIL entirely. If it hangs, this
    function's terminate()/kill() is a real, unconditional OS-level kill —
    it works regardless of what the child is stuck doing internally, no
    cooperation from the stuck code required.

    Returns True only if the probe process cleanly reported success within
    `timeout` seconds. On any failure, timeout, or even a problem with the
    probing mechanism itself, this fails CLOSED (returns False) — for a
    standalone install, "occasionally slower to notice Resolve is running"
    is a far better trade than "occasionally hangs the whole app again"."""
    log = logging.getLogger("mflow")
    try:
        import multiprocessing
        ctx = multiprocessing.get_context("spawn")
        q = ctx.Queue()
        p = ctx.Process(target=_probe_worker, args=(custom_path, q), daemon=True)
        p.start()
        p.join(timeout)
        if p.is_alive():
            log.warning("[get_resolve] Probe process unresponsive after %.1fs — "
                        "terminating it and continuing in standalone mode.", timeout)
            try:
                p.terminate()
                p.join(2.0)
                if p.is_alive():
                    p.kill()
                    p.join(1.0)
            except Exception as e:
                log.debug("[get_resolve] Could not terminate probe process cleanly: %s", e)
            return False
        if not q.empty():
            kind, val = q.get()
            if kind == "ok":
                return bool(val)
            log.warning("[get_resolve] Probe process reported an error: %s", val)
            return False
        log.warning("[get_resolve] Probe process exited without a result (exit code %s)",
                    p.exitcode)
        return False
    except Exception as e:
        log.warning("[get_resolve] Connection probe unavailable (%s) — "
                    "skipping real attempt this launch, staying standalone.", e)
        return False


# ── Resolve process liveness check ────────────────────────────────────────────
# Best-effort, deliberately cheap: the DaVinci scripting bridge can hang
# indefinitely on a call into a dead/closing Resolve process rather than
# raising promptly (a stale socket with nothing on the other end doesn't
# always fail fast). Since a genuine hang can't be caught by try/except —
# the calling thread just never comes back — the only way to avoid it is to
# not make the call in the first place once Resolve is confirmed gone.
# Cached with a short TTL so this never runs on every single 500ms poll
# tick (spawning a process that often would trade one performance problem
# for another); result defaults to "assume alive" on any failure/unknown
# platform so this can only ever reduce hang risk, never invent a false
# disconnect.
_PROC_CHECK_NAMES = {
    "win32":  ["Resolve.exe"],
    "darwin": ["DaVinci Resolve"],
}
_PROC_CHECK_CACHE = {"alive": True, "ts": 0.0}
_PROC_CHECK_TTL   = 3.0  # seconds


def _is_resolve_process_alive() -> bool:
    now = time.monotonic()
    if now - _PROC_CHECK_CACHE["ts"] < _PROC_CHECK_TTL:
        return _PROC_CHECK_CACHE["alive"]
    alive = True  # fail-safe default: assume alive so this can never be the
                  # sole cause of a false "disconnected"
    try:
        import subprocess
        if sys.platform == "win32":
            names = _PROC_CHECK_NAMES["win32"]
            out = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {names[0]}"],
                capture_output=True, text=True, timeout=1.5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            alive = names[0].lower() in (out.stdout or "").lower()
        elif sys.platform == "darwin":
            out = subprocess.run(
                ["pgrep", "-f", _PROC_CHECK_NAMES["darwin"][0]],
                capture_output=True, text=True, timeout=1.5)
            alive = bool((out.stdout or "").strip())
        else:
            # Linux: DaVinci's launcher process is typically lowercase.
            out = subprocess.run(
                ["pgrep", "-if", "resolve"],
                capture_output=True, text=True, timeout=1.5)
            alive = bool((out.stdout or "").strip())
    except Exception as e:
        # Check itself failed (no tasklist/pgrep, sandboxed env, etc.) —
        # assume alive rather than risk a false disconnect over a check
        # that isn't even working.
        logging.getLogger("mflow").debug(
            "[Watcher] Process liveness check unavailable (assuming alive): %s", e)
        alive = True
    _PROC_CHECK_CACHE["alive"] = alive
    _PROC_CHECK_CACHE["ts"] = now
    return alive


def warmup_fusion_api(comp) -> None:
    """Best-effort warm-up of the Python<->Fusion scripting bridge.

    The first *write*-side call Fusion's scripting API makes in a session
    (SetKeyFrames, SetData, ...) can behave differently from later ones —
    e.g. a call that doesn't raise an exception can still silently drop
    part of what it was asked to write (this is what caused the "first
    Apply only updates one handle" bug in the curve engine). Rather than
    let the user's first real Apply click be that first write, this sends
    one harmless, side-effect-free write-side call — comp.Lock()/Unlock() —
    right after connecting, so the bridge is already warm by the time the
    curve engine touches a real spline.

    Lock()/Unlock() is Fusion's own documented pattern for bracketing batch
    node edits; called on its own with no edits in between, it changes
    nothing about the comp — it only exercises the same write-capable API
    path. This is intentionally silent and non-fatal: if it fails for any
    reason (older API surface, unusual node graph, etc.) that's fine, it
    was only ever a defensive optimization, never a requirement.
    """
    if comp is None:
        return
    locked = False
    try:
        comp.Lock()
        locked = True
    except Exception:
        pass
    if locked:
        try:
            comp.Unlock()
        except Exception:
            pass


class ResolveWatcher(QObject):
    """
    Polls the active Fusion comp every 500 ms for tool/undo changes.
    A separate 1500 ms timer independently detects when the user switches
    to a different comp in Resolve (powers the auto-follow feature).
    """
    tool_changed       = Signal(str, dict)
    disconnected       = Signal()
    comp_scan_updated  = Signal(dict)
    comp_changed       = Signal()   # user opened a different comp in Resolve

    def __init__(self, comp, fu=None, parent=None):
        super().__init__(parent)
        self._comp           = comp
        self._fu             = fu       # Fusion object — needed for comp-identity check
        self._last_name      = ""
        self._last_undo      = 0
        self._cached_inputs  = {}
        # Per-tool memoization: avoids re-scanning a tool's animated inputs
        # (up to 6 IPC round-trips per input) every time you click back onto
        # a tool you've already visited. Cleared whenever undo_changed fires,
        # since we can't cheaply know *which* tool the undo/redo affected.
        self._input_cache    = {}
        self._selected_input = None
        self._comp_name      = self._get_comp_attr_name()   # stable name for comparison

        self._poll_fail_count = 0           # consecutive poll failures
        self._comp_fp = self._quick_fp(comp)  # fingerprint for comp-change detection

        # Set true while the user is actively dragging something in the
        # canvas (curve handles, physics parameter draggers). _poll() skips
        # its body entirely while this is set — see set_interacting() below
        # for why this matters: a single ActiveTool property read routinely
        # costs 150-240ms of IPC round-trip on the main thread (confirmed
        # via [PERF] logging), and if that lands mid-drag it visibly stutters
        # the exact interaction the user is in the middle of.
        self._interacting = False
        # Safety net: if a mouseup is ever missed (e.g. the OS window loses
        # focus mid-drag and the browser-side mouseup never fires), this
        # guarantees polling resumes anyway instead of silently staying
        # paused forever.
        self._interacting_timeout = QTimer(self)
        self._interacting_timeout.setSingleShot(True)
        self._interacting_timeout.timeout.connect(self._force_clear_interacting)

        # Set false while the MFlow window doesn't have OS-level focus (the
        # user is working in Resolve's own viewport, or any other app).
        # _poll() skips its body while this is false — same ~150-240ms
        # ActiveTool cost as above, just spent continuously in the
        # background for no benefit while nobody is even looking at MFlow.
        # Defaults True so nothing changes until main.py starts reporting
        # real focus state via QApplication.applicationStateChanged.
        # Deliberately independent of the manual Ctrl+R global hotkey path
        # (Backend.scan_comp()) — that one must keep working regardless of
        # focus, since "works without window focus" is its whole purpose.
        self._focused = True

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

        self._scan_cooldown = QTimer(self)
        self._scan_cooldown.setSingleShot(True)
        self._scan_cooldown.setInterval(2500)
        self._scan_cooldown.timeout.connect(self.scan_all_tools)

        # Independent comp-switch detector — slower cadence to keep IPC light
        self._comp_timer = QTimer(self)
        self._comp_timer.timeout.connect(self._comp_check)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _get_comp_attr_name(self) -> str:
        """Return a stable string name for self._comp (cheap — uses GetAttrs)."""
        try:
            attrs = self._comp.GetAttrs()
            return attrs.get("COMPS_FileName") or attrs.get("COMPS_Name") or ""
        except Exception:
            return ""

    def _quick_fp(self, comp) -> str:
        """
        Fast fingerprint for comp-change detection using clip attributes.
        Uses COMPN_GlobalEnd + COMPN_FPS + COMPS_FileName — these are set by the
        clip and are STABLE: they do not change when tools are added/removed within
        the same comp (unlike GetToolList which triggered false positives).
        One GetAttrs IPC call, only from _comp_check (every 1500 ms).
        """
        try:
            attrs = comp.GetAttrs()
            end  = round(attrs.get("COMPN_GlobalEnd", -1), 3)
            fps  = round(attrs.get("COMPN_FPS", 0), 4)
            name = attrs.get("COMPS_FileName") or attrs.get("COMPS_Name") or ""
            key  = f"{end}:{fps}:{name}"
            # Return empty if all fields are defaults (unreadable comp)
            return key if key != "-1.0:0.0:" else ""
        except Exception:
            return ""

    def _comp_check(self):
        """Periodic check: has the user switched to a different comp in Resolve?"""
        if not self._fu:
            return
        _t0 = time.perf_counter()
        try:
            current = self._fu.GetCurrentComp()
            if not current:
                return
            current_fp = self._quick_fp(current)
            # Only fire if fingerprint is non-empty AND different from stored one.
            # COMPS_FileName/COMPS_Name are empty for timeline comps so we use
            # tool-name fingerprints which ARE reliable across IPC.
            if current_fp and current_fp != self._comp_fp:
                logging.getLogger("mflow").debug(
                    "[Watcher] _comp_check: fp changed '%s' → '%s'",
                    self._comp_fp, current_fp)
                self.comp_changed.emit()
        except Exception:
            pass
        finally:
            _ms = (time.perf_counter() - _t0) * 1000
            if _ms > _SLOW_MS:
                lvl = logging.WARNING if _ms > _VSLOW_MS else logging.INFO
                logging.getLogger("mflow").log(
                    lvl, "[PERF] _comp_check took %.1fms (main thread blocked)", _ms)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        self._last_undo = self._undo_len()
        self._timer.start(self.POLL_MS)
        if self._fu:
            self._comp_timer.start(1500)

    def stop(self):
        self._timer.stop()
        self._comp_timer.stop()

    def force_refresh(self):
        try:
            t = self._comp.ActiveTool
            if t:
                self._emit(t)
        except Exception:
            pass

    def get_selected_spline(self):
        """Return the BezierSpline connected to the currently selected input."""
        if not self._selected_input:
            return None, None
        _, inp_id = self._selected_input
        try:
            tool = self._comp.ActiveTool
            if not tool:
                return None, None
            inputs = self._animated_inputs(tool)
            meta = inputs.get(inp_id)
            if not meta:
                return None, None
            return tool, meta.get("input_obj")
        except Exception:
            return None, None

    def get_all_splines(self):
        """Return list of (inp_id, input_obj) for all animated inputs on active tool."""
        try:
            tool = self._comp.ActiveTool
            if not tool:
                return []
            return [(k, v["input_obj"]) for k, v in self._animated_inputs(tool).items()]
        except Exception:
            return []

    def scan_all_tools(self):
        """
        Scan every tool in the comp and emit comp_scan_updated with all
        animated inputs found.  Called explicitly (never in the poll loop)
        so it doesn't affect normal poll performance.
        Returns the result dict as well for immediate use.
        """
        _t0 = time.perf_counter()
        result = {}
        tool_count = 0
        try:
            tool_list = self._comp.GetToolList(False)  # False = all tools, not just selected
            if not tool_list:
                return result
            tool_count = len(tool_list)
            for tool in tool_list.values():
                try:
                    name = tool.Name
                    inputs = self._animated_inputs(tool)
                    if inputs:
                        result[name] = inputs
                except Exception:
                    pass
        except Exception:
            pass
        _ms = (time.perf_counter() - _t0) * 1000
        lvl = logging.WARNING if _ms > _VSLOW_MS else logging.INFO
        logging.getLogger("mflow").log(
            lvl,
            "[PERF] scan_all_tools took %.1fms — %d tools scanned, "
            "%d with animated inputs — main thread blocked",
            _ms, tool_count, len(result))
        self.comp_scan_updated.emit(result)
        return result

    # ── internals ─────────────────────────────────────────────────────────────

    def _undo_len(self) -> int:
        try:
            return len(self._comp.GetUndoStack())
        except Exception:
            return self._last_undo

    POLL_MS = 500  # slower poll reduces CPU

    def set_interacting(self, active: bool):
        """Called from Backend.set_interacting() (wired to JS drag start/end).
        While active, _poll() returns immediately without touching the
        Fusion API at all — no IPC calls means no chance of the ~150-240ms
        ActiveTool round-trip landing in the middle of a drag gesture."""
        self._interacting = bool(active)
        if self._interacting:
            self._interacting_timeout.start(5000)  # safety net — see __init__ comment
        else:
            self._interacting_timeout.stop()

    def _force_clear_interacting(self):
        if self._interacting:
            logging.getLogger("mflow").debug(
                "[Watcher] interacting flag force-cleared after timeout (missed mouseup?)")
            self._interacting = False

    def set_focused(self, focused: bool):
        """Called from main.py's QApplication.applicationStateChanged
        handler. Pausing polling while MFlow isn't the active window means
        no ActiveTool/GetUndoStack cost is paid at all while the user is
        working in Resolve's own viewport — that cost was previously being
        spent continuously for a UI nobody was even looking at."""
        self._focused = bool(focused)

    def _poll(self):
        if self._interacting or not self._focused:
            return
        _t0 = time.perf_counter()
        _t_active = _t_undo = _t_scan = None
        if not _is_resolve_process_alive():
            # Resolve is confirmed gone at the OS level — treat exactly like
            # 3 consecutive IPC failures would, without risking a hang by
            # attempting the call anyway.
            self._poll_fail_count += 1
            logging.getLogger("mflow").debug(
                "[Watcher] Resolve process not found (%d/3 consecutive)", self._poll_fail_count)
            if self._poll_fail_count >= 3:
                logging.getLogger("mflow").warning(
                    "[Watcher] Resolve process gone — emitting disconnected")
                self.disconnected.emit()
                self._timer.stop()
            return
        try:
            active = self._comp.ActiveTool
            _t_active = time.perf_counter()
            name   = active.Name if active else ""
            undo   = self._undo_len()
            _t_undo = time.perf_counter()
            self._poll_fail_count = 0   # reset on any successful IPC call
            name_changed = (name != self._last_name)
            undo_changed = (undo != self._last_undo)
            if name_changed or undo_changed:
                self._last_name = name
                self._last_undo = undo
                if undo_changed:
                    # Restart cooldown — scan fires 2.5s after last change
                    self._scan_cooldown.start()
                    # Can't tell which tool an undo/redo touched, so drop the
                    # whole memoization to stay correct — this trades a little
                    # of the caching win on undo-heavy sessions for guaranteed
                    # freshness.
                    self._input_cache.clear()
                if active:
                    # Re-scan only if we've never seen this tool since the
                    # last invalidation — revisiting a tool you already
                    # clicked (e.g. flipping between two nodes to compare
                    # keyframes) is then a free dict lookup instead of a
                    # fresh IPC round-trip per input.
                    if name not in self._input_cache:
                        self._input_cache[name] = self._animated_inputs(active)
                        _t_scan = time.perf_counter()
                    self._cached_inputs = self._input_cache[name]
                    self.tool_changed.emit(name, self._cached_inputs)
                else:
                    self._cached_inputs = {}
                    self.tool_changed.emit("", {})
        except Exception:
            self._poll_fail_count += 1
            logging.getLogger("mflow").debug(
                "[Watcher] Poll failed (%d/3 consecutive)", self._poll_fail_count)
            if self._poll_fail_count >= 3:
                logging.getLogger("mflow").warning(
                    "[Watcher] 3 consecutive poll failures — emitting disconnected")
                self.disconnected.emit()
                self._timer.stop()
        finally:
            _total = (time.perf_counter() - _t0) * 1000
            if _total > _SLOW_MS:
                _active_ms = (_t_active - _t0) * 1000 if _t_active else -1
                _undo_ms   = (_t_undo - _t_active) * 1000 if (_t_undo and _t_active) else -1
                _scan_ms   = (_t_scan - _t_undo) * 1000 if (_t_scan and _t_undo) else -1
                lvl = logging.WARNING if _total > _VSLOW_MS else logging.INFO
                logging.getLogger("mflow").log(
                    lvl,
                    "[PERF] _poll took %.1fms total (ActiveTool=%.1fms, "
                    "GetUndoStack=%.1fms, undo_len=%d, inputs_scan=%.1fms) "
                    "— main thread blocked",
                    _total, _active_ms, _undo_ms, self._last_undo, _scan_ms)

    def _emit(self, tool):
        self.tool_changed.emit(tool.Name, self._animated_inputs(tool))

    def _animated_inputs(self, tool) -> dict:
        result = {}
        try:
            for inp in tool.GetInputList().values():
                try:
                    attrs  = inp.GetAttrs()
                    inp_id = attrs.get("INPS_ID", "")
                    label  = attrs.get("INPS_Name", inp_id)
                    if not inp_id:
                        continue
                    # Skip Image-type inputs (media connections, not animation splines)
                    # e.g. OFX tools connected to the image Input of another node
                    if attrs.get("INPS_DataType") == "Image":
                        continue
                    # Skip expressions — they're not editable splines
                    try:
                        if inp.GetExpression():
                            continue
                    except Exception:
                        pass
                    kf_count = 0
                    # Try GetKeyFrames on the input directly (works for OFX + native)
                    try:
                        sd = inp.GetKeyFrames()
                        if isinstance(sd, dict):
                            kf_count = len(sd)
                    except Exception:
                        pass
                    # Fall back to connected BezierSpline tool
                    if kf_count < 2:
                        try:
                            out = inp.GetConnectedOutput()
                            if out:
                                sp = out.GetTool()
                                if sp:
                                    sd2 = sp.GetKeyFrames()
                                    if isinstance(sd2, dict):
                                        kf_count = len(sd2)
                        except Exception:
                            pass
                    if kf_count >= 2:
                        result[inp_id] = {
                            "label":    label,
                            "kf_count": kf_count,
                            "input_obj": inp,
                        }
                except Exception:
                    pass
        except Exception:
            pass
        return result
