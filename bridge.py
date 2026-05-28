"""
FusionFlow bridge — Free version.
Place this file as FusionFlow.py in:
  Workspace > Scripts > Comp  (Fusion page)

Resolve injects 'fusion' and 'comp' globals automatically.
"""
import os, sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _get_comp():
    c = globals().get("comp") or globals().get("Comp")
    f = globals().get("fusion") or globals().get("Fusion")
    if not c and f:
        try: c = f.CurrentComp
        except Exception: pass
    if not c:
        try:
            import bmd
            fu = bmd.scriptapp("Fusion")
            if fu: c = fu.CurrentComp
        except Exception: pass
    return c


def run():
    comp = _get_comp()

    # Try running GUI directly if PySide6 is installed in Resolve's Python
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: verify present
        app = QApplication.instance() or QApplication(sys.argv)
        app.setApplicationName("FusionFlow")

        from main import FFlowWindow
        win = FFlowWindow(comp=comp)
        win.show()
        app.exec()

    except ImportError:
        # PySide6 / WebEngine not in Resolve's Python — launch system Python
        import subprocess

        main_py = os.path.join(_ROOT, "main.py")
        pythons = (["py", "python", "python3"] if sys.platform == "win32"
                   else ["python3", "python"])
        for py in pythons:
            try:
                subprocess.Popen([py, main_py], cwd=_ROOT)
                return
            except FileNotFoundError:
                continue
        print("[FusionFlow] Could not start. Run install.py with your system Python first.")


run()
