import os, sys, platform

_PLAT  = platform.system()
_FROZEN = getattr(sys, "frozen", False)


def app_data_dir() -> str:
    if _PLAT == "Windows":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif _PLAT == "Darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    p = os.path.join(base, "FusionFlow")
    os.makedirs(p, exist_ok=True)
    return p

def settings_file()       -> str: return os.path.join(app_data_dir(), "settings.json")
def profiles_state_file() -> str: return os.path.join(app_data_dir(), "profiles.json")

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
