import json, os, copy
from core.platform_config import profiles_state_file, builtin_presets_dir

def _rj(path):
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except Exception: return None

def _wj(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=2)
        return True
    except Exception: return False

def load_builtin(library):
    p = os.path.join(builtin_presets_dir(), f"{library}.json")
    d = _rj(p)
    return d if isinstance(d, list) else []

_EMPTY = {"version": 1, "active": "Default", "profiles": {"Default": []}}

def load_profiles():
    d = _rj(profiles_state_file())
    return d if isinstance(d, dict) and "profiles" in d else copy.deepcopy(_EMPTY)

def save_profiles(state): return _wj(profiles_state_file(), state)

def active_presets(state): return state["profiles"].get(state["active"], [])

def add_preset(state, preset):
    active_presets(state).append(copy.deepcopy(preset))
    save_profiles(state); return state

def delete_preset(state, idx):
    p = active_presets(state)
    if 0 <= idx < len(p): p.pop(idx); save_profiles(state)
    return state

def new_profile(state, name):
    name = name.strip()
    if name and name not in state["profiles"]:
        state["profiles"][name] = []; state["active"] = name; save_profiles(state)
    return state

def delete_profile(state, name):
    if name in state["profiles"] and len(state["profiles"]) > 1:
        del state["profiles"][name]
        state["active"] = next(iter(state["profiles"]))
        save_profiles(state)
    return state

def switch_profile(state, name):
    if name in state["profiles"]: state["active"] = name; save_profiles(state)
    return state
