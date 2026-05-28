"""
MFlow installer — python install.py
"""
import subprocess, sys, os, shutil, platform, glob

HERE = os.path.dirname(os.path.abspath(__file__))
PLAT = platform.system()

SCRIPTS_DIRS = {
    "Windows": [
        os.path.expandvars(r"%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility"),
        r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Utility",
    ],
    "Darwin":  [os.path.expanduser("~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility")],
    "Linux":   [os.path.expanduser("~/.local/share/DaVinciResolve/Fusion/Scripts/Utility"),
                "/opt/resolve/Fusion/Scripts/Utility"],
}

def sep(): print("─" * 52)

def find_all_pythons():
    """Find every Python ≥3.9 on the system (Windows-focused)."""
    found = {}  # path -> version string

    # 1. Current interpreter
    v = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    found[sys.executable] = v

    if PLAT == "Windows":
        # 2. All pythonX.Y.exe under LOCALAPPDATA\Programs\Python\
        base = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python")
        for exe in glob.glob(os.path.join(base, "Python3*", "python.exe")):
            _probe(exe, found)
        # 3. py launcher
        for ver in ("3.12", "3.11", "3.10", "3.9"):
            _probe_launcher(ver, found)
    else:
        for name in ("python3", "python3.12", "python3.11", "python3.10", "python3.9"):
            exe = shutil.which(name)
            if exe:
                _probe(exe, found)

    # Filter Windows Store stubs and < 3.9
    result = {}
    for exe, ver in found.items():
        if "WindowsApps" in exe or "PythonSoftwareFoundation" in exe:
            continue
        try:
            maj, minor = int(ver.split(".")[0]), int(ver.split(".")[1])
            if maj == 3 and minor >= 9:
                result[exe] = ver
        except Exception:
            pass
    return result

def _probe(exe, found):
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
        ver = (r.stdout + r.stderr).strip().replace("Python ", "")
        if ver:
            found[exe] = ver
    except Exception:
        pass

def _probe_launcher(ver, found):
    try:
        r = subprocess.run(["py", f"-{ver}", "-c", "import sys;print(sys.executable)"],
                           capture_output=True, text=True, timeout=5)
        exe = r.stdout.strip()
        if exe and os.path.isfile(exe):
            _probe(exe, found)
    except Exception:
        pass

def pick_python(pythons):
    """Auto-select best Python (highest version). Print what was chosen."""
    if not pythons:
        return sys.executable
    # Sort by version descending
    def ver_key(item):
        try: return tuple(int(x) for x in item[1].split(".")[:3])
        except: return (0,0,0)
    best_exe, best_ver = sorted(pythons.items(), key=ver_key, reverse=True)[0]
    print(f"\n  Versiones encontradas:")
    for exe, ver in sorted(pythons.items(), key=ver_key, reverse=True):
        mark = " ← seleccionado" if exe == best_exe else ""
        print(f"    {ver}  {exe}{mark}")
    return best_exe

def pip_install(python_exe, pkg):
    print(f"  Instalando {pkg} ...", end=" ", flush=True)
    try:
        r = subprocess.run(
            [python_exe, "-m", "pip", "install", "--upgrade", pkg],
            capture_output=True, text=True, timeout=180
        )
        if r.returncode == 0:
            print("OK"); return True
        errs = [l for l in r.stderr.strip().splitlines() if l.strip()]
        print(f"ERROR  {errs[-1][:100] if errs else '?'}"); return False
    except Exception as e:
        print(f"ERROR  {e}"); return False

def find_scripts_dir():
    for d in SCRIPTS_DIRS.get(PLAT, []):
        if os.path.isdir(d):
            return d
    first = SCRIPTS_DIRS.get(PLAT, [None])[0]
    if first:
        try:
            os.makedirs(first, exist_ok=True)
            return first
        except Exception:
            pass
    return None

def main():
    if "WindowsApps" in sys.executable or "PythonSoftwareFoundation" in sys.executable:
        print("\n[!] Estas usando el Python de Microsoft Store.")
        print("    Descarga Python desde https://www.python.org/downloads/")
        input("\nPresiona Enter para cerrar...")
        return

    print()
    print("  MFlow  —  Installer")
    sep()

    # Python detection
    print("\n[1/3] Detectando Python...")
    pythons = find_all_pythons()
    if not pythons:
        print("  No se encontro Python 3.9+. Instala desde https://www.python.org")
        input("\nPresiona Enter para cerrar..."); return

    python_exe = pick_python(pythons)

    # Save python_path.txt
    txt_path = os.path.join(HERE, "python_path.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(python_exe)

    sep()
    print("\n[2/3] PySide6")
    pip_install(python_exe, "PySide6")

    sep()
    # Create install dir and copy all files
    install_dir = os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "MFlow"
    )
    print(f"\n[3/3] Instalando en: {install_dir}")
    try:
        os.makedirs(install_dir, exist_ok=True)
        for item in os.listdir(HERE):
            src = os.path.join(HERE, item)
            dst = os.path.join(install_dir, item)
            try:
                if os.path.isdir(src):
                    if os.path.exists(dst): shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
            except Exception: pass
        # Write path files into install_dir
        with open(os.path.join(install_dir, "mflow_path.txt"), "w") as f:
            f.write(install_dir)
        with open(os.path.join(install_dir, "python_path.txt"), "w") as f:
            f.write(python_exe)
        print(f"  OK")
    except Exception as e:
        print(f"  WARN: {e}")
        install_dir = HERE

    # Copy launcher files to Resolve Scripts\Utility
    d = find_scripts_dir()
    if d:
        for fname in ("MFlow.lua", "mflow_path.txt", "python_path.txt"):
            src = os.path.join(install_dir, fname)
            if not os.path.isfile(src):
                src = os.path.join(HERE, fname)
            if os.path.isfile(src):
                try:
                    shutil.copy2(src, os.path.join(d, fname))
                    print(f"  OK  {os.path.join(d, fname)}")
                except Exception as e:
                    print(f"  WARN {fname}: {e}")
    else:
        print("  Copia MFlow.lua, mflow_path.txt y python_path.txt a:")
        print(f"  %APPDATA%\\Blackmagic Design\\DaVinci Resolve\\Support\\Fusion\\Scripts\\Utility\\")

    sep()
    print(f"\n  Python:    {python_exe}")
    print(f"  MFlow:     {install_dir}")
    print(f"  Resolve:   Workspace > Scripts > MFlow  (pagina Fusion)\n")
    input("Presiona Enter para cerrar...")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback; traceback.print_exc()
        input("\nPresiona Enter para cerrar...")
