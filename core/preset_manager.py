"""
Preset storage.

Layout (current, v2):
    %APPDATA%\\MFlow\\profiles.json          <- lightweight index only:
                                                 {"version": 2, "active": <name>,
                                                  "profiles": [<name>, ...]}
    %APPDATA%\\MFlow\\profiles\\<profile>\\<mode>.json
                                              <- list of presets for that one
                                                 profile+mode pair, e.g.
                                                 profiles\\Default\\easing.json

Why per-profile/per-mode files instead of one big blob:
Previously the whole app kept ONE dict in memory (profile name -> flat list
of every preset in every mode) and wrote the ENTIRE thing back to disk on
every save. That made it possible for an operation scoped to a single mode
(e.g. "Sort A-Z" while looking at the Spring tab) to overwrite the in-memory
list with only the Spring presets and then persist that over the top of the
real file — silently deleting every Easing/Bounce/etc. preset the user had
saved in that profile. Splitting storage by profile+mode makes that class of
bug structurally impossible: an operation on one mode can only ever touch
that mode's file.

Legacy migration:
On first load, if profiles.json is still in the old v1 shape
({"active":..., "profiles": {name: [presets...]}}), it's split into the new
per-file layout and the original is preserved untouched as
profiles.legacy.json (never deleted) so nothing is ever lost mid-migration.
"""
import json, os, shutil, copy, logging
from core.platform_config import profiles_index_file, profiles_dir, builtin_presets_dir

log = logging.getLogger("mflow")


def _rj(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _wj(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        log.error("[Preset] Failed to write %s: %s", path, e)
        return False


def load_builtin(library):
    p = os.path.join(builtin_presets_dir(), f"{library}.json")
    d = _rj(p)
    return d if isinstance(d, list) else []


_EMPTY_INDEX = {"version": 2, "active": "Default", "profiles": ["Default"], "seeded_defaults": False}


def _profile_dir(name):
    p = os.path.join(profiles_dir(), name)
    os.makedirs(p, exist_ok=True)
    return p


def _mode_file(profile, library):
    return os.path.join(_profile_dir(profile), f"{library}.json")


def _migrate_legacy(index_path, legacy):
    """legacy is the old v1 dict: {"active":..., "profiles": {name: [preset,...]}}.
    Splits every profile's mixed preset list out into per-mode files, backs
    up the original file untouched, and returns the new v2 index."""
    profs = legacy.get("profiles") or {}
    log.info("[Preset] Migrating legacy profiles.json to per-file layout")
    names = []
    for name, presets in profs.items():
        name = str(name)
        names.append(name)
        _profile_dir(name)  # always create the folder, even if empty
        by_mode = {}
        if isinstance(presets, list):
            for p in presets:
                if isinstance(p, dict):
                    lib = p.get("library", "easing")
                    by_mode.setdefault(lib, []).append(p)
        for lib, plist in by_mode.items():
            _wj(_mode_file(name, lib), plist)

    if not names:
        names = ["Default"]
        _profile_dir("Default")

    try:
        backup = os.path.join(os.path.dirname(index_path), "profiles.legacy.json")
        if not os.path.exists(backup):
            shutil.copy2(index_path, backup)
    except Exception as e:
        log.warning("[Preset] Could not back up legacy profiles.json: %s", e)

    active = legacy.get("active")
    if active not in names:
        active = names[0]
    new_index = {"version": 2, "active": active, "profiles": names}
    _wj(index_path, new_index)
    log.info("[Preset] Migration complete — profiles=%s active=%r", names, active)
    return new_index


def _seed_default_from_builtins():
    """Copies every presets/<mode>.json bundled with the install into
    profiles/Default/<mode>.json as normal, editable presets — this is what
    a first-time user (or an existing user who never had them) sees under
    Default. Only writes a mode file that doesn't already exist for Default,
    so it can never overwrite anything a user already saved there. Runs
    exactly once per install (gated by the "seeded_defaults" flag in the
    index) — deleting the seeded presets afterward is a normal delete and
    they will NOT come back on next launch.

    Returns True if the builtin presets directory was found (i.e. seeding
    genuinely had a chance to happen — including the edge case where it's
    empty on purpose), and False if it wasn't found at all. Callers should
    only persist the "seeded_defaults" flag on True: a False here almost
    always means an incomplete/broken install (the presets/ folder never
    got bundled or copied), and retrying on the next launch — once the
    install is fixed — is far better than silently never seeding again
    because a broken run happened to set the flag first."""
    try:
        bdir = builtin_presets_dir()
        if not os.path.isdir(bdir):
            log.warning("[Preset] Builtin presets dir not found at %s — "
                        "skipping seed, will retry on next launch", bdir)
            return False
        for fname in os.listdir(bdir):
            if not fname.endswith(".json"):
                continue
            mode = fname[:-5]
            dest = _mode_file("Default", mode)
            if os.path.exists(dest):
                continue  # never clobber existing user data
            data = _rj(os.path.join(bdir, fname))
            if isinstance(data, list) and data:
                _wj(dest, data)
                log.info("[Preset] Seeded Default/%s.json with %d factory preset(s)",
                          mode, len(data))
        return True
    except Exception as e:
        log.warning("[Preset] Seeding Default from builtins failed: %s", e)
        return False


def load_profiles():
    """Loads the lightweight index: {"active": name, "profiles": [names]}.
    Per-mode preset lists are NOT loaded here — see active_presets()."""
    idx_path = profiles_index_file()
    d = _rj(idx_path)

    if isinstance(d, dict) and isinstance(d.get("profiles"), list) and "active" in d:
        # Already v2. Make sure every listed profile at least has a folder.
        for name in d["profiles"]:
            _profile_dir(name)
        if not d.get("seeded_defaults"):
            if _seed_default_from_builtins():
                d["seeded_defaults"] = True
                save_index(d)
        return d

    if isinstance(d, dict) and isinstance(d.get("profiles"), dict):
        migrated = _migrate_legacy(idx_path, d)
        if not migrated.get("seeded_defaults"):
            if _seed_default_from_builtins():
                migrated["seeded_defaults"] = True
                save_index(migrated)
        return migrated

    fresh = copy.deepcopy(_EMPTY_INDEX)
    _profile_dir("Default")
    if _seed_default_from_builtins():
        fresh["seeded_defaults"] = True
    _wj(idx_path, fresh)
    return fresh


def save_index(state):
    """Persists the lightweight index (active profile, profile names, and
    the one-time seeded_defaults flag). Never touches any preset data."""
    return _wj(profiles_index_file(), {
        "version": 2,
        "active": state.get("active", "Default"),
        "profiles": list(state.get("profiles", ["Default"])),
        "seeded_defaults": bool(state.get("seeded_defaults", False)),
    })


# Kept for backward compatibility with older call sites / imports.
save_profiles = save_index


def load_mode_presets(profile, library):
    d = _rj(_mode_file(profile, library))
    return d if isinstance(d, list) else []


def save_mode_presets(profile, library, presets):
    return _wj(_mode_file(profile, library), presets)


def active_presets(state, library=None):
    """Presets for the active profile.
    - library given (normal path): reads just that one mode's file. Cheap,
      and the read can never be polluted by another mode's data.
    - library=None (export-all / debug only): concatenates every mode file
      found under the active profile's folder."""
    active = state.get("active", "Default")
    if library is not None:
        return load_mode_presets(active, library)
    all_presets = []
    d = _profile_dir(active)
    try:
        for fname in sorted(os.listdir(d)):
            if fname.endswith(".json"):
                all_presets.extend(load_mode_presets(active, fname[:-5]))
    except Exception as e:
        log.warning("[Preset] active_presets(all modes) failed for %r: %s", active, e)
    return all_presets


def add_preset(state, preset):
    """Adds/overwrites a preset in the active profile's file for its own
    mode only. Guards against duplicates (same name, same library) —
    without this a double-click or a re-import could silently pile up
    copies with no way to tell them apart in the UI."""
    lib = preset.get("library", "easing")
    name = preset.get("name", "")
    active = state.get("active", "Default")
    presets = load_mode_presets(active, lib)
    for p in presets:
        if p.get("name") == name:
            p.update(copy.deepcopy(preset))
            save_mode_presets(active, lib, presets)
            return state
    presets.append(copy.deepcopy(preset))
    save_mode_presets(active, lib, presets)
    return state


def delete_preset(state, idx, library):
    """idx is the position within that single mode's file — matches exactly
    what the UI grid shows for the active mode, no offset math needed since
    built-ins were removed from the grid.
    Returns (state, ok) — ok=False means idx was out of range."""
    active = state.get("active", "Default")
    presets = load_mode_presets(active, library)
    if 0 <= idx < len(presets):
        presets.pop(idx)
        save_mode_presets(active, library, presets)
        return state, True
    return state, False


def reorder_presets(state, library, presets):
    """Overwrites ONLY the given mode's file for the active profile. This is
    the fix for the data-loss bug: sorting can never again wipe out presets
    that live in a different mode of the same profile."""
    active = state.get("active", "Default")
    save_mode_presets(active, library, presets)
    return state


def new_profile(state, name):
    name = name.strip()
    names = state.setdefault("profiles", [])
    if name and name not in names:
        names.append(name)
        state["active"] = name
        _profile_dir(name)  # empty folder — no mode files until something is saved
        save_index(state)
    return state


def delete_profile(state, name):
    names = state.get("profiles", [])
    if name in names and len(names) > 1:
        names.remove(name)
        if state.get("active") == name:
            state["active"] = names[0]
        save_index(state)
        # Deliberately NOT deleting the on-disk folder — keeps the presets
        # recoverable if the profile was removed by mistake.
    return state


def switch_profile(state, name):
    if name in state.get("profiles", []):
        state["active"] = name
        save_index(state)
    return state
