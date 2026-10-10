"""Public sky geometry used by the v4 engine (same low-precision formulas), vectorized."""
import math
from datetime import datetime, timezone

import numpy as np

DEG = math.pi / 180.0
SID = 360.98564736629  # deg per day


def parse_utc(s):
    return datetime.fromisoformat(str(s).replace('Z', '+00:00')).astimezone(timezone.utc).timestamp()


def fmt_utc(t):
    return datetime.fromtimestamp(round(t), tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def days_j2000(t):
    return t / 86400.0 + 2440587.5 - 2451545.0


def lst_deg(t, lon):
    return (280.46061837 + SID * days_j2000(t) + lon) % 360.0


def sun_radec(t):
    d = days_j2000(t)
    L = (280.460 + 0.9856474 * d) % 360.0
    g = math.radians((357.528 + 0.9856003 * d) % 360.0)
    lam = math.radians((L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)) % 360.0)
    eps = math.radians(23.439 - 0.0000004 * d)
    ra = math.degrees(math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))) % 360.0
    dec = math.degrees(math.asin(math.sin(eps) * math.sin(lam)))
    return ra, dec


def moon_radec(t):
    d = days_j2000(t)
    Lm = math.radians((218.316 + 13.176396 * d) % 360.0)
    Mm = math.radians((134.963 + 13.064993 * d) % 360.0)
    Fm = math.radians((93.272 + 13.229350 * d) % 360.0)
    lon = Lm + math.radians(6.289) * math.sin(Mm)
    lat = math.radians(5.128) * math.sin(Fm)
    eps = math.radians(23.439 - 0.0000004 * d)
    x = math.cos(lon) * math.cos(lat)
    y = math.sin(lon) * math.cos(lat) * math.cos(eps) - math.sin(lat) * math.sin(eps)
    z = math.sin(lon) * math.cos(lat) * math.sin(eps) + math.sin(lat) * math.cos(eps)
    return math.degrees(math.atan2(y, x)) % 360.0, math.degrees(math.asin(max(-1.0, min(1.0, z))))


def sep_deg(ra1, dec1, ra2, dec2):
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    c = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(r1 - r2)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def alt_scalar(ra, dec, t, lat, lon):
    ha = math.radians((lst_deg(t, lon) - ra + 180.0) % 360.0 - 180.0)
    la, de = math.radians(lat), math.radians(dec)
    s = math.sin(la) * math.sin(de) + math.cos(la) * math.cos(de) * math.cos(ha)
    return math.degrees(math.asin(max(-1.0, min(1.0, s))))


def moon_state(t, lat, lon):
    """(moon unit vector equatorial, illumination, moon altitude deg)."""
    mra, mdec = moon_radec(t)
    sra, sdec = sun_radec(t)
    illum = (1.0 - math.cos(math.radians(sep_deg(sra, sdec, mra, mdec)))) / 2.0
    malt = alt_scalar(mra, mdec, t, lat, lon)
    r, d = math.radians(mra), math.radians(mdec)
    vec = np.array([math.cos(d) * math.cos(r), math.cos(d) * math.sin(r), math.sin(d)])
    return vec, illum, malt


def airmass(alt_deg):
    z = 90.0 - np.clip(alt_deg, 1.0, 90.0)
    raw = 1.0 / (np.cos(z * DEG) + 0.50572 * (96.07995 - z) ** -1.6364)
    zr = 1.0 / (1.0 + 0.50572 * 96.07995 ** -1.6364)
    return raw / zr


def sun_alt(t, lat, lon):
    ra, dec = sun_radec(t)
    return alt_scalar(ra, dec, t, lat, lon)
