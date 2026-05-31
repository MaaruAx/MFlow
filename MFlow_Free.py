# MFlow_Free.py
# ─────────────────────────────────────────────────────────────────────────────
# Bridge for DaVinci Resolve FREE.
# Copy this file to:
#   Windows: %APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Comp\
#   Mac:     ~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Support/Fusion/Scripts/Comp/
#   Linux:   ~/.local/share/DaVinciResolve/Fusion/Scripts/Comp/
#
# In Resolve (Fusion page): Scripts > Comp > MFlow_Free
#
# HOW IT WORKS: Resolve injects 'app' (a live Fusion object) automatically
# when executing scripts from Scripts/Comp/. We pass it directly to MFlow —
# no scriptapp(), no DaVinciResolveScript, no external connection needed.
# ─────────────────────────────────────────────────────────────────────────────
import sys, os, platform

def _find_mflow():
    PLAT = platform.system()
    # In Resolve's script context, __file__ may not be defined — use multiple fallbacks
    here = ""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        try:
            import inspect
            here = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
        except Exception:
            pass
    # 1. mflow_path.txt next to this script (only if we resolved the script dir)
    if here:
        txt = os.path.join(here, "mflow_path.txt")
        if os.path.isfile(txt):
            p = open(txt, encoding="utf-8").read().strip()
            if os.path.isfile(os.path.join(p, "main.py")):
                return p
    # 2. Platform default install location
    candidates = {
        "Windows": [os.path.join(os.environ.get("LOCALAPPDATA",""), "MFlow")],
        "Darwin":  [os.path.expanduser("~/Library/Application Support/MFlow")],
        "Linux":   [os.path.expanduser("~/.local/share/MFlow")],
    }.get(PLAT, [])
    for c in candidates:
        if os.path.isfile(os.path.join(c, "main.py")):
            return c
    # 3. Script's own directory (dev mode)
    if os.path.isfile(os.path.join(here, "main.py")):
        return here
    return None

mflow_dir = _find_mflow()
if mflow_dir is None:
    print("[MFlow] ERROR: MFlow not found. Run install.py first.")
    print("        Or place mflow_path.txt next to this script with the install path.")
else:
    if mflow_dir not in sys.path:
        sys.path.insert(0, mflow_dir)
    try:
        # 'app' is injected by Resolve — it IS the Fusion object on Free
        _fusion = app           # noqa: F821
        _comp   = _fusion.CurrentComp

        from PySide6.QtWidgets import QApplication
        _qt = QApplication.instance() or QApplication(sys.argv)

        from main import MFlowWindow
        win = MFlowWindow(fusion_app=_fusion, comp=_comp)
        win.show()
        _qt.exec()
    except NameError:
        print("[MFlow] ERROR: 'app' not found in context.")
        print("        Run MFlow_Free from Scripts > Comp (Fusion page), not from terminal.")
    except Exception as e:
        import traceback
        print(f"[MFlow] Error: {e}")
        traceback.print_exc()
