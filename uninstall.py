"""
MFlow uninstaller — python uninstall.py
Removes MFlow files from all installed locations.
Preserves: settings.json, profiles.json, presets/ (your data).
"""
import os, sys, shutil, platform

PLAT = platform.system()
ARCH = platform.machine()
HERE = os.path.dirname(os.path.abspath(__file__))

SCRIPTS_UTILITY = {
    "Windows": [
        os.path.expandvars(r"%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility"),
        r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Utility",
    ],
    "Darwin": [
        os.path.expanduser("~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility"),
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility",
    ],
    "Linux": [
        os.path.expanduser("~/.local/share/DaVinciResolve/Fusion/Scripts/Utility"),
        "/opt/resolve/Fusion/Scripts/Utility",
    ],
}

SCRIPTS_COMP = {
    "Windows": [
        os.path.expandvars(r"%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Comp"),
        r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Comp",
    ],
    "Darwin": [
        os.path.expanduser("~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Comp"),
    ],
    "Linux": [
        os.path.expanduser("~/.local/share/DaVinciResolve/Fusion/Scripts/Comp"),
        "/opt/resolve/Fusion/Scripts/Comp",
    ],
}

def _get_install_dir():
    """Where install.py copies the application CODE (main.py, ui/, core/...).
    Matches platformdirs.user_data_dir — on Windows this is %LOCALAPPDATA%,
    which is DIFFERENT from where the running app stores its data (see
    _get_data_dir below). Two separate directories, both must be cleaned.
    """
    try:
        from platformdirs import user_data_dir
        return user_data_dir("MFlow", appauthor=False)
    except ImportError:
        pass
    if PLAT == "Windows":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.environ.get("USERPROFILE", os.path.expanduser("~")), "AppData", "Local"
        )
        return os.path.join(base, "MFlow")
    elif PLAT == "Darwin":
        return os.path.expanduser("~/Library/Application Support/MFlow")
    else:
        xdg = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
        return os.path.join(xdg, "MFlow")

def _get_data_dir():
    """Where the RUNNING app actually writes settings.json, profiles.json and
    user-saved themes — must exactly match core/platform_config.py's
    app_data_dir(). On Windows that's %APPDATA%\\\\MFlow (roaming), NOT
    %LOCALAPPDATA%\\\\MFlow — a different folder from _get_install_dir() above.
    Import the real implementation when available so this can never drift
    out of sync with the app again; fall back to a manual copy only if the
    source tree isn't importable (e.g. running uninstall.py standalone after
    core/ was already partially removed).
    """
    try:
        sys.path.insert(0, HERE)
        from core.platform_config import app_data_dir
        return app_data_dir()
    except Exception:
        pass
    if PLAT == "Windows":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif PLAT == "Darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(base, "MFlow")

INSTALL_DIR = _get_install_dir()
DATA_DIR    = _get_data_dir()

# Files placed by the installer in Resolve script dirs
LAUNCHER_FILES = [
    "MFlow.lua",
    "MFlow_Free.py",
    "mflow_path.txt",
    "python_path.txt",
]

# Files/folders inside install dir to KEEP (user data)
KEEP = {"settings.json", "profiles.json", "presets", "themes"}

def sep(c="-"): print(c * 54)

def remove_file(path):
    try:
        os.remove(path)
        print(f"  Removed  {path}")
        return True
    except FileNotFoundError:
        return False
    except Exception as e:
        print(f"  WARN     Cannot remove {path}: {e}")
        return False

def remove_dir(path):
    try:
        shutil.rmtree(path)
        print(f"  Removed  {path}/")
        return True
    except FileNotFoundError:
        return False
    except Exception as e:
        print(f"  WARN     Cannot remove {path}: {e}")
        return False

def main():
    plat_display = {"Windows": "Windows", "Darwin": "macOS", "Linux": "Linux"}.get(PLAT, PLAT)

    print()
    sep("=")
    print("  MFlow - Uninstaller")
    print(f"  Platform: {plat_display} ({ARCH})")
    print(f"  App code:    {INSTALL_DIR}")
    print(f"  Your data:   {DATA_DIR}")
    sep("=")

    print("\nThis will remove MFlow from your system.")
    print("Your settings, profiles, presets and saved themes live in a")
    print("separate folder from the app — you'll be asked below whether")
    print("to keep or remove that data too.")
    print()

    confirm = input("Continue? [y/N]: ").strip().lower()
    if confirm != "y":
        print("\nCancelled.")
        input("\nPress Enter to close...")
        return

    keep_data = input("\nKeep your settings and presets? [Y/n]: ").strip().lower()
    keep_user_data = (keep_data != "n")

    removed = 0

    # ── 1. Remove launcher files from Scripts/Utility ────────────────────
    print("\n[1/4] Removing Studio launcher (Scripts/Utility)...")
    for d in SCRIPTS_UTILITY.get(PLAT, []):
        for fname in LAUNCHER_FILES:
            p = os.path.join(d, fname)
            if os.path.isfile(p) and remove_file(p):
                removed += 1

    # ── 2. Remove launcher files from Scripts/Comp ───────────────────────
    print("\n[2/4] Removing Free launcher (Scripts/Comp)...")
    for d in SCRIPTS_COMP.get(PLAT, []):
        for fname in LAUNCHER_FILES:
            p = os.path.join(d, fname)
            if os.path.isfile(p) and remove_file(p):
                removed += 1

    # ── 3. Remove the app-code install dir — always safe to wipe entirely,
    #      since no user data has ever lived here at runtime (KEEP_PATTERNS
    #      in install.py is only a legacy safety net for old installs that
    #      may have mixed code and data in this folder).
    print(f"\n[3/4] Removing app code: {INSTALL_DIR}")
    if os.path.isdir(INSTALL_DIR):
        if keep_user_data:
            for item in os.listdir(INSTALL_DIR):
                if item in KEEP:
                    print(f"  Kept     {item}  (your data — legacy location)")
                    continue
                target = os.path.join(INSTALL_DIR, item)
                if os.path.isdir(target):
                    if remove_dir(target): removed += 1
                else:
                    if remove_file(target): removed += 1
            try:
                remaining = os.listdir(INSTALL_DIR)
                if not remaining:
                    os.rmdir(INSTALL_DIR)
                    print(f"  Removed  {INSTALL_DIR}/")
                else:
                    print(f"\n  Kept {INSTALL_DIR}/ (contains: {', '.join(remaining)})")
            except Exception:
                pass
        else:
            remove_dir(INSTALL_DIR)
            removed += 1
    else:
        print(f"  Not found: {INSTALL_DIR}")

    # ── 4. Remove the REAL data dir — settings.json, profiles.json, and every
    #      theme you've ever saved via Settings > Save Theme all live here.
    #      This is the directory the previous version of this script never
    #      touched, which is why themes survived uninstall.
    print(f"\n[4/4] {'Removing' if not keep_user_data else 'Checking'} your data: {DATA_DIR}")
    if os.path.isdir(DATA_DIR):
        if DATA_DIR == INSTALL_DIR:
            # macOS: both paths coincide — already handled above, nothing left to do
            print("  (same folder as app code on this platform — already handled)")
        elif keep_user_data:
            print(f"  Kept     {DATA_DIR}/  (settings, profiles, themes)")
        else:
            if remove_dir(DATA_DIR):
                removed += 1
    else:
        print(f"  Not found: {DATA_DIR}")

    # ── Log file ──────────────────────────────────────────────────────────
    log_dir = os.path.join(os.path.expanduser("~"), ".mflow")
    log_file = os.path.join(log_dir, "mflow.log")
    if os.path.isfile(log_file):
        yn = input("\nRemove log file (~/.mflow/mflow.log)? [y/N]: ").strip().lower()
        if yn == "y":
            remove_file(log_file)
            try:
                if not os.listdir(log_dir): os.rmdir(log_dir)
            except Exception: pass

    sep("=")
    print(f"\n  Done. {removed} file(s) removed.")
    print()
    input("Press Enter to close...")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
    except Exception as e:
        import traceback; traceback.print_exc()
        input("\nPress Enter to close...")
