-- MFlow launcher
-- Place in: %APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\
-- In Resolve (Fusion page): Workspace > Scripts > MFlow

local is_win = (package.config:sub(1,1) == "\\")
local sep     = is_win and "\\" or "/"

-- ── Resolve script's own directory ───────────────────────────────────────────
local script_dir = (debug.getinfo(1,"S").source or ""):match("^@(.+)[/\\][^/\\]+$") or ""

-- ── Default install paths ────────────────────────────────────────────────────
local function default_mflow_dir()
    if is_win then
        local la = os.getenv("LOCALAPPDATA") or ""
        if la ~= "" then return la .. "\\MFlow" end
        local up = os.getenv("USERPROFILE") or os.getenv("HOME") or "C:\\Users\\Default"
        return up .. "\\AppData\\Local\\MFlow"
    else
        local home = os.getenv("HOME") or "/tmp"
        if os.getenv("APPDATA") then -- shouldn't happen but guard
            return home .. "/MFlow"
        end
        -- macOS: ~/Library/Application Support/MFlow
        -- Linux: ~/.local/share/MFlow
        local platform_path = home .. (is_win and "" or "/Library/Application Support")
        local linux_path    = home .. "/.local/share/MFlow"
        local mac_test = io.open(home .. "/Library", "r")
        if mac_test then mac_test:close(); return home .. "/Library/Application Support/MFlow"
        else return linux_path end
    end
end

-- ── Read mflow_path.txt if present ───────────────────────────────────────────
local mflow_dir = default_mflow_dir()
local txt_paths = {
    script_dir .. sep .. "mflow_path.txt",
    mflow_dir  .. sep .. "mflow_path.txt",
}
for _, tp in ipairs(txt_paths) do
    local f = io.open(tp, "r")
    if f then
        local p = f:read("*l"); f:close()
        if p and p ~= "" then mflow_dir = p; break end
    end
end

local main_py = mflow_dir .. sep .. "main.py"

-- ── Verify main.py exists ────────────────────────────────────────────────────
local check = io.open(main_py, "r")
if not check then
    -- Show error via a temp file that gets printed — best we can do in Lua
    local err_msg = "[MFlow] ERROR: main.py not found at: " .. main_py ..
                    "\nRun install.py first, or edit mflow_path.txt at:\n" ..
                    (script_dir ~= "" and (script_dir .. sep .. "mflow_path.txt") or "(script dir unknown)")
    print(err_msg)
    return
end
check:close()

-- ── Find Python ───────────────────────────────────────────────────────────────
local python_exe = nil

-- 1. python_path.txt written by install.py
local py_txt_paths = {
    script_dir .. sep .. "python_path.txt",
    mflow_dir  .. sep .. "python_path.txt",
}
for _, pp in ipairs(py_txt_paths) do
    local f = io.open(pp, "r")
    if f then
        local p = f:read("*l"); f:close()
        if p and p ~= "" then
            local tf = io.open(p, "r")
            if tf then tf:close(); python_exe = p; break end
        end
    end
end

-- 2. Common Windows paths fallback
if not python_exe and is_win then
    local la = os.getenv("LOCALAPPDATA") or ""
    local candidates = {
        la .. "\\Programs\\Python\\Python312\\python.exe",
        la .. "\\Programs\\Python\\Python311\\python.exe",
        la .. "\\Programs\\Python\\Python310\\python.exe",
        la .. "\\Programs\\Python\\Python39\\python.exe",
    }
    for _, c in ipairs(candidates) do
        local tf = io.open(c, "r")
        if tf then tf:close(); python_exe = c; break end
    end
end

-- 3. Last resort: rely on PATH
if not python_exe then
    python_exe = is_win and "python" or "python3"
end

-- ── Launch ────────────────────────────────────────────────────────────────────
-- Windows note: os.execute() always routes through cmd.exe (Lua's system()
-- wrapper). Resolve/Fusion has no console of its own, so Windows must
-- allocate one for that cmd.exe process regardless of what runs inside it —
-- that transient console is what briefly flashes on screen. Using pythonw.exe
-- avoids a SECOND console for the Python process itself, but does nothing
-- about the first one. The fix is to hand the actual launch to wscript.exe
-- (a GUI-subsystem executable, never allocates a console) via a throwaway
-- VBScript, and have cmd.exe's only job be to start that and return
-- immediately — its own console then exists for a negligible fraction of a
-- second instead of the multi-second flash a slower/blocking launch causes.
if is_win then
    local pyw = python_exe
    if pyw:match("python%.exe$") then
        pyw = pyw:gsub("python%.exe$", "pythonw.exe")
    elseif pyw == "python" then
        pyw = "pythonw"
    end
    local tf2 = io.open(pyw, "r")
    if tf2 then
        tf2:close()
        python_exe = pyw
    elseif pyw == "pythonw" then
        -- Bare command (PATH-resolved) can't be probed with io.open; trust
        -- it and let the launch itself fail safely if it doesn't exist.
        python_exe = pyw
    end

    local function vbs_escape(s)
        return s:gsub('"', '""')
    end

    local vbs_path = os.getenv("TEMP") or os.getenv("TMP") or "."
    vbs_path = vbs_path .. sep .. "mflow_launch_" .. tostring(os.time()) .. ".vbs"

    local vbs = io.open(vbs_path, "w")
    if vbs then
        local run_cmd = string.format('"%s" "%s"', vbs_escape(python_exe), vbs_escape(main_py))
        vbs:write('Set MFlowShell = CreateObject("WScript.Shell")\r\n')
        vbs:write('MFlowShell.Run "' .. run_cmd .. '", 0, False\r\n')
        vbs:close()

        print("[MFlow] Launching via: " .. python_exe)
        os.execute(string.format('wscript.exe //B //Nologo "%s"', vbs_path))
    else
        -- Fallback: VBS could not be written (e.g. read-only TEMP) — still
        -- attempt a direct launch rather than silently doing nothing, even
        -- though this reintroduces the brief console flash.
        local cmd = string.format('start "" /B "%s" "%s"', python_exe, main_py)
        print("[MFlow] VBS launcher unavailable, falling back to: " .. cmd)
        os.execute(cmd)
    end
else
    local cmd = string.format('"%s" "%s" > /tmp/mflow.log 2>&1 &', python_exe, main_py)
    print("[MFlow] Launching: " .. cmd)
    os.execute(cmd)
end
