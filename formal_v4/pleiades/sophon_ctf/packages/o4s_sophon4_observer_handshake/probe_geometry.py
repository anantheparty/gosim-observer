"""Geometry retained from sophon2; no planner or external services."""

import math

import numpy as np

DEG = math.pi / 180

def _classify_np(calt, caz, tv, side, pitch, margin_min, cos_r):
    a, z = (calt * DEG, caz * DEG)
    c = np.array([math.cos(a) * math.cos(z), math.cos(a) * math.sin(z), math.sin(a)])
    up = np.array([-math.sin(a) * math.cos(z), -math.sin(a) * math.sin(z), math.cos(a)])
    rt = np.array([-math.sin(z), math.cos(z), 0.0])
    depth = tv @ c
    ok = depth >= cos_r
    dep = np.where(ok, depth, 1.0)
    dal = tv @ up / dep / DEG
    daz = tv @ rt / dep / DEG
    half = side * pitch / 2.0
    ok &= (np.abs(dal) <= half) & (np.abs(daz) <= half)
    row = np.clip(np.floor(dal / pitch + side / 2.0), 0, side - 1).astype(int)
    col = np.clip(np.floor(daz / pitch + side / 2.0), 0, side - 1).astype(int)
    cn = (row - (side - 1) / 2.0) * pitch
    ce = (col - (side - 1) / 2.0) * pitch
    m = pitch / 2.0 - np.maximum(np.abs(dal - cn), np.abs(daz - ce))
    ok &= m >= margin_min
    return (np.flatnonzero(ok), (row * side + col)[ok], m[ok])

def _shift(alt, az, d_up, d_right):
    a, z = (alt * DEG, az * DEG)
    c = np.array([math.cos(a) * math.cos(z), math.cos(a) * math.sin(z), math.sin(a)])
    up = np.array([-math.sin(a) * math.cos(z), -math.sin(a) * math.sin(z), math.cos(a)])
    rt = np.array([-math.sin(z), math.cos(z), 0.0])
    v = c + math.tan(d_up * DEG) * up + math.tan(d_right * DEG) * rt
    v /= np.linalg.norm(v)
    return (math.asin(max(-1.0, min(1.0, v[2]))) / DEG, math.atan2(v[1], v[0]) / DEG % 360.0)
