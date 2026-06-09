"""
MFlow uninstaller — python uninstall.py
Removes MFlow files from all installed locations.
Preserves: settings.json, profiles.json, presets/ (your data).
"""
import os, sys, shutil, platform

PLAT = platform.system()
ARCH = platform.machine()

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

INSTALL_DIR = _get_install_dir()

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
    print(f"  Install dir: {INSTALL_DIR}")
    sep("=")

    print("\nThis will remove MFlow from your system.")
    print("Your settings, profiles, presets and themes will be preserved.")
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
    print("\n[1/3] Removing Studio launcher (Scripts/Utility)...")
    for d in SCRIPTS_UTILITY.get(PLAT, []):
        for fname in LAUNCHER_FILES:
            p = os.path.join(d, fname)
            if os.path.isfile(p) and remove_file(p):
                removed += 1

    # ── 2. Remove launcher files from Scripts/Comp ───────────────────────
    print("\n[2/3] Removing Free launcher (Scripts/Comp)...")
    for d in SCRIPTS_COMP.get(PLAT, []):
        for fname in LAUNCHER_FILES:
            p = os.path.join(d, fname)
            if os.path.isfile(p) and remove_file(p):
                removed += 1

    # ── 3. Remove install dir (keeping user data) ─────────────────────────
    print(f"\n[3/3] Removing install directory: {INSTALL_DIR}")
    if os.path.isdir(INSTALL_DIR):
        if keep_user_data:
            for item in os.listdir(INSTALL_DIR):
                if item in KEEP:
                    print(f"  Kept     {item}  (your data)")
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
