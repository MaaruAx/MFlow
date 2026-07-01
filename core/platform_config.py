import os, sys, platform

_PLAT  = platform.system()
_FROZEN = getattr(sys, "frozen", False)


def win_subprocess_kwargs() -> dict:
    """Extra kwargs for subprocess.run()/Popen() that keep a console-subsystem
    child process (python.exe, py.exe launcher, etc.) from flashing open its
    own console window when spawned from a windowed/frozen GUI app on Windows.

    Two independent suppression mechanisms are combined on purpose:
      1. creationflags=CREATE_NO_WINDOW — tells the OS not to allocate a
         console for the child process at all.
      2. STARTUPINFO(STARTF_USESHOWWINDOW, wShowWindow=SW_HIDE) — a second,
         independent hint that keeps any window the child *does* create
         hidden.
    Belt-and-suspenders is intentional here: CREATE_NO_WINDOW alone is the
    documented approach, but DETACHED_PROCESS-style flags are known to still
    flash a console on some Windows builds (see CPython bpo-41619 / GH-85785).
    Pairing it with STARTUPINFO/SW_HIDE closes that gap without relying on a
    single mechanism.

    No-op (returns {}) on non-Windows platforms, and fails safe (returns {})
    if anything about the Windows-only subprocess APIs is unavailable —
    a console-hiding helper should never be the reason a subprocess call
    itself breaks.
    """
    if _PLAT != "Windows":
        return {}
    try:
        import subprocess
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        return {
            "startupinfo": si,
            "creationflags": subprocess.CREATE_NO_WINDOW,
        }
    except Exception:
        return {}


def app_data_dir() -> str:
    if _PLAT == "Windows":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif _PLAT == "Darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    p = os.path.join(base, "MFlow")
    os.makedirs(p, exist_ok=True)
    # Migrate data from old FusionFlow directory if it exists and MFlow is empty
    old = os.path.join(base, "FusionFlow")
    if os.path.isdir(old) and not any(
        f.endswith((".json",)) for f in os.listdir(p)
    ):
        import shutil
        for fname in os.listdir(old):
            src = os.path.join(old, fname)
            dst = os.path.join(p, fname)
            if not os.path.exists(dst):
                try:
                    shutil.copy2(src, dst)
                except Exception:
                    pass
    return p

def settings_file()       -> str: return os.path.join(app_data_dir(), "settings.json")
def profiles_state_file() -> str: return os.path.join(app_data_dir(), "profiles.json")
def themes_dir()          -> str:
    p = os.path.join(app_data_dir(), "themes")
    os.makedirs(p, exist_ok=True)
    return p

def bundled_themes_dir() -> str:
    """themes/ folder inside the MFlow install directory (next to main.py)."""
    base = os.path.dirname(sys.executable) if _FROZEN else \
           os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "themes")

def language_dir() -> str:
    """language/ folder inside the MFlow install directory (next to main.py)."""
    base = os.path.dirname(sys.executable) if _FROZEN else \
           os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(base, "language")
    os.makedirs(p, exist_ok=True)
    return p
def builtin_presets_dir() -> str:
    base = os.path.dirname(sys.executable) if _FROZEN else \
           os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "presets")

# Exact paths Resolve uses on each platform
RESOLVE_MODULE_PATHS = {
    "Windows": [
        r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules",
    ],
    "Darwin": [
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
    ],
    "Linux": [
        "/opt/resolve/Developer/Scripting/Modules",
        "/home/resolve/Developer/Scripting/Modules",
    ],
}

FUSIONSCRIPT_PATHS = {
    "Windows": [
        r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll",
    ],
    "Darwin": [
        "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so",
    ],
    "Linux": [
        "/opt/resolve/libs/Fusion/fusionscript.so",
    ],
}

def resolve_module_paths(custom: str = "") -> list:
    paths = list(RESOLVE_MODULE_PATHS.get(_PLAT, []))
    if custom and os.path.isdir(custom) and custom not in paths:
        paths.insert(0, custom)
    return paths

def fusionscript_path() -> str:
    for p in FUSIONSCRIPT_PATHS.get(_PLAT, []):
        if os.path.exists(p):
            return p
    return ""
