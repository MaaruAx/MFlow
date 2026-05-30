"""
Bezier evaluation, baking (spring/elastic/bounce/steps), and Fusion spline application.
Handle writing uses every known format for Resolve compatibility.
"""
import math
from dataclasses import dataclass, field


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
    t_settle = 4.6 / (zeta * omega_n)
    # t0/t1 are FRAME NUMBERS — step one integer frame at a time
    n = max(1, int(round(t1 - t0)))
    result = []
    for i in range(n + 1):
        tn     = i / n
        val    = eval_spring_osc(tn * t_settle, zeta, omega_n)
        result.append((int(round(t0)) + i, v0 + val * (v1 - v0)))
    return result


    t: float = 0.5
    v: float = 0.5
    lh: list = field(default_factory=lambda: [-0.1, 0.0])
    rh: list = field(default_factory=lambda: [ 0.1, 0.0])
    tangent: str = "smooth"

    def apply_smooth(self):
        self.lh = [-self.rh[0], -self.rh[1]]

    def apply_sym(self):
        mag = math.hypot(*self.rh)
        ang = math.atan2(self.rh[1], self.rh[0])
        self.lh = [-mag*math.cos(ang), -mag*math.sin(ang)]



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


# ── Resolve spline writing ────────────────────────────────────────────────────

def _get_kf_range(spline):
    """Return (t0, v0, t1, v1) or None if not enough keyframes."""
    try:
        kf = spline.GetKeyFrames()
        if not kf or len(kf) < 2:
            return None
        times = sorted(kf.keys())
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


def _call_set_kf(obj, tbl) -> bool:
    fn = getattr(obj, "SetKeyFrames", None)
    if not callable(fn): return False
    for args in ((tbl, True), (tbl,)):
        try: fn(*args); return True
        except Exception: continue
    return False


def apply_bezier(spline, h1: list, h2: list) -> bool:
    """
    Apply cubic-bezier handles to a BezierSpline or Point2D input.
    Handles both scalar inputs and compound (Point2D) inputs like Center.
    """
    get_kf = getattr(spline, "GetKeyFrames", None)
    if not callable(get_kf):
        print("[MFlow] apply_bezier: no GetKeyFrames on object")
        return False
    try:
        sd = get_kf()
    except Exception as e:
        print(f"[MFlow] apply_bezier: GetKeyFrames failed: {e}")
        return False

    if not isinstance(sd, dict) or len(sd) < 2:
        print(f"[MFlow] apply_bezier: < 2 keyframes")
        return False

    all_times = sorted(sd.keys(), key=lambda x: float(x))
    k0, k1 = all_times[0], all_times[-1]
    e0, e1 = sd[k0], sd[k1]
    dt = float(k1) - float(k0)
    if abs(dt) < 1e-12: return False

    # Shallow copy to avoid mutating Fusion's internal dict
    tbl = {k: dict(v) if isinstance(v, dict) else v for k, v in sd.items()}
    if not isinstance(tbl[k0], dict): tbl[k0] = {1: tbl[k0]}
    if not isinstance(tbl[k1], dict): tbl[k1] = {1: tbl[k1]}

    name = getattr(spline, "Name", "?")

    # ── Point2D path input (Center, Pivot, etc.) ──────────────────────────
    p0, p1 = _path_point(e0), _path_point(e1)
    if p0 is not None and p1 is not None:
        dx, dy = p1[0]-p0[0], p1[1]-p0[1]
        # Use the dominant axis for value delta
        dv = dx if abs(dx) >= abs(dy) else dy
        tbl[k0]["RH"] = {1: h1[0]*dt,       2: h1[1]*dv}
        tbl[k1]["LH"] = {1: (h2[0]-1.0)*dt, 2: (h2[1]-1.0)*dv}
        ok = _call_set_kf(spline, tbl)
        print(f"[MFlow] apply_bezier: Point2D {'OK' if ok else 'FAILED'} on '{name}'")
        return ok

    # ── Scalar input ──────────────────────────────────────────────────────
    v0 = _kf_scalar(e0); v1 = _kf_scalar(e1)
    if v0 is None or v1 is None:
        print(f"[MFlow] apply_bezier: cannot read scalar values")
        return False
    dv = v1 - v0
    tbl[k0]["RH"] = {1: h1[0]*dt,       2: h1[1]*dv}
    tbl[k1]["LH"] = {1: (h2[0]-1.0)*dt, 2: (h2[1]-1.0)*dv}
    ok = _call_set_kf(spline, tbl)
    print(f"[MFlow] apply_bezier: scalar {'OK' if ok else 'FAILED'} on '{name}' t={float(k0):.1f}→{float(k1):.1f}")
    return ok




def apply_baked(spline, frames) -> bool:
    if not frames:
        return False
    try:
        kf = {int(round(f)): v for f, v in frames}
        set_kf = getattr(spline, "SetKeyFrames", None)
        if not callable(set_kf):
            return False
        for args in ((kf, True), (kf,)):
            try:
                set_kf(*args)
                return True
            except Exception:
                continue
        return False
    except Exception:
        return False


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


def apply_overframe(spline, h1, h2, of_points) -> bool:
    """Insert overframe keyframes and apply per-segment handles."""
    r = _get_kf_range(spline)
    if not r:
        return False
    t0, v0, t1, v1 = r
    dt, dv = t1-t0, v1-v0

    def dn_t(tn): return t0 + tn*dt
    def dn_v(vn): return v0 + vn*dv

    new_kf = {t0: v0, t1: v1}
    for p in of_points:
        new_kf[dn_t(p.t)] = dn_v(p.v)
    try:
        spline.SetKeyFrames(new_kf)
    except Exception:
        return False

    # Build ordered segment list: [start, ...of_points..., end]
    seg = (
        [(0.0, 0.0, None, h1)]
        + [(p.t, p.v, p.lh, p.rh) for p in sorted(of_points, key=lambda x: x.t)]
        + [(1.0, 1.0, h2,  None)]
    )
    for i in range(len(seg)-1):
        pt0, pv0, _, rh = seg[i]
        pt1, pv1, lh, _ = seg[i+1]
        seg_dt = (pt1-pt0)*dt
        seg_dv = (pv1-pv0)*dv
        ft0 = dn_t(pt0); fv0 = dn_v(pv0)
        ft1 = dn_t(pt1); fv1 = dn_v(pv1)
        if rh:
            _write_handle(spline, ft0, "RH", ft0 + rh[0]*seg_dt, fv0 + rh[1]*seg_dv)
        if lh:
            _write_handle(spline, ft1, "LH", ft1 + lh[0]*seg_dt, fv1 + lh[1]*seg_dv)
    return True
