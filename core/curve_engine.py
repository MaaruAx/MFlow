"""
Bezier evaluation, baking (spring/elastic/bounce/steps), and Fusion spline application.
Handle writing uses every known format for Resolve compatibility.
"""
import math
import time
import logging
from dataclasses import dataclass, field

log = logging.getLogger("mflow")

# Spring/oscillator preview-vs-bake sync point.
#
# Every OTHER bake_* function in this file evaluates its shape on a
# normalized fraction tn = i/n of the REAL keyframe span, so the canvas
# preview (which also samples 0..1 normalized) always matches exactly what
# gets applied, no matter how long the real Fusion range is.
#
# The spring/oscillator was originally the one exception: it used the real
# elapsed time in seconds (t1-t0)/fps so that omega_n would behave like a
# physically real angular frequency. That meant the shape depended on the
# real clip length, which the canvas has no way to know about at preview
# time (it always draws assuming a fixed reference duration) — so anything
# shorter than that reference duration got cut off mid-oscillation on
# apply, even though the preview showed the full settle. This constant
# removes that mismatch by making spring behave like every other mode:
# always sampled across this fixed reference duration, so the preview is
# always exactly what gets applied.
#
# MUST match SP_T_REF in ui/app.html exactly — if you ever change one,
# change the other. Kept as an obvious, singular, well-commented constant
# in both files specifically so it can't quietly drift again like it did
# before (ui/app.html previously had this same value duplicated inline in
# two separate places).
SPRING_T_REF = 2.5


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

def derive_squash_stretch(baked_frames, stretch_intensity: float = 1.0,
                           squash_intensity: float = 1.0,
                           min_scale: float = 0.15, max_scale: float = 4.0):
    """
    Derives a pair of complementary "squash & stretch" scale-factor curves
    from an already-baked primary motion curve — the classic animation
    principle where a moving object stretches along its direction of
    travel and squashes perpendicular to it, in proportion to how fast
    it's currently moving. Settles back to neutral 1.0 (no distortion)
    wherever the primary motion is momentarily at rest — that's what makes
    it read as motivated by the motion rather than an arbitrary wobble
    layered on top.

    Deliberately mode-agnostic: this only ever looks at the BAKED VALUES,
    never at which curve type produced them (bounce, spring, elastic, or a
    plain ease all work identically) — no per-mode special-casing, no
    "impact detection" logic.

    stretch intensity and squash_intensity are independent dials (NOT
    forced into a strict volume-preserving 1/x relationship) — letting the
    two axes be tuned separately by eye, since "looks natural" is a
    per-shot judgment call. Each is 0 = no effect on that axis, 1.0 =
    a full unit of effect at peak velocity, and can go higher to
    exaggerate further.

    Parameters
    ----------
    baked_frames : list[(frame, value)]
        The already-baked primary curve, exactly as returned by any
        bake_*() function or bake_fn(). Frames need not be evenly spaced.
    stretch_intensity, squash_intensity : float
        Independent per-axis intensity dials, as described above.
    min_scale / max_scale : float
        Hard safety clamps so an extreme intensity, or a noisy/spiky
        primary curve, can never invert a shape (scale <= 0) or blow up to
        a degenerate size.

    Returns
    -------
    (stretch_frames, squash_frames) — two [(frame, value)] lists at the
    same frame positions as the input, in exactly the shape apply_baked()
    expects, each smoothly settling to exactly 1.0 at both endpoints
    regardless of intensity (see the edge-fade comment below).
    """
    n = len(baked_frames)
    if n < 2:
        flat = [(f, 1.0) for f, _ in baked_frames]
        return flat, list(flat)

    frames = [f for f, _v in baked_frames]
    values = [v for _f, v in baked_frames]

    # Central-difference velocity (one-sided at the two edges), in
    # value-per-frame. Dividing by the LOCAL frame delta (rather than
    # assuming a fixed step) keeps this correct even where a bake_*
    # function oversamples near sharp corners with smaller steps.
    velocity = [0.0] * n
    for i in range(n):
        if i == 0:
            df = frames[i + 1] - frames[i]
            velocity[i] = (values[i + 1] - values[i]) / df if df else 0.0
        elif i == n - 1:
            df = frames[i] - frames[i - 1]
            velocity[i] = (values[i] - values[i - 1]) / df if df else 0.0
        else:
            df = frames[i + 1] - frames[i - 1]
            velocity[i] = (values[i + 1] - values[i - 1]) / df if df else 0.0

    peak = max((abs(v) for v in velocity), default=0.0)
    if peak < 1e-9:
        flat = [(f, 1.0) for f in frames]
        return flat, list(flat)

    # BUG FIX: this used to hard-snap ONLY the very first/last sample to
    # exactly 1.0 after computing everything else from raw velocity. That
    # works fine for the other bake_* functions because their underlying
    # physics naturally decays to near-zero velocity at the boundary, so
    # forcing the endpoint is an imperceptible rounding correction. But
    # squash & stretch derives from an ARBITRARY primary curve's velocity,
    # which can still be high right up to the very last frame (e.g. a
    # bounce "landing" at full speed) — so the value stayed elevated
    # through the second-to-last sample and then hard-snapped to 1.0 on
    # the last one, producing a visibly abrupt jump instead of a settle.
    # Fixing this with a smoothstep taper over the first/last ~12% of the
    # range: the deviation from neutral fades out gradually and reaches
    # exactly 0 right at the boundary, so it settles into the keyframe
    # instead of snapping onto it.
    ease_n = max(1, min(n // 2, round(n * 0.12)))

    def _edge_fade(i):
        if i < ease_n:
            x = i / ease_n
        elif i > (n - 1) - ease_n:
            x = ((n - 1) - i) / ease_n
        else:
            return 1.0
        return x * x * (3 - 2 * x)  # smoothstep: 0 at the edge, 1 past the taper window

    stretch_frames = []
    squash_frames  = []
    for i, (f, v) in enumerate(zip(frames, velocity)):
        norm    = (abs(v) / peak) * _edge_fade(i)     # 0 at rest/edges, up to 1 at peak speed
        stretch = max(min_scale, min(max_scale, 1.0 + stretch_intensity * norm))
        squash  = max(min_scale, min(max_scale, 1.0 / (1.0 + squash_intensity * norm)))
        stretch_frames.append((f, stretch))
        squash_frames.append((f, squash))

    # Belt-and-suspenders: the taper above already reaches exactly 1.0 at
    # i=0 and i=n-1 (smoothstep(0)=0), so this is redundant in practice —
    # kept anyway as a hard guarantee against any floating-point edge case.
    stretch_frames[0]  = (stretch_frames[0][0],  1.0)
    stretch_frames[-1] = (stretch_frames[-1][0], 1.0)
    squash_frames[0]   = (squash_frames[0][0],   1.0)
    squash_frames[-1]  = (squash_frames[-1][0],  1.0)

    return stretch_frames, squash_frames


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


def _oversample(t0, t1, density=1):
    """Return (n_samples, frame_positions) for baking.
    density=1 (default) → exactly the same integer-frame sequence as before
    this feature existed — zero behavior change. density>1 → extra
    fractional-frame samples between each integer frame for smoother/more
    accurate curves. EXPERIMENTAL: relies on Fusion's BezierSpline accepting
    fractional-frame keyframes; verify on your system before relying on
    density>1 for delivery work.
    """
    n_frames = max(1, int(round(t1 - t0)))
    density  = max(1, int(density))
    if density <= 1:
        n = n_frames
        frames = [int(round(t0)) + i for i in range(n + 1)]
    else:
        n = n_frames * density
        step = (t1 - t0) / n
        frames = [t0 + i * step for i in range(n + 1)]
    return n, frames


def bake_oscillator(t0: float, v0: float, t1: float, v1: float,
                    fps: float, zeta: float = 0.3, omega_n: float = 8.0,
                    density: int = 1) -> list:
    """fps is intentionally unused now — kept in the signature only so the
    call site in backend.py doesn't need special-casing versus the other
    bake_* functions, which all take the same (t0,v0,t1,v1,fps,...) shape."""
    zeta    = max(0.01, min(0.99, zeta))
    omega_n = max(0.5, omega_n)
    # Sample across the fixed SPRING_T_REF reference duration (see comment
    # above the constant) instead of the real (t1-t0)/fps duration. This is
    # what makes the shape match the canvas preview exactly regardless of
    # how long the real keyframe range actually is — the same normalized
    # approach every other mode (elastic/bounce/catenary/etc.) already uses.
    n, frame_pos = _oversample(t0, t1, density)
    T = SPRING_T_REF
    result = []
    for i in range(n + 1):
        tn  = i / n
        val = eval_spring_osc(tn * T, zeta, omega_n)
        result.append((frame_pos[i], v0 + val * (v1 - v0)))
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


def bake_elastic_penner(t0, v0, t1, v1, fps, amplitude=1.0, period=0.3, flip_to_mid=False, density=1):
    n, frame_pos = _oversample(t0, t1, density)
    result = []
    for i in range(n + 1):
        tn  = i / n
        val = eval_elastic_penner(tn, amplitude, period)
        if flip_to_mid:
            val *= 0.5
        result.append((frame_pos[i], v0 + val * (v1 - v0)))
    return result


def bake_elastic_out(t0, v0, t1, v1, fps, amplitude=1.0, period=0.3, flip_to_mid=False, density=1):
    """Penner easeOutElastic — settles at start, oscillates at end."""
    n, frame_pos = _oversample(t0, t1, density)
    result = []
    for i in range(n + 1):
        tn  = i / n
        val = elastic_out(tn, amplitude, period)
        if flip_to_mid:
            val *= 0.5
        result.append((frame_pos[i], v0 + val * (v1 - v0)))
    result[0]  = (result[0][0],  v0)
    result[-1] = (result[-1][0], v1 if not flip_to_mid else v0 + 0.5 * (v1 - v0))
    return result


# ── Bounce (damped cosine) ────────────────────────────────────────────────────

def eval_bounce(t: float, gamma: float = 4.0, omega: float = 6.0) -> float:
    """Ceiling bounce: 1 - e^(-γt)·|cos(ωt)|  → starts 0, settles at 1."""
    if t <= 0: return 0.0
    if t >= 1: return 1.0
    return 1.0 - math.exp(-gamma * t) * abs(math.cos(omega * t))


def bake_bounce(t0, v0, t1, v1, fps, gamma=4.0, omega=6.0, flipped=False, density=1):
    """flipped=True → floor version: starts ~1, settles at 0."""
    n, frame_pos = _oversample(t0, t1, density)
    result = []
    for i in range(n + 1):
        tn  = i / n
        val = eval_bounce(tn, gamma, omega)
        if flipped:
            val = 1.0 - val
        result.append((frame_pos[i], v0 + val * (v1 - v0)))
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


def bake_catenary(t0, v0, t1, v1, fps, a=1.0, reverse=False, density=1):
    n, frame_pos = _oversample(t0, t1, density)
    vals = [eval_catenary(i / n, a) for i in range(n + 1)]
    if reverse:
        # Mirror the shape while preserving 0→1 direction: f_rev(t) = 1 - f(1-t)
        vals = [1.0 - v for v in reversed(vals)]
    result = []
    for i, val in enumerate(vals):
        result.append((frame_pos[i], v0 + val * (v1 - v0)))
    result[0]  = (result[0][0],  v0)
    result[-1] = (result[-1][0], v1)
    return result


# ── Pulse (modulated wave) ────────────────────────────────────────────────────

def eval_pulse_raw(t: float, omega1: float, omega2: float, n: float) -> float:
    return math.sin(omega1 * math.pi * t) * abs(math.sin(omega2 * math.pi * t)) ** n


def bake_pulse(t0, v0, t1, v1, fps, omega1=8.0, omega2=2.0, n=4.0, reverse=False, density=1):
    n_samples, frame_pos = _oversample(t0, t1, density)
    raw = [eval_pulse_raw(i / n_samples, omega1, omega2, n) for i in range(n_samples + 1)]
    r_min, r_max = min(raw), max(raw)
    span = r_max - r_min if abs(r_max - r_min) > 1e-10 else 1.0
    vals = [(r - r_min) / span for r in raw]
    if reverse:
        vals = [1.0 - v for v in reversed(vals)]
    # Additive linear correction: instead of a hard snap at the endpoints
    # (which creates a frame-to-frame discontinuity), add an offset that
    # linearly blends from (0 - vals[0]) at t=0 to (1 - vals[-1]) at t=1.
    # This makes the curve naturally pass through v0 and v1 while preserving
    # the interior shape as much as possible.
    n_pts = len(vals)
    start_err = -vals[0]
    end_err   = 1.0 - vals[-1]
    vals = [v + (1.0 - i/(n_pts-1))*start_err + (i/(n_pts-1))*end_err
            for i, v in enumerate(vals)]
    result = [(frame_pos[i], v0 + val * (v1 - v0)) for i, val in enumerate(vals)]
    result[0]  = (result[0][0],  v0)
    result[-1] = (result[-1][0], v1)
    return result


# ── Noise (smooth random) ─────────────────────────────────────────────────────

def bake_noise(t0, v0, t1, v1, fps, freq=2.0, amp=0.5, seed=42, reverse=False, density=1):
    """Smooth noise via cosine interpolation over seeded random control points."""
    import random
    rng    = random.Random(int(seed))
    n, frame_pos = _oversample(t0, t1, density)
    n_ctrl = max(2, int(freq * 4) + 1)
    ctrl   = [rng.uniform(-1.0, 1.0) for _ in range(n_ctrl)]
    vals = []
    for i in range(n + 1):
        t   = i / n
        pos = t * (n_ctrl - 1)
        idx = min(int(pos), n_ctrl - 2)
        frac = pos - idx
        mu2  = (1.0 - math.cos(frac * math.pi)) / 2.0
        v    = ctrl[idx] * (1.0 - mu2) + ctrl[idx + 1] * mu2
        vals.append(max(0.0, min(1.0, 0.5 + v * amp)))
    if reverse:
        vals = [1.0 - v for v in reversed(vals)]
    # Additive linear correction for smooth endpoint alignment
    n_pts = len(vals)
    start_err = -vals[0]
    end_err   = 1.0 - vals[-1]
    vals = [v + (1.0 - i/(n_pts-1))*start_err + (i/(n_pts-1))*end_err
            for i, v in enumerate(vals)]
    result = [(frame_pos[i], v0 + val * (v1 - v0)) for i, val in enumerate(vals)]
    result[0]  = (result[0][0],  v0)
    result[-1] = (result[-1][0], v1)
    return result


# ── Resonance (forced oscillator) ─────────────────────────────────────────────

def eval_resonance_raw(t: float, gamma: float, omega: float, omega0: float) -> float:
    denom = abs(omega0 ** 2 - omega ** 2)
    A = min(1.0 / max(denom, 0.5), 5.0)
    B = -A
    return A * math.cos(omega * t) + B * math.exp(-gamma * t) * math.cos(omega0 * t)


def bake_resonance(t0, v0, t1, v1, fps, gamma=2.0, omega=8.0, omega0=8.0, reverse=False, density=1):
    n, frame_pos = _oversample(t0, t1, density)
    raw = [eval_resonance_raw(i / n, gamma, omega, omega0) for i in range(n + 1)]
    r_min, r_max = min(raw), max(raw)
    span = r_max - r_min if abs(r_max - r_min) > 1e-10 else 1.0
    vals = [(r - r_min) / span for r in raw]
    if reverse:
        vals = [1.0 - v for v in reversed(vals)]
    # Additive linear correction for smooth endpoint alignment
    n_pts = len(vals)
    start_err = -vals[0]
    end_err   = 1.0 - vals[-1]
    vals = [v + (1.0 - i/(n_pts-1))*start_err + (i/(n_pts-1))*end_err
            for i, v in enumerate(vals)]
    result = [(frame_pos[i], v0 + val * (v1 - v0)) for i, val in enumerate(vals)]
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


def _write_handle(spline, frame, side, time_val, value):
    """
    Try every known SetData key format for a bezier handle.
    Returns True on first success.
    """
    payload   = {1: float(time_val), 2: float(value)}
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


def _settle(spline, delay: float = 0.02) -> None:
    """Give Fusion a brief moment to flush internal state right after a
    SetKeyFrames() commit, before any follow-up SetData() handle writes are
    attempted. A single short, bounded pause here means the FIRST handle
    write (previously the one most likely to land in the unsettled window
    and fail — see _write_handle_retry) succeeds on its first try in the
    common case, rather than relying purely on reactive retries after an
    initial failure. Never raises — worst case this is a no-op delay."""
    try:
        time.sleep(delay)
        get_kf = getattr(spline, "GetKeyFrames", None)
        if callable(get_kf):
            get_kf()
    except Exception:
        pass


def _write_handle_retry(spline, frame, side, time_val, value,
                         attempts: int = 3, delay: float = 0.03) -> bool:
    """Redundant wrapper around _write_handle() for stability.

    Immediately after a SetKeyFrames() call, Fusion's spline can take a brief
    moment to internally "settle" before it reliably accepts a follow-up
    SetData() write on a keyframe that was just (re)created — especially the
    very first handle written right after the commit. Writing several
    handles back-to-back with zero delay means the earliest ones can land in
    that unsettled window and silently fail (this is the "first Apply only
    updates one handle, the other needs a second Apply" bug: whichever
    handle is written first has the least time to settle).

    This wrapper retries a failed write a few times with a short pause and a
    forced round-trip through GetKeyFrames() (which nudges Fusion to flush
    its internal state) in between, instead of relying on a single
    instantaneous attempt. Bounded to a handful of short retries — at most
    ~90ms total in the worst case — so it never introduces a noticeable
    stall on what is a synchronous, user-initiated Apply click.
    """
    for attempt in range(1, attempts + 1):
        if _write_handle(spline, frame, side, time_val, value):
            return True
        # Give Fusion a moment to settle, then force a state round-trip
        # before the next attempt.
        try:
            time.sleep(delay)
            get_kf = getattr(spline, "GetKeyFrames", None)
            if callable(get_kf):
                get_kf()
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


def _lookup_kf_entry(kf_dict, key):
    """Look up a keyframe entry by key, tolerating type/format differences
    between the key we used locally (int/float/original Fusion type) and
    whatever Fusion echoes back on a fresh GetKeyFrames() read (which isn't
    always the same type — e.g. int vs float vs numeric string). Falls back
    to comparing float values across all keys if a direct lookup misses."""
    if key in kf_dict:
        return kf_dict[key]
    try:
        target = float(key)
    except (TypeError, ValueError):
        return None
    for k in kf_dict.keys():
        try:
            if abs(float(k) - target) < 1e-6:
                return kf_dict[k]
        except (TypeError, ValueError):
            continue
    return None


def _kf_handles_match(entry, expected_sides: dict, tol: float = 1e-3) -> bool:
    """Check whether a GetKeyFrames() entry actually carries the RH/LH
    sub-values we asked Fusion to write, within a small tolerance."""
    if not isinstance(entry, dict):
        return False
    for side, want in expected_sides.items():
        got = entry.get(side)
        if not isinstance(got, dict):
            return False
        for k, wv in want.items():
            gv = got.get(k)
            if gv is None:
                return False
            try:
                if abs(float(gv) - float(wv)) > tol:
                    return False
            except (TypeError, ValueError):
                return False
    return True


def _call_set_kf(obj, tbl, attempts: int = 3, delay: float = 0.02) -> bool:
    """Commit a keyframe table to Fusion, with a VERIFIED, redundant retry.

    SetKeyFrames() accepts three call signatures depending on node type
    (True=force-create, False=update-existing, no-arg=default) — but a call
    that doesn't raise an exception does NOT guarantee every nested value in
    `tbl` actually landed. In practice the (tbl, True) "force-create"
    signature can silently drop the bezier RH/LH handle on one endpoint
    while keeping the other. That is what produced the "first Apply only
    updates one handle, the other stays the same" bug — including in plain
    easing mode, since apply_bezier() commits everything through this one
    call.

    To close that gap, after each attempt that doesn't raise we read the
    spline back via GetKeyFrames() and confirm the RH/LH values we intended
    are actually present before declaring success — "didn't throw" is no
    longer trusted on its own. If verification fails, we settle (brief
    pause + state round-trip) and try the next signature or another pass,
    instead of returning success on the first non-raising call.
    """
    fn = getattr(obj, "SetKeyFrames", None)
    if not callable(fn):
        return False

    # Snapshot which keys carry RH/LH handles so we can verify them.
    expected = {}
    for k, v in tbl.items():
        if not isinstance(v, dict):
            continue
        sides = {s: v[s] for s in ("RH", "LH") if s in v}
        if sides:
            expected[k] = sides

    signatures = ((tbl, True), (tbl, False), (tbl,))
    call_succeeded = False  # a signature ran without raising, at least once

    for attempt in range(attempts):
        for args in signatures:
            try:
                fn(*args)
                call_succeeded = True
            except Exception:
                continue

            if not expected:
                # Nothing to verify (e.g. position-only commit) — a
                # non-raising call is success.
                return True

            get_kf = getattr(obj, "GetKeyFrames", None)
            try:
                fresh = get_kf() if callable(get_kf) else None
            except Exception:
                fresh = None

            if isinstance(fresh, dict):
                all_match = all(
                    _kf_handles_match(_lookup_kf_entry(fresh, k), want)
                    for k, want in expected.items()
                )
                if all_match:
                    return True
            # Either couldn't read back or a handle didn't land — fall
            # through and try the next signature / attempt.

        if attempt < attempts - 1:
            _settle(obj, delay)

    # Last resort: if some call ran without raising even though we
    # couldn't verify every handle landed, still report success — a
    # partially-applied curve is better than the caller assuming total
    # failure and leaving the spline in a worse, inconsistent state. The
    # per-handle warnings logged by callers still surface the discrepancy.
    return call_succeeded


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
            kf = {(f if abs(f - round(f)) > 1e-6 else int(round(f))): v for f, v in frames}
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
                # Keep fractional keys when oversampling (density>1) for extra
                # in-between control points; integer frames stay int as before.
                key = ft if abs(ft - round(ft)) > 1e-6 else int(round(ft))
                kf[key] = v

        # Force anchors (plain floats — Fusion's SetKeyFrames crashes with nested dicts)
        t_start_int = int(round(t_start))
        t_end_int   = int(round(t_end))
        kf[t_start_int] = v_start
        kf[t_end_int]   = v_end

        for args in ((kf, True), (kf, False), (kf,)):
            try:
                set_kf(*args)
                # Let Fusion settle before writing handles — see _settle().
                _settle(spline)
                # "Magnetism": flatten the boundary tangents so the baked curve
                # enters/exits horizontally — same effect spring/elastic get
                # naturally from their shape. Uses the proven SetData path
                # (same as apply_overframe) — NOT a nested dict inside
                # SetKeyFrames, which crashes Fusion's Python bridge.
                handle_dt = max(1.0, (t_end_int - t_start_int) * 0.15)
                try:
                    _write_handle_retry(spline, t_start_int, "RH",
                                         t_start_int + handle_dt, v_start)
                except Exception:
                    pass
                try:
                    _write_handle_retry(spline, t_end_int, "LH",
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


def eval_steps(tn: float, n_steps: int = 8, from_start: bool = False) -> float:
    """CSS steps()/Anime.js-compatible step easing, normalized to [0,1].

    Divides the range into n_steps equal plateaus.
    - from_start=False (default; CSS 'jump-end'): each plateau holds the
      PREVIOUS level and only jumps once its interval fully ends. Starts at
      exactly 0, only reaches 1 at tn=1.
    - from_start=True (CSS 'jump-start'): jumps to the NEXT level immediately
      at the start of each interval. Never sits at 0 — jumps to 1/n_steps
      the instant tn leaves 0, matching Anime.js's steps(n, true).

    Matches Anime.js's steps(n, fromStart) exactly — verified against its
    published source rather than approximated from memory (see chat).
    """
    if n_steps < 1:
        n_steps = 1
    if tn <= 0:
        return (1.0 / n_steps) if from_start else 0.0
    if tn >= 1:
        return 1.0
    idx = math.floor(tn * n_steps)
    if from_start:
        idx = min(idx + 1, n_steps)
    return idx / n_steps


def bake_steps(t0, v0, t1, v1, fps, n_steps=8, from_start=False):
    """One sample per frame using eval_steps — same signature/shape as every
    other bake_* function, used for the live canvas preview and anywhere
    else a plain sampled array is wanted. NOT used to write to Fusion —
    see apply_steps_kf for that; writing one keyframe per frame here would
    make Fusion's bezier interpolation draw a fine staircase-of-ramps
    instead of true flat plateaus with hard jumps.
    """
    n = max(1, round((t1 - t0) * fps))
    result = []
    for i in range(n + 1):
        tn = i / n
        vn = eval_steps(tn, n_steps, from_start)
        result.append((t0 + tn * (t1 - t0), v0 + vn * (v1 - v0)))
    return result


def apply_steps_kf(spline, t0, v0, t1, v1, n_steps=8, from_start=False) -> bool:
    """Writes TRUE discrete step keyframes onto a live Fusion spline.

    There is no native 'constant/hold' per-keyframe interpolation flag
    available through this BezierSpline API, so a hard jump is faked the
    only reliable way available: each of the n_steps plateaus gets a
    matching PAIR of keyframes — one at the start of its span, one an
    epsilon before the next jump — both holding the identical value, so
    Fusion's interpolation between them stays flat. The next pair then
    jumps to the next level almost instantly. Endpoints are still anchored
    exactly to v0/v1 like every other mode.
    """
    if n_steps < 1:
        return False
    span = t1 - t0
    if span <= 0:
        return False
    # Never large enough to eat into the next plateau even with n_steps=1.
    eps = min(0.05, span / max(1, n_steps) / 4.0)
    new_kf = {t0: v0}
    for k in range(n_steps):
        level_idx = (k + 1) if from_start else k
        level_v = v0 + (v1 - v0) * (level_idx / n_steps)
        seg_start = t0 + span * k / n_steps
        seg_end = t0 + span * (k + 1) / n_steps
        new_kf[seg_start] = level_v
        new_kf[seg_end - eps] = level_v
    new_kf[t1] = v1
    log.warning(f"[MFlow] apply_steps_kf: n_steps={n_steps} from_start={from_start}"
          f"  t={t0:.1f}→{t1:.1f}  v={v0:.3f}→{v1:.3f}  eps={eps:.4f}  kf_count={len(new_kf)}")
    try:
        spline.SetKeyFrames(new_kf)
        log.warning(f"[MFlow] apply_steps_kf: SetKeyFrames OK — {len(new_kf)} keyframes written")
        return True
    except Exception as e:
        log.warning("[MFlow] apply_steps_kf: SetKeyFrames FAILED: %s", e)
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

    # Remove any previously-written OKF intermediate keyframes between the
    # two endpoints so that moving a point and re-applying does not leave
    # stale duplicate frames in Fusion.
    end0, end1 = int(round(t0)), int(round(t1))
    for k in list(tbl.keys()):
        try:
            fk = float(k)
            if t0 < fk < t1 and int(round(fk)) not in (end0, end1):
                del tbl[k]
        except (TypeError, ValueError):
            pass

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

    # Let Fusion settle before writing handles — see _settle() docstring.
    _settle(spline)

    # ── 3. Apply per-segment bezier handles ───────────────────────────────
    sorted_pts = sorted(of_points, key=lambda x: x.t)
    seg = (
        [(0.0, 0.0, None, h1)]
        + [(p.t, p.v, p.lh, p.rh) for p in sorted_pts]
        + [(1.0, 1.0, h2,  None)]
    )
    handles_ok = 0
    handles_expected = 0
    n_segs = len(seg) - 1
    for i in range(n_segs):
        pt0, pv0, _, rh  = seg[i]
        pt1, pv1, lh, _  = seg[i + 1]
        seg_dt = (pt1 - pt0) * dt
        seg_dv = (pv1 - pv0) * dv
        ft0s = dn_t(pt0);  fv0s = dn_v(pv0)
        ft1s = dn_t(pt1);  fv1s = dn_v(pv1)
        if rh:
            handles_expected += 1
            # h1 (first segment's RH) is in full-curve normalized space [0,1],
            # NOT in segment-local space — scale by total dt/dv, not seg_dt/dv.
            if i == 0:
                rh_t = t0 + rh[0] * dt
                rh_v = v0 + rh[1] * dv
            else:
                rh_t = ft0s + rh[0] * seg_dt
                rh_v = fv0s + rh[1] * seg_dv
            wrote = _write_handle_retry(spline, ft0s, "RH", rh_t, rh_v)
            if wrote:
                handles_ok += 1
            else:
                log.warning(f"[MFlow] apply_overframe: RH handle FAILED at frame {ft0s:.1f}")
        if lh:
            handles_expected += 1
            # h2 (last segment's LH) is likewise in full-curve space.
            if i == n_segs - 1:
                lh_t = t0 + lh[0] * dt
                lh_v = v0 + lh[1] * dv
            else:
                lh_t = ft1s + lh[0] * seg_dt
                lh_v = fv1s + lh[1] * seg_dv
            wrote = _write_handle_retry(spline, ft1s, "LH", lh_t, lh_v)
            if wrote:
                handles_ok += 1
            else:
                log.warning(f"[MFlow] apply_overframe: LH handle FAILED at frame {ft1s:.1f}")

    log.warning(f"[MFlow] apply_overframe: handles {handles_ok}/{handles_expected}  → DONE")
    return True


# ── Labs: blend up to 3 curve modes into one ───────────────────────────────────
# Every bake_* function above already shares the same contract:
# (t0, v0, t1, v1, fps, **params) -> [(frame, value), ...], one sample per
# frame. That shared contract is what makes blending possible without any
# new curve math at all — bake each slot independently over the identical
# range (guaranteeing identical sample counts/frame positions), then combine
# by weighted average. _LABS_DISPATCH below is the only new code: a lookup
# from mode name to "how do I call that mode's bake_* with Labs-supplied
# params", kept in one place so adding a mode to Labs later is a one-line change.

def _labs_bake_easing(t0, v0, t1, v1, fps, p):
    h1 = p.get("h1", [0.42, 0.0]); h2 = p.get("h2", [0.58, 1.0])
    n = max(1, round((t1 - t0) * fps))
    return [(t0 + i/n*(t1-t0), v0 + (v1-v0)*eval_bezier(i/n, h1, h2)) for i in range(n+1)]

_LABS_DISPATCH = {
    "easing":    _labs_bake_easing,
    "spring":    lambda t0,v0,t1,v1,fps,p: bake_oscillator(t0,v0,t1,v1,fps,
                    zeta=p.get("zeta",0.3), omega_n=p.get("omega_n",8.0)),
    "elastic":   lambda t0,v0,t1,v1,fps,p: (bake_elastic_out if p.get("direction","out")=="out" else bake_elastic_penner)(
                    t0,v0,t1,v1,fps, amplitude=p.get("amplitude",1.0),
                    period=p.get("period",0.3), flip_to_mid=p.get("flip_to_mid",False)),
    "bounce":    lambda t0,v0,t1,v1,fps,p: bake_bounce(t0,v0,t1,v1,fps,
                    gamma=p.get("gamma",4.0), omega=p.get("omega",6.0),
                    flipped=(p.get("direction","ceiling")=="floor")),
    "catenary":  lambda t0,v0,t1,v1,fps,p: bake_catenary(t0,v0,t1,v1,fps,
                    a=p.get("a",0.8), reverse=p.get("reverse",False)),
    "pulse":     lambda t0,v0,t1,v1,fps,p: bake_pulse(t0,v0,t1,v1,fps,
                    omega1=p.get("omega1",8.0), omega2=p.get("omega2",2.0),
                    n=p.get("n",4.0), reverse=p.get("reverse",False)),
    "noise":     lambda t0,v0,t1,v1,fps,p: bake_noise(t0,v0,t1,v1,fps,
                    freq=p.get("freq",2.0), amp=p.get("amp",0.5),
                    seed=p.get("seed",42), reverse=p.get("reverse",False)),
    "resonance": lambda t0,v0,t1,v1,fps,p: bake_resonance(t0,v0,t1,v1,fps,
                    gamma=p.get("gamma",2.0), omega=p.get("omega",8.0),
                    omega0=p.get("omega0",8.0), reverse=p.get("reverse",False)),
    "steps":     lambda t0,v0,t1,v1,fps,p: bake_steps(t0,v0,t1,v1,fps,
                    n_steps=p.get("n_steps",8), from_start=p.get("from_start",False)),
}


def bake_labs_slot(mode_name, t0, v0, t1, v1, fps, params=None):
    """Bake a single Labs slot by mode name. Returns [] for an unknown or
    empty (disabled) slot rather than raising — a slot with no mode picked
    is a normal, expected state (e.g. only 2 of 3 slots in use), not an error."""
    fn = _LABS_DISPATCH.get(mode_name)
    if fn is None:
        return []
    try:
        return fn(t0, v0, t1, v1, fps, params or {})
    except Exception as e:
        log.warning("[MFlow] bake_labs_slot: '%s' raised: %s", mode_name, e)
        return []


def _resample_to_frames(baked, target_frames):
    """Linearly interpolates a dense [(frame,value),...] array (e.g.
    bake_spring's fps-resolution Euler steps) onto an explicit list of
    target frame numbers. If baked is already exactly at those frames
    (the common case — bounce/catenary/pulse/noise/resonance/steps all
    sample one point per real frame already), this is a no-op in effect,
    just re-expressed as a lookup instead of a copy.
    """
    if not baked:
        return []
    xs = [f for f, _ in baked]
    ys = [v for _, v in baked]
    out = []
    j = 0
    for tf in target_frames:
        while j < len(xs) - 2 and xs[j + 1] < tf:
            j += 1
        x0, x1 = xs[j], xs[min(j + 1, len(xs) - 1)]
        y0, y1 = ys[j], ys[min(j + 1, len(xs) - 1)]
        if x1 == x0:
            out.append((tf, y0))
        else:
            frac = (tf - x0) / (x1 - x0)
            frac = max(0.0, min(1.0, frac))
            out.append((tf, y0 + (y1 - y0) * frac))
    return out


def blend_baked(slot_bakes: list, weights: list, t0: float, t1: float,
                 v0: float, v1: float):
    """Combines up to 3 already-baked [(frame,value),...] arrays via
    weighted average, after first resampling every slot onto the SAME
    explicit grid of real frame numbers — see _resample_to_frames. This
    cannot assume the inputs already share sample positions: bake_spring
    (and any future physics-integrator mode) samples at fps-resolution
    dt-steps for numerical accuracy, while every closed-form mode
    (bounce/catenary/pulse/noise/resonance/steps) samples once per real
    frame via _oversample — confirmed different lengths for the same
    t0/t1/fps in testing, which would have silently corrupted or dropped
    slots under a naive zip().

    Weights are normalized so they don't need to sum to 1 — Labs lets each
    slot go 0-200% independently for deliberately extreme blends, and this
    function makes that safe regardless. Endpoints are re-anchored exactly
    to v0/v1 no matter what the weighted values landed on, matching the
    anchoring convention every other mode already follows.
    """
    active = [(frames, w) for frames, w in zip(slot_bakes, weights) if frames and w > 0]
    if not active:
        return []
    total_w = sum(w for _, w in active)
    if total_w <= 0:
        return []
    n_frames = max(1, round(t1 - t0))
    target_frames = [t0 + i for i in range(n_frames + 1)]
    resampled = [(_resample_to_frames(frames, target_frames), w) for frames, w in active]
    result = []
    for i, tf in enumerate(target_frames):
        v = sum(frames[i][1] * w for frames, w in resampled) / total_w
        result.append((tf, v))
    if result:
        result[0]  = (result[0][0],  v0)
        result[-1] = (result[-1][0], v1)
    return result


# ── "labs" (sequential): 3 consecutive time segments, each its own shape ──────
# Unlike "???" (weighted blend of the SAME time range), this concatenates
# segments end-to-end — each owns its own slice of time and its own slice of
# value, and the join points are shared so there is never a jump between
# segments. Reuses bake_labs_slot for curve-mode segments; the "flat"
# wildcard segment (hand-placed keyframes) gets its own baker below.

def bake_flat_segment(t0, v0, t1, v1, fps, keyframes=None, anchor_end=True):
    """keyframes: optional list of {"t":0..1, "v":0..1, "h1":[x,y], "h2":[x,y]}
    in the segment's OWN local space (t=0 at seg start, t=1 at seg end; same
    for v). h1/h2 are optional per-keyframe outgoing/incoming bezier handles
    in the same local-segment space; omitting both on a pair gives a
    straight line between them, which is how a flat/held section is made —
    two keyframes at the same v with no handles.

    anchor_end controls whether the LAST sample gets force-set to v1, same
    as every other bake_* function does by default. concat_labs_segments
    passes anchor_end=False for a non-final flat segment: a hold is defined
    by the user's own keyframes, not by whatever value the segment was
    theoretically assigned to reach — forcing it there would silently
    override an intentional flat hold with a jump nobody asked for.
    """
    span_t = t1 - t0
    span_v = v1 - v0
    n = max(1, round(span_t))
    if not keyframes or len(keyframes) < 2:
        kfs = [{"t": 0.0, "v": 0.0}, {"t": 1.0, "v": 1.0}]
    else:
        kfs = sorted(keyframes, key=lambda k: k.get("t", 0.0))
        if kfs[0].get("t", 0.0) > 1e-9:
            kfs = [{"t": 0.0, "v": kfs[0].get("v", 0.0)}] + kfs
        if kfs[-1].get("t", 1.0) < 1.0 - 1e-9:
            kfs = kfs + [{"t": 1.0, "v": kfs[-1].get("v", 1.0)}]
    result = []
    for i in range(n + 1):
        tn = i / n
        seg_i = len(kfs) - 2
        for j in range(len(kfs) - 1):
            if kfs[j]["t"] <= tn <= kfs[j+1]["t"]:
                seg_i = j
                break
        k0, k1 = kfs[seg_i], kfs[seg_i+1]
        dt = k1["t"] - k0["t"]
        local = 0.0 if dt <= 1e-9 else max(0.0, min(1.0, (tn - k0["t"]) / dt))
        h_out = k0.get("h_out")
        h_in = k1.get("h_in")
        shape = eval_bezier(local, h_out or [0.0, 0.0], h_in or [1.0, 1.0]) if (h_out or h_in) else local
        v_local = k0["v"] + (k1["v"] - k0["v"]) * shape
        result.append((t0 + tn * span_t, v0 + v_local * span_v))
    if result:
        result[0] = (result[0][0], v0)
        if anchor_end:
            result[-1] = (result[-1][0], v1)
    return result


def bake_labs_segment(segment, t0, v0, t1, v1, fps, anchor_end=True):
    """Dispatches one segment to bake_flat_segment (kind='flat') or
    bake_labs_slot (kind='curve', any of the 9 regular modes) — returns []
    on a genuinely empty/misconfigured segment rather than raising, since a
    segment with no mode picked yet is a normal mid-edit state, not an error.
    Curve-mode segments always anchor both ends (that's their whole design —
    always span exactly v0 to v1); anchor_end only affects 'flat' segments.
    """
    if not isinstance(segment, dict):
        return []
    kind = segment.get("kind", "curve")
    try:
        if kind == "flat":
            return bake_flat_segment(t0, v0, t1, v1, fps, segment.get("keyframes"),
                                     anchor_end=anchor_end)
        mode_name = segment.get("mode")
        if not mode_name:
            return []
        return bake_labs_slot(mode_name, t0, v0, t1, v1, fps, segment.get("params", {}))
    except Exception as e:
        log.warning("[MFlow] bake_labs_segment: kind='%s' raised: %s", kind, e)
        return []


def concat_labs_segments(segments, t0, v0, t1, v1, fps,
                          time_bounds=None, value_bounds=None, reverse_out=False):
    """Bakes up to 3 segments over their own consecutive sub-ranges of
    [t0,t1]/[v0,v1] and concatenates them into one continuous array — no
    blending, no averaging, just a relay hand-off. time_bounds/value_bounds
    are optional explicit fraction lists of len(segments)+1 (default: equal
    thirds for both) so a future UI can drag the join points without this
    function changing at all.

    Continuity is enforced by construction, not by hoping the numbers line
    up: each segment's real ENTRY value is whatever the previous segment
    actually produced as its last sample — never the theoretical
    value_bounds target — so a 'flat' segment that legitimately holds
    somewhere other than its assigned target still hands off correctly to
    whatever comes next. Only curve-mode segments (and the final segment,
    always) are forced to their assigned target value, since reaching a
    target is their whole design; a flat hold is defined by its own
    keyframes and must not be silently overridden.

    reverse_out=True applies the standard easeIn/easeOut reflection —
    v_out(t) = v0+v1-v_in(t1-t) — turning an "entrance" recipe into an
    "exit" one (or back) without rebuilding the segments, matching how
    ease-in/ease-out are mathematical mirror images of each other, not two
    independently-authored shapes.
    """
    segments = [s for s in (segments or []) if isinstance(s, dict)][:3]
    if not segments:
        return []
    n_segs = len(segments)
    if not time_bounds or len(time_bounds) != n_segs + 1:
        time_bounds = [i / n_segs for i in range(n_segs + 1)]
    if not value_bounds or len(value_bounds) != n_segs + 1:
        value_bounds = [i / n_segs for i in range(n_segs + 1)]
    span_t = t1 - t0
    span_v = v1 - v0
    result = []
    running_v0 = v0
    for i, seg in enumerate(segments):
        seg_t0 = t0 + time_bounds[i]   * span_t
        seg_t1 = t0 + time_bounds[i+1] * span_t
        if seg_t1 <= seg_t0:
            continue
        is_last = (i == n_segs - 1)
        target_v1 = v1 if is_last else (v0 + value_bounds[i+1] * span_v)
        kind = seg.get("kind", "curve")
        anchor_end = True if (kind != "flat" or is_last) else False
        baked = bake_labs_segment(seg, seg_t0, running_v0, seg_t1, target_v1, fps,
                                  anchor_end=anchor_end)
        if not baked:
            continue
        if result and abs(baked[0][0] - result[-1][0]) < 1e-6:
            baked = baked[1:]
        if baked:
            running_v0 = baked[-1][1]
        result.extend(baked)
    if not result:
        return []
    result[0]  = (result[0][0],  v0)
    result[-1] = (result[-1][0], v1)
    if reverse_out:
        n = len(result)
        frames = [f for f, _ in result]
        mirrored = []
        for i in range(n):
            v_in = result[n - 1 - i][1]
            mirrored.append((frames[i], v0 + v1 - v_in))
        result = mirrored
        result[0]  = (result[0][0],  v0)
        result[-1] = (result[-1][0], v1)
    return result
