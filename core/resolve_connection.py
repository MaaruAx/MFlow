"""
Resolve connection and live watcher (undo-stack strategy from friend's script).
All API calls stay on the main thread — watcher uses QTimer, never QThread.
"""
import importlib, importlib.util, os, sys
from PySide6.QtCore import QObject, QTimer, Signal
from core.platform_config import resolve_module_paths, fusionscript_path


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
        self._selected_input = None
        self._comp_name      = self._get_comp_attr_name()   # stable name for comparison

        self._poll_fail_count = 0           # consecutive poll failures
        self._comp_fp = self._quick_fp(comp)  # fingerprint for comp-change detection

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
        Fast fingerprint for comp-change detection.
        Uses first 5 sorted tool names + count.
        Avoids COMPS_FileName/COMPS_Name which are empty for Resolve timeline comps.
        One GetToolList IPC call, only from _comp_check (every 1500 ms).
        """
        try:
            tools = comp.GetToolList(False)
            if not tools:
                return ""
            names = sorted(t.Name for t in tools.values())
            return f"{len(names)}:" + ",".join(names[:5])
        except Exception:
            return ""

    def _comp_check(self):
        """Periodic check: has the user switched to a different comp in Resolve?"""
        if not self._fu:
            return
        try:
            current = self._fu.GetCurrentComp()
            if not current:
                return
            current_fp = self._quick_fp(current)
            # Only fire if fingerprint is non-empty AND different from stored one.
            # COMPS_FileName/COMPS_Name are empty for timeline comps so we use
            # tool-name fingerprints which ARE reliable across IPC.
            if current_fp and current_fp != self._comp_fp:
                import logging
                logging.getLogger("mflow").debug(
                    "[Watcher] _comp_check: fp changed '%s' → '%s'",
                    self._comp_fp, current_fp)
                self.comp_changed.emit()
        except Exception:
            pass

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
        result = {}
        try:
            tool_list = self._comp.GetToolList(False)  # False = all tools, not just selected
            if not tool_list:
                return result
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
        self.comp_scan_updated.emit(result)
        return result

    # ── internals ─────────────────────────────────────────────────────────────

    def _undo_len(self) -> int:
        try:
            return len(self._comp.GetUndoStack())
        except Exception:
            return self._last_undo

    POLL_MS = 500  # slower poll reduces CPU

    def _poll(self):
        try:
            active = self._comp.ActiveTool
            name   = active.Name if active else ""
            undo   = self._undo_len()
            self._poll_fail_count = 0   # reset on any successful IPC call
            name_changed = (name != self._last_name)
            undo_changed = (undo != self._last_undo)
            if name_changed or undo_changed:
                self._last_name = name
                self._last_undo = undo
                if undo_changed:
                    # Restart cooldown — scan fires 2.5s after last change
                    self._scan_cooldown.start()
                if active:
                    # Only re-scan inputs when tool changes — expensive operation
                    # On undo-only change, reuse cached inputs
                    if name_changed or not self._cached_inputs:
                        self._cached_inputs = self._animated_inputs(active)
                    self.tool_changed.emit(name, self._cached_inputs)
                else:
                    self._cached_inputs = {}
                    self.tool_changed.emit("", {})
        except Exception:
            self._poll_fail_count += 1
            import logging
            logging.getLogger("mflow").debug(
                "[Watcher] Poll failed (%d/3 consecutive)", self._poll_fail_count)
            if self._poll_fail_count >= 3:
                import logging
                logging.getLogger("mflow").warning(
                    "[Watcher] 3 consecutive poll failures — emitting disconnected")
                self.disconnected.emit()
                self._timer.stop()

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
