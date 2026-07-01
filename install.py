"""
MFlow installer - python install.py
Works on Windows, macOS, Linux.
Never crashes - every error is caught, explained, and continues.
"""
import subprocess, sys, os, shutil, platform, glob, json, time

MFLOW_VERSION = "2.5.0"
HERE   = os.path.dirname(os.path.abspath(__file__))
PLAT   = platform.system()
ARCH   = platform.machine()
PY_VER = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

# -- Resolve Scripts paths per platform ---------------------------------------
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
        "/home/resolve/Fusion/Scripts/Utility",
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
    """Return platform-appropriate app data dir, using platformdirs if available."""
    try:
        from platformdirs import user_data_dir
        return user_data_dir("MFlow", appauthor=False)
    except ImportError:
        pass
    # Manual fallback
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

def sep(c="-"): print(c * 54)

def log(msg, tag=""):
    prefix = f"[{tag}] " if tag else "  "
    print(f"{prefix}{msg}")

def safe(fn, *args, **kwargs):
    """Call fn, return (result, None) or (None, error_string)."""
    try:
        return fn(*args, **kwargs), None
    except Exception as e:
        return None, str(e)

# -- Detect all Python executables ---------------------------------------------
def probe_python(exe):
    try:
        r = subprocess.run(
            [exe, "-c", "import sys; print(sys.version.split()[0]); print(sys.executable)"],
            capture_output=True, text=True, timeout=8
        )
        if r.returncode == 0:
            lines = r.stdout.strip().splitlines()
            if len(lines) >= 2:
                ver, real_exe = lines[0], lines[1]
                maj, minor = int(ver.split(".")[0]), int(ver.split(".")[1])
                if maj == 3 and minor >= 9:
                    return real_exe, ver
    except Exception:
        pass
    return None, None

def find_all_pythons():
    seen = {}  # exe -> version

    def add(exe):
        real, ver = probe_python(exe)
        if real and real not in seen:
            seen[real] = ver

    # Current interpreter first
    add(sys.executable)

    if PLAT == "Windows":
        # Python.org installs
        lad = os.environ.get("LOCALAPPDATA", "")
        for d in glob.glob(os.path.join(lad, "Programs", "Python", "Python3*")):
            add(os.path.join(d, "python.exe"))
        # py launcher
        for ver in ("3.12", "3.11", "3.10", "3.9"):
            r, _ = safe(subprocess.run,
                ["py", f"-{ver}", "-c", "import sys;print(sys.executable)"],
                capture_output=True, text=True, timeout=6)
            if r and r.returncode == 0:
                add(r.stdout.strip())
        # PATH
        for name in ("python", "python3"):
            exe = shutil.which(name)
            if exe: add(exe)
    else:
        for name in ("python3", "python3.12", "python3.11", "python3.10", "python3.9", "python"):
            exe = shutil.which(name)
            if exe: add(exe)

    # Filter Microsoft Store stubs
    return {
        exe: ver for exe, ver in seen.items()
        if "WindowsApps" not in exe and "PythonSoftwareFoundation" not in exe
    }

def pick_best(pythons):
    def key(item):
        try: return tuple(int(x) for x in item[1].split(".")[:3])
        except: return (0, 0, 0)
    return sorted(pythons.items(), key=key, reverse=True)[0] if pythons else (sys.executable, PY_VER)

# -- pip install ----------------------------------------------------------------
def pip_install(python_exe, pkg, extra_args=None):
    cmd = [python_exe, "-m", "pip", "install", "--upgrade", pkg]
    if extra_args: cmd += extra_args
    print(f"    pip install {pkg} ...", end=" ", flush=True)
    r, err = safe(subprocess.run, cmd, capture_output=True, text=True, timeout=300)
    if err:
        print(f"ERROR ({err})"); return False
    if r.returncode == 0:
        print("OK"); return True
    errs = [l for l in r.stderr.strip().splitlines() if l.strip()]
    print(f"WARN  {errs[-1][:100] if errs else 'unknown'}")
    return False

# -- File operations -----------------------------------------------------------
def copy_tree(src, dst):
    """Copy src directory into dst, skipping __pycache__, .pyc, and PyInstaller
    / Inno Setup build artifacts that might exist alongside the source on a
    dev machine but should never be shipped into the user's install dir."""
    errors = []
    SKIP_DIRS = ("__pycache__", ".git", ".venv", "venv", "node_modules",
                 "dist", "build", "installer")
    for item in os.listdir(src):
        if item in SKIP_DIRS:
            continue
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        try:
            if os.path.isdir(s):
                if os.path.exists(d): shutil.rmtree(d)
                shutil.copytree(s, d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            else:
                shutil.copy2(s, d)
        except Exception as e:
            errors.append(f"{item}: {e}")
    return errors

def find_scripts_dir():
    dirs = SCRIPTS_UTILITY.get(PLAT, [])
    for d in dirs:
        if os.path.isdir(d): return d
    # Create first candidate
    first = dirs[0] if dirs else None
    if first:
        _, err = safe(os.makedirs, first, exist_ok=True)
        if not err: return first
    return None

def find_scripts_comp():
    dirs = SCRIPTS_COMP.get(PLAT, [])
    for d in dirs:
        if os.path.isdir(d): return d
    first = dirs[0] if dirs else None
    if first:
        _, err = safe(os.makedirs, first, exist_ok=True)
        if not err: return first
    return None

def write_python_path(python_exe, location):
    try:
        path = os.path.join(location, "python_path.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(python_exe)
    except Exception as e:
        log(f"Could not write python_path.txt: {e}", "WARN")

def write_mflow_path(install_dir, location):
    """Write mflow_path.txt with the fully-expanded real path (no env vars)."""
    try:
        real = os.path.realpath(os.path.abspath(install_dir))
        path = os.path.join(location, "mflow_path.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(real)
        log(f"  mflow_path.txt -> {real}")
    except Exception as e:
        log(f"Could not write mflow_path.txt: {e}", "WARN")

# -- Main ----------------------------------------------------------------------
def main():
    print()
    sep("=")
    print(f"  MFlow {MFLOW_VERSION} - Installer")
    _plat_display = {"Windows": "Windows", "Darwin": "macOS", "Linux": "Linux"}.get(PLAT, PLAT)
    print(f"  Platform: {_plat_display} ({ARCH})   Python: {PY_VER}")
    print(f"  App code:  {INSTALL_DIR}")
    try:
        sys.path.insert(0, HERE)
        from core.platform_config import app_data_dir as _adir
        print(f"  Your data: {_adir()}  (settings, profiles, themes)")
    except Exception:
        pass
    sep("=")

    # Block Microsoft Store Python
    if "WindowsApps" in sys.executable or "PythonSoftwareFoundation" in sys.executable:
        print("\n  [!] Microsoft Store Python detected - cannot install packages.")
        print("      Download Python from https://www.python.org/downloads/")
        print("      and run install.py with that version.\n")
        input("Press Enter to close...")
        return

    # -- Step 1: Detect Python ----------------------------------------------
    sep()
    print("\n[1/4] Detecting Python installations...\n")
    pythons = find_all_pythons()
    if not pythons:
        print("  No Python 3.9+ found. Install from https://www.python.org")
        input("\nPress Enter to close..."); return

    python_exe, python_ver = pick_best(pythons)
    print(f"  Found {len(pythons)} installation(s):")
    for exe, ver in sorted(pythons.items(), key=lambda x: x[1], reverse=True):
        mark = " < selected" if exe == python_exe else ""
        print(f"    {ver}  {exe}{mark}")

    # Write for Lua launcher
    write_python_path(python_exe, HERE)

    # -- Step 2: Install PySide6 --------------------------------------------
    sep()
    print("\n[2/4] Installing dependencies...\n")

    req_file = os.path.join(HERE, "requirements.txt")

    # Check if already installed
    r, _ = safe(subprocess.run,
        [python_exe, "-c", "import PySide6.QtWebEngineWidgets; print('ok')"],
        capture_output=True, text=True, timeout=15)
    if r and "ok" in r.stdout:
        print("    PySide6 already installed  OK")
    elif os.path.isfile(req_file):
        # Prefer requirements.txt so version pins stay in one place (the repo)
        # instead of duplicating "PySide6" here with no version constraint.
        print(f"    pip install -r requirements.txt ...", end=" ", flush=True)
        r3, err = safe(subprocess.run,
            [python_exe, "-m", "pip", "install", "--upgrade", "-r", req_file],
            capture_output=True, text=True, timeout=300)
        if err or not r3 or r3.returncode != 0:
            print("WARN  falling back to direct install")
            pip_install(python_exe, "PySide6")
        else:
            print("OK")
        # Verify WebEngine - some platforms need explicit install
        r2, _ = safe(subprocess.run,
            [python_exe, "-c", "import PySide6.QtWebEngineWidgets"],
            capture_output=True, text=True, timeout=15)
        if r2 and r2.returncode != 0:
            log("QtWebEngineWidgets not found - trying PySide6[WebEngine]", "WARN")
            pip_install(python_exe, "PySide6[WebEngine]")
    else:
        pip_install(python_exe, "PySide6")
        # Verify WebEngine - some platforms need explicit install
        r2, _ = safe(subprocess.run,
            [python_exe, "-c", "import PySide6.QtWebEngineWidgets"],
            capture_output=True, text=True, timeout=15)
        if r2 and r2.returncode != 0:
            log("QtWebEngineWidgets not found - trying PySide6[WebEngine]", "WARN")
            pip_install(python_exe, "PySide6[WebEngine]")

    # platformdirs: clean cross-platform path resolution
    r_pd, _ = safe(subprocess.run,
        [python_exe, "-c", "import platformdirs"],
        capture_output=True, text=True, timeout=8)
    if r_pd and r_pd.returncode == 0:
        print("    platformdirs already installed  OK")
    else:
        pip_install(python_exe, "platformdirs")

    # -- Step 3: Copy MFlow to install dir ---------------------------------
    sep()
    print(f"\n[3/4] Installing MFlow to: {INSTALL_DIR}\n")
    _, err = safe(os.makedirs, INSTALL_DIR, exist_ok=True)
    if err:
        log(f"Cannot create install dir: {err}", "ERR")
        log("Falling back to current directory", "WARN")
        install_dir = HERE
    else:
        install_dir = INSTALL_DIR

    # These are normally preserved across upgrades (user configs/presets/themes)
    KEEP_PATTERNS = {"settings.json", "profiles.json", "presets", "themes", "mflow_path.txt", "python_path.txt"}

    # -- Ask about a clean install if there's existing user data ------------
    clean_install = False
    if os.path.isdir(install_dir) and install_dir != HERE:
        has_existing_data = any(
            os.path.exists(os.path.join(install_dir, p)) for p in KEEP_PATTERNS
            if p not in ("mflow_path.txt", "python_path.txt")
        )
        if has_existing_data:
            print()
            log("Existing MFlow data found (settings, profiles, presets and/or themes).", "!")
            yn_clean = input(
                "  Perform a CLEAN install and erase your existing settings/presets/themes? [y/N]: "
            ).strip().lower()
            clean_install = yn_clean == 'y'
            print()

    # Preserve everything by default, or nothing if the user chose a clean install
    keep_patterns = set() if clean_install else KEEP_PATTERNS

    if clean_install:
        log("Clean install selected — wiping existing settings/profiles/presets/themes", "!")
        for item in KEEP_PATTERNS:
            if item in ("mflow_path.txt", "python_path.txt"):
                continue  # regenerated below regardless
            target = os.path.join(install_dir, item)
            if os.path.exists(target):
                try:
                    if os.path.isdir(target): shutil.rmtree(target)
                    else: os.remove(target)
                    log(f"  Erased: {item}")
                except Exception as e:
                    log(f"  Could not erase {item}: {e}", "WARN")

    # Clean stale files from previous versions (preserve configs and presets unless clean install)
    if os.path.isdir(install_dir) and install_dir != HERE:
        for item in os.listdir(install_dir):
            if item in keep_patterns or item.startswith("."):
                continue
            target = os.path.join(install_dir, item)
            src_equiv = os.path.join(HERE, item)
            # Only remove if NOT in current source (truly stale)
            if not os.path.exists(src_equiv):
                try:
                    if os.path.isdir(target): shutil.rmtree(target)
                    else: os.remove(target)
                    log(f"  Removed stale: {item}")
                except Exception as e:
                    log(f"  Could not remove {item}: {e}", "WARN")

    # Guard: if install.py is running FROM inside the install dir (e.g. user
    # navigated to %LOCALAPPDATA%\MFlow and ran install.py from there), skip the
    # file copy entirely.  copy_tree(src, dst) with src==dst calls shutil.rmtree
    # on each subdirectory before re-copying it — if the copy then fails (e.g.
    # a lock or permission error) the directory stays deleted, which is exactly
    # what caused the "No module named 'ui'" / "No module named 'core'" errors.
    _here_real = os.path.realpath(os.path.abspath(HERE))
    _inst_real  = os.path.realpath(os.path.abspath(install_dir))
    if _here_real == _inst_real:
        log("Source == install dir — skipping file copy (already in place)")
    else:
        errs = copy_tree(HERE, install_dir)
        if errs:
            for e in errs: log(e, "WARN")
        else:
            log(f"OK - copied to {install_dir}")

    # -- Copy bundled themes to AppData (non-destructive: never overwrite user edits)
    bundled_themes = os.path.join(install_dir, "themes")
    if os.path.isdir(bundled_themes):
        try:
            from core.platform_config import themes_dir as _themes_dir
            user_themes = _themes_dir()
        except Exception:
            user_themes = None
        if user_themes:
            for fname in os.listdir(bundled_themes):
                if not fname.endswith(".json"):
                    continue
                dst = os.path.join(user_themes, fname)
                if not os.path.exists(dst):  # never overwrite user's version
                    try:
                        shutil.copy2(os.path.join(bundled_themes, fname), dst)
                        log(f"  Theme: {fname}")
                    except Exception as e:
                        log(f"  Theme copy failed: {fname}: {e}", "WARN")

    # Write path files with fully expanded real paths
    write_python_path(python_exe, install_dir)
    write_mflow_path(install_dir, install_dir)

    # -- Step 4: Install Resolve launchers ---------------------------------
    sep()
    print("\n[4/4] DaVinci Resolve integration\n")
    print("  MFlow comes with two launchers:")
    print("  • MFlow Studio  — MFlow.lua → Scripts/Utility   (any Resolve page, requires Studio)")
    print("  • MFlow Free    — MFlow_Free.py → Scripts/Comp  (Fusion page only, free version)")
    print()

    yn_studio = input("  Install Studio launcher (MFlow.lua)? [Y/n]: ").strip().lower()
    install_studio = yn_studio != 'n'
    yn_free   = input("  Install Free launcher (MFlow_Free.py)? [Y/n]: ").strip().lower()
    install_free   = yn_free   != 'n'
    print()

    # 4a. Studio version — Scripts/Utility/ (any page, uses Lua + external process)
    if install_studio:
        scripts_utility = find_scripts_dir()
        if not scripts_utility:
            # Try to create the first candidate path
            candidates = SCRIPTS_UTILITY.get(PLAT, [])
            if candidates:
                _, err = safe(os.makedirs, candidates[0], exist_ok=True)
                scripts_utility = candidates[0] if not err else None
        if scripts_utility:
            log(f"Studio launcher → {scripts_utility}")
            for fname in ("MFlow.lua", "python_path.txt"):
                src = os.path.join(install_dir, fname)
                if not os.path.isfile(src):
                    src = os.path.join(HERE, fname)
                if os.path.isfile(src):
                    _, err = safe(shutil.copy2, src, os.path.join(scripts_utility, fname))
                    if err: log(f"  Cannot copy {fname}: {err}", "WARN")
                    else:   log(f"  OK  {fname}")
            write_mflow_path(install_dir, scripts_utility)
        else:
            log("Could not find or create Scripts/Utility — copy MFlow.lua manually", "WARN")
            for d in SCRIPTS_UTILITY.get(PLAT, []):
                log(f"  {d}", "")
    else:
        log("Studio launcher skipped")

    # 4b. Free version — Scripts/Comp/ (Fusion page only, uses injected 'app')
    if install_free:
        scripts_comp = find_scripts_comp()
        if not scripts_comp:
            candidates = SCRIPTS_COMP.get(PLAT, [])
            if candidates:
                _, err = safe(os.makedirs, candidates[0], exist_ok=True)
                scripts_comp = candidates[0] if not err else None
        if scripts_comp:
            log(f"Free launcher   → {scripts_comp}")
            for fname in ("MFlow_Free.py",):
                src = os.path.join(install_dir, fname)
                if not os.path.isfile(src):
                    src = os.path.join(HERE, fname)
                if os.path.isfile(src):
                    _, err = safe(shutil.copy2, src, os.path.join(scripts_comp, fname))
                    if err: log(f"  Cannot copy {fname}: {err}", "WARN")
                    else:   log(f"  OK  {fname}")
                else:
                    log(f"  Not found: {fname}", "WARN")
            write_mflow_path(install_dir, scripts_comp)
        else:
            log("Could not find or create Scripts/Comp — copy MFlow_Free.py manually", "WARN")
            for d in SCRIPTS_COMP.get(PLAT, []):
                log(f"  {d}", "")
    else:
        log("Free launcher skipped")

    # -- Summary ------------------------------------------------------------
    sep("=")
    print(f"\n  MFlow {MFLOW_VERSION} installed")
    print(f"  Python:    {python_exe}")
    print(f"  App code:  {install_dir}")
    try:
        from core.platform_config import app_data_dir as _adir2
        print(f"  Your data: {_adir2()}")
    except Exception:
        pass
    print()
    if install_studio:
        print("  Studio (any page):  Workspace > Scripts > MFlow")
    if install_free:
        print("  Free   (Fusion pg): Scripts > Comp > MFlow_Free")
    print()
    print(f"  Log:      {os.path.join(os.path.expanduser('~'), '.mflow', 'mflow.log')}")
    print()
    print("  Run standalone:  python main.py")
    print()
    sep("=")
    input("Press Enter to close...")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
    except Exception as e:
        import traceback
        print(f"\n[FATAL] Unexpected error: {e}")
        traceback.print_exc()
        input("\nPress Enter to close...")
