r"""
Preset storage — one JSON file per (profile, library/mode) pair, under
%APPDATA%\MFlow\profiles\<profile>\<mode>.json (Windows; see app_data_dir()
for other platforms). profiles.json at the top level is now just a small
index: {"version": 2, "active": "<name>", "profiles": ["Default", ...]}.

Why per-file instead of one big profiles.json blob:
  - A single blob mixed every mode's presets together per profile in one
    flat list. Any operation that rewrote "the active profile's list"
    (e.g. reorder_presets, used by Sort A-Z/Z-A) silently discarded every
    preset belonging to OTHER modes in that profile — a real data-loss bug,
    not hypothetical (confirmed in the field: an empty "Default" after a
    sort in a mode where its list happened to be short/empty).
  - Per-file storage makes that class of bug structurally impossible:
    an operation scoped to one mode can only ever touch that mode's file.
  - Each file is independently inspectable/backup-able, and a write failure
    in one file can't corrupt another mode's data.

Legacy migration: if profiles.json is still in the old single-blob format
({"profiles": {name: [presets...]}}), it's split into per-file storage once
and profiles.json is rewritten as the new slim index. Old file is not
deleted (renamed to profiles.legacy.json) so nothing is destroyed by the
migration itself.
"""
import json, os, re, copy, logging
from core.platform_config import profiles_index_file, profiles_dir, builtin_presets_dir, app_data_dir

log = logging.getLogger("mflow")


def _rj(path):
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except Exception:
        return None


def _wj(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=2)
        return True
    except Exception as e:
        log.error("[Preset] Failed writing %s: %s", path, e)
        return False


def load_builtin(library):
    p = os.path.join(builtin_presets_dir(), f"{library}.json")
    d = _rj(p)
    return d if isinstance(d, list) else []


_EMPTY_INDEX = {"version": 2, "active": "Default", "profiles": ["Default"]}


def _sanitize(name):
    """Filesystem-safe folder name — strips characters invalid on Windows."""
    s = re.sub(r'[<>:"/\\|?*]', "_", name).strip()
    return s or "profile"


def _profile_dir(name):
    return os.path.join(profiles_dir(), _sanitize(name))


def _mode_file(profile_name, library):
    return os.path.join(_profile_dir(profile_name), f"{library}.json")


def _migrate_legacy(old):
    """old is a dict already confirmed to have profiles.profiles as a dict
    of {name: [presets...]} — the pre-v2 single-blob format."""
    log.info("[Preset] Migrating legacy profiles.json to per-file layout")
    names = []
    for name, presets in old.get("profiles", {}).items():
        names.append(name)
        by_lib = {}
        for p in presets:
            by_lib.setdefault(p.get("library", "easing"), []).append(p)
        for lib, plist in by_lib.items():
            _wj(_mode_file(name, lib), plist)
        os.makedirs(_profile_dir(name), exist_ok=True)  # keep empty profiles too
    if not names:
        names = ["Default"]
    active = old.get("active")
    if active not in names:
        active = names[0]
    idx = {"version": 2, "active": active, "profiles": names}
    # Preserve the old file instead of silently overwriting it, in case the
    # migration itself has a bug — nothing about this should be able to lose
    # data the user already had on disk.
    legacy_path = os.path.join(app_data_dir(), "profiles.legacy.json")
    try:
        if not os.path.exists(legacy_path):
            _wj(legacy_path, old)
    except Exception as e:
        log.warning("[Preset] Could not preserve legacy profiles.json: %s", e)
    save_profiles(idx)
    return idx


def load_profiles():
    """Returns the profile INDEX: {"active": name, "profiles": [names...]}.
    Does not load any preset data — use load_active_presets() for that."""
    d = _rj(profiles_index_file())
    if isinstance(d, dict) and isinstance(d.get("profiles"), list):
        os.makedirs(_profile_dir(d.get("active", "Default")), exist_ok=True)
        return d
    if isinstance(d, dict) and isinstance(d.get("profiles"), dict):
        return _migrate_legacy(d)
    idx = copy.deepcopy(_EMPTY_INDEX)
    os.makedirs(_profile_dir(idx["active"]), exist_ok=True)
    save_profiles(idx)
    return idx


def save_profiles(state):
    return _wj(profiles_index_file(), state)


def load_active_presets(state, library):
    return load_presets(state["active"], library)


def load_presets(profile_name, library):
    d = _rj(_mode_file(profile_name, library))
    return d if isinstance(d, list) else []


def save_presets(profile_name, library, presets):
    return _wj(_mode_file(profile_name, library), presets)


def add_preset(state, preset):
    library = preset.get("library", "easing")
    presets = load_presets(state["active"], library)
    presets.append(copy.deepcopy(preset))
    ok = save_presets(state["active"], library, presets)
    if not ok:
        log.error("[Preset] add_preset: save failed for profile=%s library=%s",
                   state["active"], library)
    return state, ok


def delete_preset(state, idx, library):
    """idx is the position within THIS library's saved-preset list for the
    active profile — the exact same list load_library() sends to JS.
    Returns (state, ok) — ok=False means idx was out of range."""
    presets = load_presets(state["active"], library)
    if 0 <= idx < len(presets):
        presets.pop(idx)
        ok = save_presets(state["active"], library, presets)
        return state, ok
    return state, False


def reorder_presets(state, library, presets):
    """Replace the SAVED order of one profile's ONE library — never touches
    any other library's file."""
    ok = save_presets(state["active"], library, presets)
    if not ok:
        log.error("[Preset] reorder_presets: save failed for profile=%s library=%s",
                   state["active"], library)
    return state, ok


def new_profile(state, name):
    name = name.strip()
    if name and name not in state["profiles"]:
        os.makedirs(_profile_dir(name), exist_ok=True)
        state["profiles"].append(name)
        state["active"] = name
        save_profiles(state)
    return state


def delete_profile(state, name):
    """Removes the profile from the index only — the folder and its preset
    files are left on disk as a safety net rather than deleted, in case this
    was clicked by accident."""
    if name in state["profiles"] and len(state["profiles"]) > 1:
        state["profiles"].remove(name)
        if state["active"] == name:
            state["active"] = state["profiles"][0]
        save_profiles(state)
    return state


def switch_profile(state, name):
    if name in state["profiles"]:
        state["active"] = name
        save_profiles(state)
    return state
