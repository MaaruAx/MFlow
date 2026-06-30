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

def delete_preset(state, idx, library, n_builtin):
    """idx is the position in the UI's (builtin + library-filtered-user) list —
    the exact same list load_library() sends to JS. The flat active_presets(state)
    list mixes EVERY library together in save order, so idx cannot index it
    directly; we must walk it filtered by `library` to find the right object.
    Returns (state, ok) — ok=False means idx pointed at a builtin (not deletable)
    or was out of range; caller should not assume anything changed.
    """
    if idx < n_builtin:
        return state, False   # builtin presets aren't part of saved data — can't delete
    target_pos = idx - n_builtin   # position within this library's saved presets only
    p = active_presets(state)
    seen = 0
    for i, pr in enumerate(p):
        if pr.get("library") == library:
            if seen == target_pos:
                p.pop(i)
                save_profiles(state)
                return state, True
            seen += 1
    return state, False

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
