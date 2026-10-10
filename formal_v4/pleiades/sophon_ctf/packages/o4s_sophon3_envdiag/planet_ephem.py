"""Planet formulas from the official downloaded Sophon local check_sky.py (2026-10-06)."""
import math
from datetime import datetime, timezone

R = math.pi / 180


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def lst(t, lon):
    jd = t.timestamp() / 86400 + 2440587.5
    return (280.46061837 + 360.98564736629 * (jd - 2451545.0) + lon) % 360


def altaz(ra, dec, t, lat, lon):
    h = ((lst(t, lon) - ra + 180) % 360 - 180) * R
    la, de = lat * R, dec * R
    alt = math.asin(max(-1, min(1, math.sin(la) * math.sin(de) + math.cos(la) * math.cos(de) * math.cos(h))))
    ca = max(1e-12, math.cos(alt))
    az = math.atan2(-math.sin(h) * math.cos(de) / ca, (math.sin(de) - math.sin(alt) * math.sin(la)) / (ca * max(1e-12, math.cos(la))))
    return alt / R, (az / R) % 360


EL = {"venus": lambda d: (76.6799 + 2.4659e-5 * d, 3.3946 + 2.75e-8 * d, 54.891 + 1.38374e-5 * d, 0.72333, 0.006773 - 1.302e-9 * d, 48.0052 + 1.6021302244 * d),
      "mars": lambda d: (49.5574 + 2.11081e-5 * d, 1.8497 - 1.78e-8 * d, 286.5016 + 2.92961e-5 * d, 1.523688, 0.093405 + 2.516e-9 * d, 18.6021 + 0.5240207766 * d),
      "jupiter": lambda d: (100.4542 + 2.76854e-5 * d, 1.303 - 1.557e-7 * d, 273.8777 + 1.64505e-5 * d, 5.20256, 0.048498 + 4.469e-9 * d, 19.895 + 0.0830853001 * d),
      "saturn": lambda d: (113.6634 + 2.3898e-5 * d, 2.4886 - 1.081e-7 * d, 339.3939 + 2.97661e-5 * d, 9.55475, 0.055546 - 9.499e-9 * d, 316.967 + 0.0334442282 * d)}


def kepler(M, e):
    E = M + e * math.sin(M) * (1 + e * math.cos(M))
    for _ in range(8):
        E -= (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
    return E


def planet(name, t):
    d = (t - datetime(1999, 12, 31, tzinfo=timezone.utc)).total_seconds() / 86400
    ws, es, Ms = 282.9404 + 4.70935e-5 * d, 0.016709 - 1.151e-9 * d, (356.047 + 0.9856002585 * d) % 360 * R
    E = kepler(Ms, es)
    v, r = math.atan2(math.sqrt(1 - es * es) * math.sin(E), math.cos(E) - es), math.hypot(math.cos(E) - es, math.sqrt(1 - es * es) * math.sin(E))
    xs, ys = r * math.cos(v + ws * R), r * math.sin(v + ws * R)
    N, i, w, a, e, M = EL[name](d)
    E = kepler(M % 360 * R, e)
    xv, yv = a * (math.cos(E) - e), a * math.sqrt(1 - e * e) * math.sin(E)
    v, r = math.atan2(yv, xv), math.hypot(xv, yv)
    N, i, w = N * R, i * R, w * R
    x = r * (math.cos(N) * math.cos(v + w) - math.sin(N) * math.sin(v + w) * math.cos(i))
    y = r * (math.sin(N) * math.cos(v + w) + math.cos(N) * math.sin(v + w) * math.cos(i))
    z = r * math.sin(v + w) * math.sin(i)
    if name in ("jupiter", "saturn"):
        Mj, Msa = (19.895 + 0.0830853001 * d) % 360 * R, (316.967 + 0.0334442282 * d) % 360 * R
        lon, lat, rr = math.atan2(y, x), math.atan2(z, math.hypot(x, y)), math.sqrt(x * x + y * y + z * z)
        if name == "saturn":
            lon += R * (0.812 * math.sin(2 * Mj - 5 * Msa - 67.6 * R) - 0.229 * math.cos(2 * Mj - 4 * Msa - 2 * R) + 0.119 * math.sin(Mj - 2 * Msa - 3 * R)
                        + 0.046 * math.sin(2 * Mj - 6 * Msa - 69 * R) + 0.014 * math.sin(Mj - 3 * Msa + 32 * R))
            lat += R * (-0.02 * math.cos(2 * Mj - 4 * Msa - 2 * R) + 0.018 * math.sin(2 * Mj - 6 * Msa - 49 * R))
        else:
            lon += R * (-0.332 * math.sin(2 * Mj - 5 * Msa - 67.6 * R) - 0.056 * math.sin(2 * Mj - 2 * Msa + 21 * R) + 0.042 * math.sin(3 * Mj - 5 * Msa + 21 * R)
                        - 0.036 * math.sin(Mj - 2 * Msa) + 0.022 * math.cos(Mj - Msa) + 0.023 * math.sin(2 * Mj - 3 * Msa + 52 * R) - 0.016 * math.sin(Mj - 5 * Msa - 69 * R))
        x, y, z = rr * math.cos(lon) * math.cos(lat), rr * math.sin(lon) * math.cos(lat), rr * math.sin(lat)
    xg, yg, zg = x + xs, y + ys, z
    ecl = (23.4393 - 3.563e-7 * d) * R
    ye, ze = yg * math.cos(ecl) - zg * math.sin(ecl), yg * math.sin(ecl) + zg * math.cos(ecl)
    return (math.atan2(ye, xg) / R) % 360, math.atan2(ze, math.hypot(xg, ye)) / R


def sep(a1, z1, a2, z2):
    c = math.sin(a1 * R) * math.sin(a2 * R) + math.cos(a1 * R) * math.cos(a2 * R) * math.cos((z1 - z2) * R)
    return math.acos(max(-1, min(1, c))) / R

