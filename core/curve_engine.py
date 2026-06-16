"""
Bezier evaluation, baking (spring/elastic/bounce/steps), and Fusion spline application.
Handle writing uses every known format for Resolve compatibility.
"""
import math
import logging
from dataclasses import dataclass, field

log = logging.getLogger("mflow")


# ── Bezier ────────────────────────────────────────────────────────────────────

def _bx(s, x1, x2):
    u = 1 - s
    return 3*u*u*s*x1 + 3*u*s*s*x2 + s*s*s

def _by(s, y1, y2):
    u = 1 - s
    return 3*u*u*s*y1 + 3*u*s*s*y2 + s*s*s

def _find_s(x, x1, x2, tol=1e-5):
    lo, hi = 0.0, 1.0
    for _ in range(54):
        m = (lo + hi) * 0.5
        v = _bx(m, x1, x2)
        if abs(v - x) < tol:
            return m
        if v < x: lo = m
        else: hi = m
    return (lo + hi) * 0.5

def eval_bezier(x, h1, h2):
    if x <= 0: return 0.0
    if x >= 1: return 1.0
    return _by(_find_s(x, h1[0], h2[0]), h1[1], h2[1])

def make_lookup(h1, h2, n=256):
    return [eval_bezier(i/n, h1, h2) for i in range(n+1)]


# ── Easing functions (for baking) ─────────────────────────────────────────────

def elastic_out(t, amp=1.0, period=0.3):
    if t <= 0: return 0.0
    if t >= 1: return 1.0
    a = max(amp, 1.0)
    s = period / (2*math.pi) * math.asin(1/a)
    return a * (2**(-10*t)) * math.sin((t-s)*(2*math.pi)/period) + 1.0

def elastic_in(t, amp=1.0, period=0.3):
    return 1.0 - elastic_out(1-t, amp, period)

def elastic_in_out(t, amp=1.0, period=0.3):
    return elastic_in(t*2, amp, period)*0.5 if t < 0.5 else elastic_out(t*2-1, amp, period)*0.5+0.5

def bounce_out(t):
    n1, d1 = 7.5625, 2.75
    if t < 1/d1:     return n1*t*t
    elif t < 2/d1:   t -= 1.5/d1;  return n1*t*t + 0.75
    elif t < 2.5/d1: t -= 2.25/d1; return n1*t*t + 0.9375
    else:            t -= 2.625/d1; return n1*t*t + 0.984375

def bounce_in(t):     return 1.0 - bounce_out(1-t)
def bounce_in_out(t): return bounce_in(t*2)*0.5 if t < 0.5 else bounce_out(t*2-1)*0.5+0.5

_BAKE_FNS = {
    "elastic_out": elastic_out,
    "elastic_in":  elastic_in,
    "elastic_in_out": elastic_in_out,
    "bounce_out":  bounce_out,
    "bounce_in":   bounce_in,
    "bounce_in_out": bounce_in_out,
}


# ── Frame baking ──────────────────────────────────────────────────────────────

def bake_fn(fn_name, t0, v0, t1, v1, fps, params=None):
    """Compute [(abs_time, value), ...] for every frame using a named easing fn."""
    fn = _BAKE_FNS.get(fn_name)
    if fn is None:
        return []
    params = params or {}
    n = max(1, round((t1-t0)*fps))
    result = []
    for i in range(n+1):
        tn = i/n
        vn = fn(tn, **params) if params else fn(tn)
        result.append((t0 + tn*(t1-t0), v0 + vn*(v1-v0)))
    return result

def bake_spring(t0, v0, t1, v1, fps, mass=1.0, stiffness=100.0, damping=15.0, velocity=0.0):
    """Euler-integrated spring."""
    n = max(1, round((t1-t0)*fps))
    dt = 1.0/fps
    pos, vel = 0.0, float(velocity)
    result = []
    for i in range(n+1):
        result.append((t0 + i*dt, v0 + pos*(v1-v0)))
        force = -stiffness*(pos-1.0) - damping*vel
        vel  += (force/mass)*dt
        pos  += vel*dt
    return result


# ── Overframe point ───────────────────────────────────────────────────────────

def eval_spring_osc(t: float, zeta: float, omega_n: float) -> float:
    """Damped harmonic oscillator position x(t).
    Formula: x(t) = 1 - e^(-ζω_n·t) · (cos(ω_d·t) + (ζω_n/ω_d)·sin(ω_d·t))
    """
    if t <= 0: return 0.0
    zeta    = max(1e-4, zeta)
    omega_n = max(1e-4, omega_n)
    if zeta >= 1.0:
        return 1.0 - math.exp(-zeta * omega_n * t) * (1.0 + zeta * omega_n * t)
    omega_d = omega_n * math.sqrt(1.0 - zeta * zeta)
    return 1.0 - math.exp(-zeta * omega_n * t) * (
        math.cos(omega_d * t) + (zeta * omega_n / omega_d) * math.sin(omega_d * t)
    )


def bake_oscillator(t0: float, v0: float, t1: float, v1: float,
                    fps: float, zeta: float = 0.3, omega_n: float = 8.0) -> list:
    zeta    = max(0.01, min(0.99, zeta))
    omega_n = max(0.5, omega_n)
    # Use actual duration in seconds so omega_n (speed) changes the baked shape:
    # high omega_n = spring settles quickly within the range,
    # low omega_n  = spring barely starts within the range.
    n = max(1, int(round(t1 - t0)))
    T = (t1 - t0) / fps          # actual duration in seconds
    result = []
    for i in range(n + 1):
        tn  = i / n
        val = eval_spring_osc(tn * T, zeta, omega_n)
        result.append((int(round(t0)) + i, v0 + val * (v1 - v0)))
    # Force exact endpoint alignment
    result[0]  = (result[0][0],  v0)
    result[-1] = (result[-1][0], v1)
    return result


# ── OverkeyFrame point ────────────────────────────────────────────────────────

from dataclasses import dataclass, field as _field

@dataclass
class OverframePoint:
    t:       float = 0.5
    v:       float = 0.5
    lh:      list  = _field(default_factory=lambda: [-0.1, 0.0])
    rh:      list  = _field(default_factory=lambda: [0.1,  0.0])
    tangent: str   = "smooth"

    def apply_smooth(self):
        self.lh = [-self.rh[0], -self.rh[1]]

    def apply_sym(self):
        mag = math.hypot(*self.rh)
        ang = math.atan2(self.rh[1], self.rh[0])
        self.lh = [-mag * math.cos(ang), -mag * math.sin(ang)]


# ── Penner elastic ────────────────────────────────────────────────────────────

def eval_elastic_penner(t: float, amplitude: float = 1.0, period: float = 0.3) -> float:
    """Penner easeInElastic — oscillation at start, settles at end."""
    if t <= 0: return 0.0
    if t >= 1: return 1.0
    p = max(0.01, period)
    a = max(1.0, amplitude)
    s = (p / (2.0 * math.pi)) * math.asin(1.0 / a)
    return -(a * (2.0 ** (10.0 * (t - 1.0))) * math.sin(((t - 1.0) - s) * 2.0 * math.pi / p))


def bake_elastic_penner(t0, v0, t1, v1, fps, amplitude=1.0, period=0.3):
    n = max(1, int(round(t1 - t0)))
    result = []
    for i in range(n + 1):
        tn  = i / n
        val = eval_elastic_penner(tn, amplitude, period)
        result.append((int(round(t0)) + i, v0 + val * (v1 - v0)))
    return result


def bake_elastic_out(t0, v0, t1, v1, fps, amplitude=1.0, period=0.3):
    """Penner easeOutElastic — settles at start, oscillates at end."""
    n = max(1, int(round(t1 - t0)))
    result = []
    for i in range(n + 1):
        tn  = i / n
        val = elastic_out(tn, amplitude, period)
        result.append((int(round(t0)) + i, v0 + val * (v1 - v0)))
    result[0]  = (result[0][0],  v0)
    result[-1] = (result[-1][0], v1)
    return result


# ── Bounce (damped cosine) ────────────────────────────────────────────────────

def eval_bounce(t: float, gamma: float = 4.0, omega: float = 6.0) -> float:
    """Ceiling bounce: 1 - e^(-γt)·|cos(ωt)|  → starts 0, settles at 1."""
    if t <= 0: return 0.0
    if t >= 1: return 1.0
    return 1.0 - math.exp(-gamma * t) * abs(math.cos(omega * t))


def bake_bounce(t0, v0, t1, v1, fps, gamma=4.0, omega=6.0, flipped=False):
    """flipped=True → floor version: starts ~1, settles at 0."""
    n = max(1, int(round(t1 - t0)))
    result = []
    for i in range(n + 1):
        tn  = i / n
        val = eval_bounce(tn, gamma, omega)
        if flipped:
            val = 1.0 - val
        result.append((int(round(t0)) + i, v0 + val * (v1 - v0)))
    # Force exact keyframe alignment at endpoints
    result[0]  = (result[0][0],  v0)
    result[-1] = (result[-1][0], v1)
    return result


# ── Catenary ──────────────────────────────────────────────────────────────────

def eval_catenary(t: float, a: float = 1.0) -> float:
    """Normalized catenary: (cosh(t/a) - 1) / (cosh(1/a) - 1).
    f(0)=0, f(1)=1. Bows below diagonal (slow start, fast end).
    High a → near-linear. Low a → heavy droop / exponential-like jump.
    """
    if t <= 0: return 0.0
    if t >= 1: return 1.0
    a   = max(0.001, a)
    num = math.cosh(t / a) - 1.0
    den = math.cosh(1.0 / a) - 1.0
    if abs(den) < 1e-12:
        return t
    return max(0.0, min(1.0, num / den))


def bake_catenary(t0, v0, t1, v1, fps, a=1.0):
    n = max(1, int(round(t1 - t0)))
    result = []
    for i in range(n + 1):
        val = eval_catenary(i / n, a)
        result.append((int(round(t0)) + i, v0 + val * (v1 - v0)))
    result[0]  = (result[0][0],  v0)
    result[-1] = (result[-1][0], v1)
    return result


# ── Pulse (modulated wave) ────────────────────────────────────────────────────

def eval_pulse_raw(t: float, omega1: float, omega2: float, n: float) -> float:
    return math.sin(omega1 * math.pi * t) * abs(math.sin(omega2 * math.pi * t)) ** n


def bake_pulse(t0, v0, t1, v1, fps, omega1=8.0, omega2=2.0, n=4.0):
    frames = max(1, int(round(t1 - t0)))
    raw = [eval_pulse_raw(i / frames, omega1, omega2, n) for i in range(frames + 1)]
    r_min, r_max = min(raw), max(raw)
    span = r_max - r_min if abs(r_max - r_min) > 1e-10 else 1.0
    result = []
    for i, r in enumerate(raw):
        val = (r - r_min) / span
        result.append((int(round(t0)) + i, v0 + val * (v1 - v0)))
    result[0]  = (result[0][0],  v0)
    result[-1] = (result[-1][0], v1)
    return result


# ── Noise (smooth random) ─────────────────────────────────────────────────────

def bake_noise(t0, v0, t1, v1, fps, freq=2.0, amp=0.5, seed=42):
    """Smooth noise via cosine interpolation over seeded random control points."""
    import random
    rng    = random.Random(int(seed))
    n      = max(1, int(round(t1 - t0)))
    n_ctrl = max(2, int(freq * 4) + 1)
    ctrl   = [rng.uniform(-1.0, 1.0) for _ in range(n_ctrl)]
    result = []
    for i in range(n + 1):
        t   = i / n
        pos = t * (n_ctrl - 1)
        idx = min(int(pos), n_ctrl - 2)
        frac = pos - idx
        mu2  = (1.0 - math.cos(frac * math.pi)) / 2.0
        v    = ctrl[idx] * (1.0 - mu2) + ctrl[idx + 1] * mu2
        val  = max(0.0, min(1.0, 0.5 + v * amp))
        result.append((int(round(t0)) + i, v0 + val * (v1 - v0)))
    result[0]  = (result[0][0],  v0)
    result[-1] = (result[-1][0], v1)
    return result


# ── Resonance (forced oscillator) ─────────────────────────────────────────────

def eval_resonance_raw(t: float, gamma: float, omega: float, omega0: float) -> float:
    denom = abs(omega0 ** 2 - omega ** 2)
    A = min(1.0 / max(denom, 0.5), 5.0)
    B = -A
    return A * math.cos(omega * t) + B * math.exp(-gamma * t) * math.cos(omega0 * t)


def bake_resonance(t0, v0, t1, v1, fps, gamma=2.0, omega=8.0, omega0=8.0):
    n   = max(1, int(round(t1 - t0)))
    raw = [eval_resonance_raw(i / n, gamma, omega, omega0) for i in range(n + 1)]
    r_min, r_max = min(raw), max(raw)
    span = r_max - r_min if abs(r_max - r_min) > 1e-10 else 1.0
    result = []
    for i, r in enumerate(raw):
        val = (r - r_min) / span
        result.append((int(round(t0)) + i, v0 + val * (v1 - v0)))
    result[0]  = (result[0][0],  v0)
    result[-1] = (result[-1][0], v1)
    return result


# ── Resolve spline writing ────────────────────────────────────────────────────

def _numeric_times(sd: dict) -> list:
    """Return sorted list of only the numeric keys from a GetKeyFrames dict.
    Fusion distortion/compound nodes can return dicts with string keys like
    'Value' — filtering those out prevents float() conversion errors.
    """
    times = []
    for k in sd.keys():
        try:
            float(k)
            times.append(k)
        except (TypeError, ValueError):
            pass
    return sorted(times, key=float)

def _get_kf_range(spline):
    """Return (t0, v0, t1, v1) or None if not enough keyframes."""
    try:
        kf = spline.GetKeyFrames()
        if not kf:
            return None
        times = _numeric_times(kf)
        if len(times) < 2:
            return None
        t0, t1 = float(times[0]), float(times[-1])
        v0 = float(spline.GetInput(t0))
        v1 = float(spline.GetInput(t1))
        return t0, v0, t1, v1
    except Exception:
        return None


def _write_handle(spline, frame, side, time, value):
    """
    Try every known SetData key format for a bezier handle.
    Returns True on first success.
    """
    payload   = {1: float(time), 2: float(value)}
    frame_int = int(round(frame))
    tags = [frame, float(frame), frame_int, str(frame_int)]
    prefixes = ["Keyframes.", "Spline.Keyframes.", "Path.Keyframes."]
    for pref in prefixes:
        for tag in tags:
            try:
                spline.SetData(f"{pref}{tag}.{side}", payload)
                return True
            except Exception:
                pass
    return False


def _kf_scalar(entry):
    """Extract float value from a scalar keyframe entry."""
    if not isinstance(entry, dict):
        try: return float(entry)
        except Exception: return None
    for k in (1, 1.0, "Value"):
        if k in entry and isinstance(entry[k], (int, float)):
            return float(entry[k])
    return None


def _path_point(entry):
    """Return [x,y] if entry is a Point2D keyframe, else None."""
    if not isinstance(entry, dict): return None
    raw = entry.get(1, entry.get(1.0))
    if raw is None: return None
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        return [float(raw[0]), float(raw[1])]
    if isinstance(raw, dict):
        x = raw.get(1, raw.get("x")); y = raw.get(2, raw.get("y"))
        if x is not None and y is not None:
            return [float(x), float(y)]
    return None


def _strip_locks(tbl) -> None:
    """Remove LockedY/Locked flags from a copied keyframe dict before SetKeyFrames.
    Fusion sets LockedY=True on Displacement spline keyframes — stripping it
    from the COPY (not the original) allows handle writes to succeed."""
    for entry in tbl.values():
        if not isinstance(entry, dict): continue
        flags = entry.get("Flags")
        if not isinstance(flags, dict): continue
        new_flags = {k: v for k, v in flags.items()
                     if k not in ("LockedY", "LockedX", "Locked")}
        if new_flags: entry["Flags"] = new_flags
        else: del entry["Flags"]


def _call_set_kf(obj, tbl) -> bool:
    fn = getattr(obj, "SetKeyFrames", None)
    if not callable(fn): return False
    # Three signatures: True=force-create, False=update-existing, no arg=default.
    # PolyPath Displacement splines only accept (tbl, False) — not True.
    for args in ((tbl, True), (tbl, False), (tbl,)):
        try: fn(*args); return True
        except Exception: continue
    return False


def apply_bezier(spline, h1: list, h2: list, kf_from: int = 1, kf_to: int = 0) -> bool:
    """
    Apply cubic-bezier handles to every segment within [kf_from, kf_to].
    Each consecutive pair of keyframes in the range gets its own h1/h2 handles,
    so intermediate keyframes are never skipped or corrupted.
    kf_from/kf_to are 1-based indices; kf_to=0 means last keyframe.
    """
    get_kf = getattr(spline, "GetKeyFrames", None)
    if not callable(get_kf):
        log.warning("[MFlow] apply_bezier: no GetKeyFrames on object")
        return False
    try:
        sd = get_kf()
    except Exception as e:
        log.warning(f"[MFlow] apply_bezier: GetKeyFrames failed: {e}")
        return False

    if not isinstance(sd, dict) or len(sd) < 2:
        log.warning(f"[MFlow] apply_bezier: < 2 keyframes")
        return False

    all_times = _numeric_times(sd)
    if len(all_times) < 2:
        log.warning(f"[MFlow] apply_bezier: < 2 numeric keyframes (non-numeric keys ignored)")
        return False
    n = len(all_times)
    i0 = max(0, kf_from - 1)
    i1 = (n - 1) if kf_to == 0 else min(n - 1, kf_to - 1)
    if i1 <= i0: i1 = min(i0 + 1, n - 1)

    name = getattr(spline, "Name", "?")

    # Build one shared table — shallow copy, strips locks once
    tbl = {k: dict(v) if isinstance(v, dict) else v for k, v in sd.items()}
    _strip_locks(tbl)

    # Ensure every keyframe in range is a dict so we can write handles
    for i in range(i0, i1 + 1):
        k = all_times[i]
        if not isinstance(tbl[k], dict):
            tbl[k] = {1: tbl[k]}

    any_ok = False

    # Apply handles to each consecutive segment within [i0, i1]
    for seg_i in range(i0, i1):
        ka, kb = all_times[seg_i], all_times[seg_i + 1]
        ea, eb = sd[ka], sd[kb]
        ta, tb = float(ka), float(kb)
        dt = tb - ta
        if abs(dt) < 1e-12:
            log.warning(f"[MFlow] apply_bezier: zero-duration seg [{seg_i+1}→{seg_i+2}] skipped")
            continue

        # ── Point2D ──
        p0, p1 = _path_point(ea), _path_point(eb)
        if p0 is not None and p1 is not None:
            dx, dy = p1[0]-p0[0], p1[1]-p0[1]
            dv = dx if abs(dx) >= abs(dy) else dy
            tbl[ka]["RH"] = {1: h1[0]*dt,         2: h1[1]*dv}
            tbl[kb]["LH"] = {1: (h2[0]-1.0)*dt,   2: (h2[1]-1.0)*dv}
            log.warning(f"[MFlow] apply_bezier: Point2D seg [{seg_i+1}→{seg_i+2}] t={ta:.1f}→{tb:.1f}"
                  f"  RH_off={h1[0]*dt:.2f}  LH_off={(h2[0]-1.0)*dt:.2f}")
            any_ok = True
            continue

        # ── Scalar ──
        v0 = _kf_scalar(ea); v1 = _kf_scalar(eb)
        if v0 is None or v1 is None:
            log.warning(f"[MFlow] apply_bezier: cannot read scalar on '{name}' seg [{seg_i+1}→{seg_i+2}]")
            continue
        dv = v1 - v0
        rh_off = h1[0]*dt
        lh_off = (h2[0]-1.0)*dt
        tbl[ka]["RH"] = {1: rh_off, 2: h1[1]*dv}
        tbl[kb]["LH"] = {1: lh_off, 2: (h2[1]-1.0)*dv}
        log.warning(f"[MFlow] apply_bezier: scalar seg [{seg_i+1}→{seg_i+2}] '{name}'"
              f"  t={ta:.1f}→{tb:.1f}  v={v0:.3f}→{v1:.3f}"
              f"  RH_off={rh_off:.2f}  LH_off={lh_off:.2f}")
        any_ok = True

    if not any_ok:
        return False

    ok = _call_set_kf(spline, tbl)
    log.warning(f"[MFlow] apply_bezier: SetKeyFrames {'OK' if ok else 'FAILED'} on '{name}'"
          f" range=[{i0+1}→{i1+1}] segs={i1-i0}")
    return ok




def apply_baked(spline, frames, kf_from: int = 1, kf_to: int = 0,
                t_start: float = None, t_end: float = None) -> bool:
    """
    Apply baked frames within the time range [t_start, t_end].
    If t_start/t_end are provided (from _bake_range), they are used directly.
    Otherwise falls back to kf_from/kf_to index-based range.
    Always clears previously-baked keyframes in the range first.
    Anchor keyframes are preserved so Ctrl+Z restores them correctly.
    """
    if not frames:
        return False
    try:
        get_kf = getattr(spline, "GetKeyFrames", None)
        set_kf = getattr(spline, "SetKeyFrames", None)
        if not callable(get_kf) or not callable(set_kf):
            return False

        sd = get_kf()
        if not isinstance(sd, dict) or len(sd) < 2:
            kf = {int(round(f)): v for f, v in frames}
            for args in ((kf, True), (kf,)):
                try: set_kf(*args); return True
                except Exception: continue
            return False

        all_times = _numeric_times(sd)
        if len(all_times) < 2:
            # No numeric keyframes — write directly
            kf = {int(round(f)): v for f, v in frames}
            for args in ((kf, True), (kf,)):
                try: set_kf(*args); return True
                except Exception: continue
            return False
        n = len(all_times)

        # Resolve t_start / t_end
        if t_start is None or t_end is None:
            i0 = max(0, kf_from - 1)
            i1 = (n - 1) if kf_to == 0 else min(n - 1, kf_to - 1)
            if i1 <= i0: i1 = min(i0 + 1, n - 1)
            t_start = float(all_times[i0])
            t_end   = float(all_times[i1])

        v_start = _anchor_value(spline, t_start, sd.get(
            min(all_times, key=lambda k: abs(float(k)-t_start))))
        v_end   = _anchor_value(spline, t_end, sd.get(
            min(all_times, key=lambda k: abs(float(k)-t_end))))

        # Keep kfs outside range, replace everything inside with baked frames
        kf = {}
        for k, v in sd.items():
            ft = float(k)
            if ft < t_start or ft > t_end:
                kf[k] = v

        for f, v in frames:
            ft = float(f)
            if t_start <= ft <= t_end:
                kf[int(round(ft))] = v

        # Force anchors (plain floats — Fusion's SetKeyFrames crashes with nested dicts)
        t_start_int = int(round(t_start))
        t_end_int   = int(round(t_end))
        kf[t_start_int] = v_start
        kf[t_end_int]   = v_end

        for args in ((kf, True), (kf, False), (kf,)):
            try:
                set_kf(*args)
                # "Magnetism": flatten the boundary tangents so the baked curve
                # enters/exits horizontally — same effect spring/elastic get
                # naturally from their shape. Uses the proven SetData path
                # (same as apply_overframe) — NOT a nested dict inside
                # SetKeyFrames, which crashes Fusion's Python bridge.
                handle_dt = max(1.0, (t_end_int - t_start_int) * 0.15)
                try:
                    _write_handle(spline, t_start_int, "RH",
                                  t_start_int + handle_dt, v_start)
                except Exception:
                    pass
                try:
                    _write_handle(spline, t_end_int, "LH",
                                  t_end_int - handle_dt, v_end)
                except Exception:
                    pass
                return True
            except Exception:
                continue
        return False

    except Exception as e:
        log.warning(f"[MFlow] apply_baked exception: {e}")
        return False


def _anchor_value(spline, t, kf_entry):
    """
    Read the true value at anchor time t.
    Tries GetInput first (most reliable), falls back to kf_entry parsing.
    """
    try:
        v = spline.GetInput(t)
        if v is not None:
            return float(v)
    except Exception:
        pass
    return _kf_scalar(kf_entry) or 0.0


def apply_steps(spline, n_steps, position="end") -> bool:
    """Create step-function keyframes by placing near-adjacent keyframes."""
    r = _get_kf_range(spline)
    if not r:
        return False
    t0, v0, t1, v1 = r
    dt = (t1-t0)/n_steps
    dv = (v1-v0)/n_steps
    new_kf = {}
    for i in range(n_steps+1):
        t = t0 + i*dt
        v = v0 + i*dv
        new_kf[t] = v
        if i < n_steps and position == "start":
            new_kf[t + 1e-4] = v0 + (i+1)*dv
    try:
        spline.SetKeyFrames(new_kf)
        return True
    except Exception:
        return False


def apply_overframe(spline, h1: list, h2: list, of_points: list, kf_from: int = 1, kf_to: int = 0) -> bool:
    """Insert overframe keyframes and apply per-segment bezier handles."""

    # ── 1. Read existing keyframe structure ───────────────────────────────
    get_kf_fn = getattr(spline, "GetKeyFrames", None)
    if not callable(get_kf_fn):
        log.warning("[MFlow] apply_overframe: no GetKeyFrames on object")
        return False
    try:
        sd = get_kf_fn()
    except Exception as e:
        log.warning(f"[MFlow] apply_overframe: GetKeyFrames failed: {e}")
        return False
    if not isinstance(sd, dict) or len(sd) < 2:
        log.warning(f"[MFlow] apply_overframe: need ≥2 keyframes, got {len(sd) if isinstance(sd, dict) else 0}")
        return False

    all_times = _numeric_times(sd)
    n = len(all_times)
    if n < 2:
        log.warning(f"[MFlow] apply_overframe: < 2 numeric keyframes")
        return False
    i0 = max(0, kf_from - 1)
    i1 = (n - 1) if kf_to == 0 else min(n - 1, kf_to - 1)
    if i1 <= i0: i1 = min(i0 + 1, n - 1)
    k0, k1 = all_times[i0], all_times[i1]
    t0, t1 = float(k0), float(k1)
    dt = t1 - t0
    if abs(dt) < 1e-12:
        log.warning("[MFlow] apply_overframe: zero-duration range")
        return False

    e0, e1 = sd[k0], sd[k1]
    v0 = _kf_scalar(e0)
    v1 = _kf_scalar(e1)
    if v0 is None or v1 is None:
        log.warning("[MFlow] apply_overframe: cannot read scalar keyframe values")
        return False
    dv   = v1 - v0
    name = getattr(spline, "Name", "?")
    log.warning(f"[MFlow] apply_overframe: '{name}'  t={t0:.0f}→{t1:.0f}  "
          f"v={v0:.4f}→{v1:.4f}  okf_pts={len(of_points)}")

    def dn_t(tn): return t0 + tn * dt
    def dn_v(vn): return v0 + vn * dv

    # ── 2. Build keyframe table: copy existing + add OKF intermediate pts ─
    # Shallow-copy to avoid mutating Fusion's internal dict
    tbl = {k: (dict(v) if isinstance(v, dict) else v) for k, v in sd.items()}
    _strip_locks(tbl)   # remove LockedY/Locked flags that block handle writes

    end0, end1 = int(round(t0)), int(round(t1))
    skipped = 0
    for p in of_points:
        ft   = dn_t(p.t)
        fv   = dn_v(p.v)
        ft_k = int(round(ft))
        # Skip points that would collapse onto an existing endpoint
        if ft_k == end0 or ft_k == end1:
            log.warning(f"[MFlow] apply_overframe: skip OKF point t={p.t:.3f} "
                  f"— frame {ft_k} collides with endpoint")
            skipped += 1
            continue
        tbl[ft_k] = {1: float(fv)}   # {1: value} is the Fusion scalar kf format

    ok = _call_set_kf(spline, tbl)
    log.warning(f"[MFlow] apply_overframe: SetKeyFrames {'OK' if ok else 'FAILED'}"
          f"  skipped={skipped}/{len(of_points)}")
    if not ok:
        return False

    # ── 3. Apply per-segment bezier handles ───────────────────────────────
    sorted_pts = sorted(of_points, key=lambda x: x.t)
    seg = (
        [(0.0, 0.0, None, h1)]
        + [(p.t, p.v, p.lh, p.rh) for p in sorted_pts]
        + [(1.0, 1.0, h2,  None)]
    )
    handles_ok = 0
    handles_expected = 0
    for i in range(len(seg) - 1):
        pt0, pv0, _, rh  = seg[i]
        pt1, pv1, lh, _  = seg[i + 1]
        seg_dt = (pt1 - pt0) * dt
        seg_dv = (pv1 - pv0) * dv
        ft0s = dn_t(pt0);  fv0s = dn_v(pv0)
        ft1s = dn_t(pt1);  fv1s = dn_v(pv1)
        if rh:
            handles_expected += 1
            wrote = _write_handle(spline, ft0s, "RH",
                                  ft0s + rh[0] * seg_dt,
                                  fv0s + rh[1] * seg_dv)
            if wrote:
                handles_ok += 1
            else:
                log.warning(f"[MFlow] apply_overframe: RH handle FAILED at frame {ft0s:.1f}")
        if lh:
            handles_expected += 1
            wrote = _write_handle(spline, ft1s, "LH",
                                  ft1s + lh[0] * seg_dt,
                                  fv1s + lh[1] * seg_dv)
            if wrote:
                handles_ok += 1
            else:
                log.warning(f"[MFlow] apply_overframe: LH handle FAILED at frame {ft1s:.1f}")

    log.warning(f"[MFlow] apply_overframe: handles {handles_ok}/{handles_expected}  → DONE")
    return True
