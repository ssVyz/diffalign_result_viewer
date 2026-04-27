"""Color utilities — ports of the legacy `utils/colors.ts`.

Returns RGB tuples (0–255 ints). Heatmap rendering uses these directly to
build QImage pixel buffers in vectorized numpy operations.
"""

from __future__ import annotations

import numpy as np

RGB = tuple[int, int, int]

GREEN: RGB = (0, 180, 0)
YELLOW: RGB = (220, 200, 0)
RED: RGB = (220, 50, 50)
DARK_RED: RGB = (100, 20, 20)
NO_DATA: RGB = (40, 40, 40)


def _green_yellow_red_from_t(t: float) -> RGB:
    if t <= 0.5:
        s = t * 2.0
        return (
            int(GREEN[0] + (YELLOW[0] - GREEN[0]) * s),
            int(GREEN[1] + (YELLOW[1] - GREEN[1]) * s),
            int(GREEN[2] + (YELLOW[2] - GREEN[2]) * s),
        )
    s = (t - 0.5) * 2.0
    return (
        int(YELLOW[0] + (RED[0] - YELLOW[0]) * s),
        int(YELLOW[1] + (RED[1] - YELLOW[1]) * s),
        int(YELLOW[2] + (RED[2] - YELLOW[2]) * s),
    )


def _gradient_t(value: float, green_at: float, red_at: float) -> float:
    if red_at <= green_at:
        return 0.0 if value <= green_at else 1.0
    if value <= green_at:
        return 0.0
    if value >= red_at:
        return 1.0
    return (value - green_at) / (red_at - green_at)


def _ramp(value: float, low: float, high: float) -> float:
    v = max(0.0, min(1.0, value))
    lo = max(0.0, min(1.0, low))
    hi = max(0.0, min(1.0, high))
    if hi <= lo:
        return 0.0 if v <= lo else 1.0
    if v <= lo:
        return 0.0
    if v >= hi:
        return 1.0
    return (v - lo) / (hi - lo)


def position_color(
    variant_count: int,
    no_match_fraction: float,
    green_at: int,
    red_at: int,
    nomatch_ok: float,
    nomatch_bad: float,
) -> RGB:
    if variant_count == 0:
        return NO_DATA
    t = _gradient_t(float(variant_count), float(green_at), float(red_at))
    base_r, base_g, base_b = _green_yellow_red_from_t(t)
    nm_t = _ramp(no_match_fraction, nomatch_ok, nomatch_bad)
    r = int(base_r * (1 - nm_t) + DARK_RED[0] * nm_t)
    g = int(base_g * (1 - nm_t) + DARK_RED[1] * nm_t)
    b = int(base_b * (1 - nm_t) + DARK_RED[2] * nm_t)
    return (r, g, b)


def differential_position_color(
    min_mismatches: int | None,
    variant_count: int,
    no_match_fraction: float,
    diff_green_at: int,
    diff_red_at: int,
    var_green_at: int,
    var_red_at: int,
    nomatch_ok: float,
    nomatch_bad: float,
) -> RGB:
    if variant_count == 0:
        return NO_DATA
    variant_dark = _ramp(
        float(variant_count - var_green_at) / max(1.0, float(var_red_at - var_green_at))
        if var_red_at > var_green_at
        else (1.0 if variant_count > var_green_at else 0.0),
        0.0,
        1.0,
    )
    nomatch_dark = _ramp(no_match_fraction, nomatch_ok, nomatch_bad)
    darkening = max(variant_dark, nomatch_dark)

    if min_mismatches is None:
        t = 0.0
    else:
        if diff_green_at <= diff_red_at:
            t = 0.0 if min_mismatches <= diff_green_at else 1.0
        elif min_mismatches >= diff_green_at:
            t = 0.0
        elif min_mismatches <= diff_red_at:
            t = 1.0
        else:
            t = (diff_green_at - min_mismatches) / (diff_green_at - diff_red_at)

    base_r, base_g, base_b = _green_yellow_red_from_t(t)
    r = int(base_r * (1 - darkening) + DARK_RED[0] * darkening)
    g = int(base_g * (1 - darkening) + DARK_RED[1] * darkening)
    b = int(base_b * (1 - darkening) + DARK_RED[2] * darkening)
    return (r, g, b)


def base_color(base: str) -> RGB:
    if base == "A":
        return (100, 200, 100)
    if base == "T" or base == "U":
        return (220, 80, 80)
    if base == "G":
        return (255, 200, 60)
    if base == "C":
        return (100, 150, 255)
    return (136, 136, 136)


# ── Vectorized helpers (used by heatmap to color whole rows at once) ──

def colorize_grid_rgba(
    variants_needed: np.ndarray,  # int32 (N,)
    no_match_count: np.ndarray,  # int32 (N,)
    total_sequences: np.ndarray,  # int32 (N,)
    skipped: np.ndarray,  # bool (N,)
    green_at: int,
    red_at: int,
    nomatch_ok_pct: float,
    nomatch_bad_pct: float,
) -> np.ndarray:
    """Return an (N, 4) uint8 RGBA array for the given row of cells."""
    n = variants_needed.shape[0]
    out = np.empty((n, 4), dtype=np.uint8)

    # default: NO_DATA color
    out[:, 0] = NO_DATA[0]
    out[:, 1] = NO_DATA[1]
    out[:, 2] = NO_DATA[2]
    out[:, 3] = 255

    # skipped → gray-blue tint, distinct from "no data"
    skipped_color = np.array([60, 60, 80, 255], dtype=np.uint8)
    out[skipped] = skipped_color

    active = (~skipped) & (variants_needed > 0)
    if not active.any():
        return out

    v = variants_needed[active].astype(np.float32)
    if red_at > green_at:
        t = np.clip((v - green_at) / max(1.0, red_at - green_at), 0.0, 1.0)
    else:
        t = np.where(v <= green_at, 0.0, 1.0).astype(np.float32)

    r = np.empty_like(t)
    g = np.empty_like(t)
    b = np.empty_like(t)
    half = t <= 0.5
    s = np.where(half, t * 2.0, (t - 0.5) * 2.0)
    r[half] = GREEN[0] + (YELLOW[0] - GREEN[0]) * s[half]
    g[half] = GREEN[1] + (YELLOW[1] - GREEN[1]) * s[half]
    b[half] = GREEN[2] + (YELLOW[2] - GREEN[2]) * s[half]
    r[~half] = YELLOW[0] + (RED[0] - YELLOW[0]) * s[~half]
    g[~half] = YELLOW[1] + (RED[1] - YELLOW[1]) * s[~half]
    b[~half] = YELLOW[2] + (RED[2] - YELLOW[2]) * s[~half]

    nm_frac = np.where(
        total_sequences[active] > 0,
        no_match_count[active] / np.maximum(total_sequences[active], 1),
        0.0,
    ).astype(np.float32)

    nm_ok = nomatch_ok_pct / 100.0
    nm_bad = nomatch_bad_pct / 100.0
    if nm_bad > nm_ok:
        nm_t = np.clip((nm_frac - nm_ok) / (nm_bad - nm_ok), 0.0, 1.0)
    else:
        nm_t = np.where(nm_frac <= nm_ok, 0.0, 1.0).astype(np.float32)

    r = r * (1 - nm_t) + DARK_RED[0] * nm_t
    g = g * (1 - nm_t) + DARK_RED[1] * nm_t
    b = b * (1 - nm_t) + DARK_RED[2] * nm_t

    out[active, 0] = np.clip(r, 0, 255).astype(np.uint8)
    out[active, 1] = np.clip(g, 0, 255).astype(np.uint8)
    out[active, 2] = np.clip(b, 0, 255).astype(np.uint8)
    out[active, 3] = 255
    return out


def colorize_grid_differential_rgba(
    variants_needed: np.ndarray,
    no_match_count: np.ndarray,
    total_sequences: np.ndarray,
    skipped: np.ndarray,
    min_mismatches: np.ndarray,  # int32 with sentinels
    excl_total: np.ndarray,
    excl_no_match: np.ndarray,
    diff_green_at: int,
    diff_red_at: int,
    var_green_at: int,
    var_red_at: int,
    nomatch_ok_pct: float,
    nomatch_bad_pct: float,
    diff_ignore_count: int,
) -> np.ndarray:
    """Vectorized version of `differential_position_color` over a row."""
    from .models import NO_MATCH_SENTINEL, NO_MIN_MM_SENTINEL, SKIPPED_SENTINEL

    n = variants_needed.shape[0]
    out = np.empty((n, 4), dtype=np.uint8)
    out[:, :] = (NO_DATA[0], NO_DATA[1], NO_DATA[2], 255)

    skipped_color = np.array([60, 60, 80, 255], dtype=np.uint8)
    out[skipped] = skipped_color

    active = (~skipped) & (variants_needed > 0)
    if not active.any():
        return out

    v = variants_needed[active].astype(np.float32)
    if var_red_at > var_green_at:
        var_dark = np.clip((v - var_green_at) / max(1.0, var_red_at - var_green_at), 0.0, 1.0)
    else:
        var_dark = np.where(v > var_green_at, 1.0, 0.0).astype(np.float32)

    nm_frac = np.where(
        total_sequences[active] > 0,
        no_match_count[active] / np.maximum(total_sequences[active], 1),
        0.0,
    ).astype(np.float32)
    nm_ok = nomatch_ok_pct / 100.0
    nm_bad = nomatch_bad_pct / 100.0
    if nm_bad > nm_ok:
        nm_dark = np.clip((nm_frac - nm_ok) / (nm_bad - nm_ok), 0.0, 1.0)
    else:
        nm_dark = np.where(nm_frac <= nm_ok, 0.0, 1.0).astype(np.float32)

    darkening = np.maximum(var_dark, nm_dark)

    # Compute t from min_mismatches.
    # ignore the min_mismatches when (excl_total - excl_no_match) <= diff_ignore_count
    aligned_excl = excl_total[active] - excl_no_match[active]
    mm = min_mismatches[active].astype(np.int64)
    use_min = (aligned_excl > diff_ignore_count) & (mm != NO_MIN_MM_SENTINEL) & (mm != SKIPPED_SENTINEL) & (mm != NO_MATCH_SENTINEL)

    t = np.zeros(v.shape[0], dtype=np.float32)
    if diff_green_at <= diff_red_at:
        # degenerate — anything <= green_at is best, > is worst
        t_use = np.where(mm[use_min] <= diff_green_at, 0.0, 1.0).astype(np.float32)
    else:
        ratio = (diff_green_at - mm[use_min].astype(np.float32)) / max(
            1e-6, float(diff_green_at - diff_red_at)
        )
        t_use = np.clip(ratio, 0.0, 1.0)
        t_use[mm[use_min] >= diff_green_at] = 0.0
        t_use[mm[use_min] <= diff_red_at] = 1.0
    t[use_min] = t_use

    r = np.empty_like(t)
    g = np.empty_like(t)
    b = np.empty_like(t)
    half = t <= 0.5
    s = np.where(half, t * 2.0, (t - 0.5) * 2.0)
    r[half] = GREEN[0] + (YELLOW[0] - GREEN[0]) * s[half]
    g[half] = GREEN[1] + (YELLOW[1] - GREEN[1]) * s[half]
    b[half] = GREEN[2] + (YELLOW[2] - GREEN[2]) * s[half]
    r[~half] = YELLOW[0] + (RED[0] - YELLOW[0]) * s[~half]
    g[~half] = YELLOW[1] + (RED[1] - YELLOW[1]) * s[~half]
    b[~half] = YELLOW[2] + (RED[2] - YELLOW[2]) * s[~half]

    r = r * (1 - darkening) + DARK_RED[0] * darkening
    g = g * (1 - darkening) + DARK_RED[1] * darkening
    b = b * (1 - darkening) + DARK_RED[2] * darkening

    out[active, 0] = np.clip(r, 0, 255).astype(np.uint8)
    out[active, 1] = np.clip(g, 0, 255).astype(np.uint8)
    out[active, 2] = np.clip(b, 0, 255).astype(np.uint8)
    out[active, 3] = 255
    return out


def gradient_legend_swatches(green_at: int, red_at: int, steps: int = 8) -> list[tuple[int, RGB]]:
    """Returns a list of (value, color) tuples spanning green_at→red_at."""
    lo = min(green_at, red_at)
    hi = max(green_at, red_at)
    rng = max(1, hi - lo)
    out: list[tuple[int, RGB]] = []
    for i in range(steps + 1):
        v = lo + rng * i / steps
        t = _gradient_t(v, green_at, red_at)
        c = _green_yellow_red_from_t(t)
        out.append((round(v), c))
    return out
