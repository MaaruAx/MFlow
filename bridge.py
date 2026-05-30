"""
MFlow bridge - Free version.
Place as MFlow.py in:
  %APPDATA%/Blackmagic Design/DaVinci Resolve/Support/Fusion/Scripts/Utility/

Resolve injects 'fusion' and 'comp' globals automatically when run from
Workspace > Scripts menu.
"""
import os, sys, platform

HERE = os.path.dirname(os.path.abspath(__file__))


def _find_mflow():
    """Locate MFlow install dir - checks multiple locations."""
    PLAT = platform.system()

    # 1. mflow_path.txt next to this script
    txt = os.path.join(HERE, "mflow_path.txt")
    if os.path.isfile(txt):
        p = open(txt, encoding="utf-8").read().strip()
        if os.path.isfile(os.path.join(p, "main.py")):
            return p

    # 2. Platform default install location
    if PLAT == "Windows":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.environ.get("USERPROFILE", os.path.expanduser("~")),
            "AppData", "Local"
        )
        candidates = [os.path.join(base, "MFlow")]
    elif PLAT == "Darwin":
        candidates = [os.path.expanduser("~/Library/Application Support/MFlow")]
    else:
        candidates = [
            os.path.expanduser("~/.local/share/MFlow"),
            "/opt/MFlow",
        ]

    for c in candidates:
        if os.path.isfile(os.path.join(c, "main.py")):
            return c

    # 3. Same directory as this script (dev mode / running from source)
    if os.path.isfile(os.path.join(HERE, "main.py")):
        return HERE

    return None


def _find_python():
    """Find python_path.txt or fall back to sys.executable."""
    for loc in [HERE]:
        txt = os.path.join(loc, "python_path.txt")
        if os.path.isfile(txt):
            p = open(txt, encoding="utf-8").read().strip()
            if os.path.isfile(p):
                return p
    return sys.executable


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
    comp   = _get_comp()
    mflow  = _find_mflow()
    python = _find_python()

    if mflow is None:
        msg = (
            "[MFlow] Cannot find MFlow installation.\n"
            "Run install.py first, or place mflow_path.txt next to this script."
        )
        print(msg)
        return

    if mflow not in sys.path:
        sys.path.insert(0, mflow)

    # Try launching in-process (PySide6 available in Resolve's Python)
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa
        app = QApplication.instance() or QApplication(sys.argv)
        app.setApplicationName("MFlow")
        from main import MFlowWindow
        win = MFlowWindow(comp=comp)
        win.show()
        app.exec()
        return
    except ImportError:
        pass

    # Launch as separate process using system Python
    import subprocess
    main_py = os.path.join(mflow, "main.py")
    print(f"[MFlow] Launching: {python} {main_py}")

    if platform.system() == "Windows":
        # Use DETACHED_PROCESS so Resolve doesn't wait for it
        CREATE_DETACHED = 0x00000008
        try:
            subprocess.Popen([python, main_py], cwd=mflow,
                             creationflags=CREATE_DETACHED,
                             close_fds=True)
            return
        except Exception as e:
            print(f"[MFlow] Popen failed: {e}")
    else:
        try:
            subprocess.Popen([python, main_py], cwd=mflow,
                             start_new_session=True)
            return
        except Exception as e:
            print(f"[MFlow] Popen failed: {e}")

    print("[MFlow] Could not start. Run install.py first.")


run()
