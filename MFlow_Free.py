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
import sys, os, platform, time

def _fallback_log(msg):
    """Writes straight to mflow.log without going through main.py's logging
    setup — needed because everything below can fail BEFORE main is even
    importable (mflow_dir not found, PySide6 missing), which otherwise
    leaves zero trace on disk of the single most common Free-launcher
    failure mode."""
    try:
        log_dir = os.path.join(os.path.expanduser("~"), ".mflow")
        os.makedirs(log_dir, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"{stamp} [PID:{os.getpid()}] [MFLOW_FREE] {msg}\n"
        with open(os.path.join(log_dir, "mflow.log"), "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass

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
    _fallback_log(f"_find_mflow: script dir resolved to: {here or '(unresolved)'}")

    # 1. mflow_path.txt next to this script (only if we resolved the script dir)
    if here:
        txt = os.path.join(here, "mflow_path.txt")
        if os.path.isfile(txt):
            p = open(txt, encoding="utf-8").read().strip()
            ok = os.path.isfile(os.path.join(p, "main.py"))
            _fallback_log(f"_find_mflow: mflow_path.txt -> {p}  main.py present={ok}")
            if ok:
                return p
        else:
            _fallback_log(f"_find_mflow: no mflow_path.txt at {txt}")

    # 2. Platform default install location
    candidates = {
        "Windows": [os.path.join(os.environ.get("LOCALAPPDATA",""), "MFlow")],
        "Darwin":  [os.path.expanduser("~/Library/Application Support/MFlow")],
        "Linux":   [os.path.expanduser("~/.local/share/MFlow")],
    }.get(PLAT, [])
    for c in candidates:
        ok = os.path.isfile(os.path.join(c, "main.py"))
        _fallback_log(f"_find_mflow: platform default candidate {c}  main.py present={ok}")
        if ok:
            return c

    # 3. Script's own directory (dev mode)
    if os.path.isfile(os.path.join(here, "main.py")):
        _fallback_log(f"_find_mflow: found via script's own dir: {here}")
        return here
    return None

def _log_scripts_path_map(fusion_obj):
    """Fusion/Resolve has a known, community-documented bug where Fusion.prefs
    fails to persist Path Map entries correctly (disk permission issues on
    some machines) — when that happens, Resolve can scan a different Scripts
    folder than the one this launcher's own file actually lives in, so a
    correctly-copied MFlow_Free.py never shows up in the menu. This makes
    that mismatch visible instead of silent."""
    try:
        mapped = fusion_obj.MapPath("Scripts:")
        _fallback_log(f"Fusion Path Map 'Scripts:' resolves to: {mapped}")
    except Exception as e:
        _fallback_log(f"Could not read Fusion Path Map 'Scripts:': {e}")

mflow_dir = _find_mflow()
if mflow_dir is None:
    _fallback_log("MFlow not found — mflow_path.txt and all platform default "
                   "candidates missing or lacking main.py. See lines above for "
                   "exactly what was checked.")
    print("[MFlow] ERROR: MFlow not found. Run install.py first.")
    print("        Or place mflow_path.txt next to this script with the install path.")
else:
    _fallback_log(f"MFlow found at: {mflow_dir} — proceeding to import main")
    if mflow_dir not in sys.path:
        sys.path.insert(0, mflow_dir)
    try:
        # 'app' is injected by Resolve — it IS the Fusion object on Free
        _fusion = app           # noqa: F821
        _comp   = _fusion.CurrentComp
        _log_scripts_path_map(_fusion)

        from PySide6.QtWidgets import QApplication
        _qt = QApplication.instance() or QApplication(sys.argv)

        from main import MFlowWindow
        win = MFlowWindow(fusion_app=_fusion, comp=_comp)
        win.show()
        _qt.exec()
    except NameError:
        _fallback_log("'app' not found in context — script was not run from "
                       "Scripts > Comp (Fusion page).")
        print("[MFlow] ERROR: 'app' not found in context.")
        print("        Run MFlow_Free from Scripts > Comp (Fusion page), not from terminal.")
    except Exception as e:
        import traceback
        _fallback_log(f"Fatal error during Free launch: {e}\n{traceback.format_exc()}")
        print(f"[MFlow] Error: {e}")
        traceback.print_exc()
