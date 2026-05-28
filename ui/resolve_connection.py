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
    if sys.platform == "win32":
        # Strip Microsoft Store aliases — intercept DLL resolution when
        # multiple Python versions are installed
        parts = os.environ.get("PATH", "").split(os.pathsep)
        os.environ["PATH"] = os.pathsep.join(
            p for p in parts if
            "WindowsApps" not in p and
            "windowsapps" not in p.lower()
        )
        # Add Resolve DLL dir
        for rdir in [
            r"C:\Program Files\Blackmagic Design\DaVinci Resolve",
            r"C:\Program Files (x86)\Blackmagic Design\DaVinci Resolve",
        ]:
            if os.path.isdir(rdir):
                if rdir not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = rdir + os.pathsep + os.environ["PATH"]
                try: os.add_dll_directory(rdir)
                except (AttributeError, OSError): pass
                break

    # Remove stale cached imports from a previous/wrong-version attempt
    for _k in ("DaVinciResolveScript", "fusionscript"):
        sys.modules.pop(_k, None)

    # Method 1: DaVinciResolveScript module (preferred)
    for p in resolve_module_paths(custom_path):
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
    try:
        import DaVinciResolveScript as _dvr  # noqa
        r = _dvr.scriptapp("Resolve")
        if r:
            return r
        print("[MFlow] scriptapp returned None.\n"
              "  Resolve must be open and:\n"
              "  Preferences > System > General > External scripting using > Local")
    except ImportError as e:
        print(f"[MFlow] Import failed: {e}")
        print(f"  Searched: {resolve_module_paths(custom_path)}")
    except Exception as e:
        print(f"[MFlow] Error: {e}")

    # Method 2: fusionscript DLL
    fsp = fusionscript_path()
    if fsp:
        try:
            spec = importlib.util.spec_from_file_location("fusionscript", fsp)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                r = mod.scriptapp("Resolve")
                if r: return r
        except Exception as e:
            print(f"[MFlow] fusionscript fallback failed: {e}")

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
    Polls the active Fusion comp every 350 ms.
    Uses undo-stack length as a cheap change trigger (friend's approach),
    only doing a detailed input scan when something actually changed.
    """
    tool_changed  = Signal(str, dict)   # tool_name, {inp_id: {label, kf_count, input_obj}}
    disconnected  = Signal()

    POLL_MS = 350

    def __init__(self, comp, parent=None):
        super().__init__(parent)
        self._comp        = comp
        self._last_name   = ""
        self._last_undo   = 0
        self._cached_inputs = {}
        self._selected_input = None   # (tool_name, inp_id) chosen by user
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    def start(self):
        self._last_undo = self._undo_len()
        self._timer.start(self.POLL_MS)

    def stop(self):
        self._timer.stop()

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
            name_changed = (name != self._last_name)
            undo_changed = (undo != self._last_undo)
            if name_changed or undo_changed:
                self._last_name = name
                self._last_undo = undo
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
            self.disconnected.emit()
            self._timer.stop()
        except Exception:
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
