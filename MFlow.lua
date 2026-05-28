-- MFlow launcher
-- Coloca en: %APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\
-- Resolve (pagina Fusion): Workspace > Scripts > MFlow

-- ── Lee mflow_path.txt junto a este script ───────────────────────────────────
local script_dir = (debug.getinfo(1,"S").source or ""):match("^@(.+)[/\\][^/\\]+$") or ""
local default_dir = os.getenv("LOCALAPPDATA") and (os.getenv("LOCALAPPDATA") .. "\\MFlow")
                    or (os.getenv("HOME") and (os.getenv("HOME") .. "/.local/share/MFlow"))
                    or ""

local mflow_dir = default_dir
local path_file = script_dir .. "\\mflow_path.txt"
local pf = io.open(path_file, "r")
if pf then
    local p = pf:read("*l"); pf:close()
    if p and p ~= "" then mflow_dir = p end
end

local main_py = mflow_dir .. (package.config:sub(1,1)=="\\") and "\\main.py" or "/main.py"

-- ── Auto-detecta Python ──────────────────────────────────────────────────────
-- Lee python_path.txt junto a este script (escrito por install.py)
local python_exe = nil
local py_file = script_dir .. "\\python_path.txt"
local pyf = io.open(py_file, "r")
if pyf then
    local p = pyf:read("*l"); pyf:close()
    if p and p ~= "" then python_exe = p end
end

-- Fallback: buscar en rutas comunes de Windows
if not python_exe then
    local candidates = {
        os.getenv("LOCALAPPDATA") .. "\\Programs\\Python\\Python311\\python.exe",
        os.getenv("LOCALAPPDATA") .. "\\Programs\\Python\\Python310\\python.exe",
        os.getenv("LOCALAPPDATA") .. "\\Programs\\Python\\Python312\\python.exe",
        "python",  -- en PATH
    }
    for _, c in ipairs(candidates) do
        local test = io.open(c, "r")
        if test then test:close(); python_exe = c; break end
        if c == "python" then python_exe = c; break end
    end
end

-- ── Lanzar ───────────────────────────────────────────────────────────────────
local is_win = (package.config:sub(1,1) == "\\")
local cmd
if is_win then
    cmd = string.format('start "" /B "%s" "%s"', python_exe, main_py)
else
    cmd = string.format('"%s" "%s" &', python_exe, main_py)
end

os.execute(cmd)
