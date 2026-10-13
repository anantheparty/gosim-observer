//! Rust port of `agent/kern.c`, the field-evaluation kernel of the Pleiades v4 observer.
//!
//! It exports the same four C-ABI functions with the same signatures, so the agent's ctypes loader
//! (`agent/policy.py`, class `Kernel`) can load `libkern.so` built from this crate instead of the C library.
//! Every floating-point operation is done in the same order as in the C source, and the trigonometric
//! functions come from the same libm, so the outputs are bit-identical to the C build (see `test_equiv.py`).
//!
//! Geometry mirrors challenge/v4_fiber_map.py: gnomonic plane at the field centre, rows along +alt ("up"),
//! columns along +az ("right"), cell = floor(d/pitch + side/2).

use std::f64::consts::PI;
use std::os::raw::{c_double, c_float, c_int};
use std::slice;

const DEG: f64 = PI / 180.0;
const R2D: f64 = 180.0 / PI;

/// Input slice from a C pointer; an empty slice for a zero length or a null pointer.
#[inline]
unsafe fn ins<'a, T>(p: *const T, n: usize) -> &'a [T] {
    if n == 0 || p.is_null() {
        &[]
    } else {
        slice::from_raw_parts(p, n)
    }
}

/// Output slice from a C pointer; an empty slice for a zero length or a null pointer.
#[inline]
unsafe fn outs<'a, T>(p: *mut T, n: usize) -> &'a mut [T] {
    if n == 0 || p.is_null() {
        &mut []
    } else {
        slice::from_raw_parts_mut(p, n)
    }
}

#[inline]
fn len(n: c_int) -> usize {
    if n > 0 { n as usize } else { 0 }
}

/// Unit vector of the field centre and the "up" (+alt) and "right" (+az) directions of its tangent plane.
#[inline]
fn basis(alt_deg: f64, az_deg: f64) -> ([f64; 3], [f64; 3], [f64; 3]) {
    let a = alt_deg * DEG;
    let z = az_deg * DEG;
    let (ca, sa, cz, sz) = (a.cos(), a.sin(), z.cos(), z.sin());
    ([ca * cz, ca * sz, sa], [-sa * cz, -sa * sz, ca], [-sz, cz, 0.0])
}

#[inline]
fn dot(u: &[f64; 3], c: &[f64; 3]) -> f64 {
    u[0] * c[0] + u[1] * c[1] + u[2] * c[2]
}

/// The j-th unit vector of a flat [n][3] array.
#[inline]
fn vec3(tv: &[f64], j: usize) -> &[f64; 3] {
    tv[3 * j..3 * j + 3].try_into().unwrap()
}

/// (int)floor(x) for the small, finite cell coordinates used here. Inlined instead of a call to the
/// out-of-line libm floor (x86-64 baseline has no SSE4.1 round instruction); exact for |x| < 2^31.
#[inline]
fn floor_i32(x: f64) -> i32 {
    let t = x as i32;
    if (t as f64) > x { t - 1 } else { t }
}

/// Fibre geometry of one field: side x side square cells of `pitch` degrees.
#[derive(Clone, Copy)]
struct Grid {
    side: i32,
    pitch: f64,
    half: f64,
    mid: f64,
}

impl Grid {
    fn new(side: c_int, pitch: f64) -> Grid {
        Grid { side, pitch, half: side as f64 * pitch / 2.0, mid: side as f64 / 2.0 }
    }

    /// Row and column of a tangent-plane offset (degrees), clamped to the grid as in the engine.
    #[inline]
    fn cell(&self, dal: f64, daz: f64) -> (i32, i32) {
        let clamp = |v: i32| if v < 0 { 0 } else if v >= self.side { self.side - 1 } else { v };
        (clamp(floor_i32(dal / self.pitch + self.mid)), clamp(floor_i32(daz / self.pitch + self.mid)))
    }

    /// Distance from the offset to the nearest edge of its cell (degrees).
    #[inline]
    fn margin(&self, dal: f64, daz: f64, row: i32, col: i32) -> f64 {
        let cn = (row as f64 - (self.side - 1) as f64 / 2.0) * self.pitch;
        let ce = (col as f64 - (self.side - 1) as f64 / 2.0) * self.pitch;
        let (a, b) = ((dal - cn).abs(), (daz - ce).abs());
        self.pitch / 2.0 - if a > b { a } else { b }
    }

    /// Cell index and margin of target `u` seen from a centre with basis (c, up, rt), or None when the
    /// target is outside the radius, outside the grid, or closer to a cell edge than `margin_min`.
    #[inline]
    fn place(&self, u: &[f64; 3], b: &([f64; 3], [f64; 3], [f64; 3]), cos_r: f64, margin_min: f64) -> Option<(i32, f64)> {
        let depth = dot(u, &b.0);
        if depth < cos_r {
            return None;
        }
        let dal = dot(u, &b.1) / depth * R2D;
        let daz = dot(u, &b.2) / depth * R2D;
        if dal.abs() > self.half || daz.abs() > self.half {
            return None;
        }
        let (row, col) = self.cell(dal, daz);
        let m = self.margin(dal, daz, row, col);
        if m < margin_min {
            return None;
        }
        Some((row * self.side + col, m))
    }
}

/// Best (rate, t, p, total) over the exposure grid for one centre, from the per-cell maxima of the
/// placed targets. `cells` is scratch space of nt * 3 * F values.
fn best_rate(placed: &[(usize, i32)], val: &[f32], nt: usize, tgrid: &[f64], nf: usize, cells: &mut [f64]) -> (f64, c_int, c_int, f64) {
    cells.iter_mut().for_each(|x| *x = 0.0);
    for &(j, f) in placed {
        let v = &val[j * nt * 3..(j + 1) * nt * 3];
        let f = f as usize;
        assert!(f < nf);
        // one row of nf cells per (t, p); the assert lets the compiler drop the per-element bounds check
        for (row, &x) in cells.chunks_exact_mut(nf).zip(v) {
            let x = x as f64;
            let cv = &mut row[f];
            // same result as `if (x > *cv) *cv = x;` in C, written as a select so it compiles to maxsd
            *cv = if x > *cv { x } else { *cv };
        }
    }
    let (mut best, mut bt, mut bp, mut btot) = (-1.0f64, 0, 0, 0.0f64);
    for t in 0..nt {
        for p in 0..3 {
            let cc = &cells[(t * 3 + p) * nf..(t * 3 + p + 1) * nf];
            let mut tot = 0.0f64;
            for &x in cc {
                tot += x;
            }
            let r = tot / tgrid[t];
            if r > best + 1e-12 || ((r - best).abs() <= 1e-12 && tot > btot) {
                best = r;
                bt = t as c_int;
                bp = p as c_int;
                btot = tot;
            }
        }
    }
    (best, bt, bp, btot)
}

/// val: [np][nt][3] float values (already -inf/0 where not allowed); tgrid: [nt] seconds.
/// For each centre: the best rate and its (t, p), and the summed value.
#[no_mangle]
pub unsafe extern "C" fn eval_centers(
    nc: c_int, calt: *const c_double, caz: *const c_double,
    np: c_int, tv: *const c_double, nt: c_int, val: *const c_float, tgrid: *const c_double,
    side: c_int, pitch: c_double, margin_min: c_double, cos_r: c_double,
    out_rate: *mut c_double, out_t: *mut c_int, out_p: *mut c_int, out_total: *mut c_double,
) {
    let (nc, np, nt) = (len(nc), len(np), len(nt));
    let g = Grid::new(side, pitch);
    let nf = len(side * side);
    let (calt, caz) = (ins(calt, nc), ins(caz, nc));
    let tv = ins(tv, 3 * np);
    let val = ins(val, np * nt * 3);
    let tgrid = ins(tgrid, nt);
    let (rate, ot, op, tot) = (outs(out_rate, nc), outs(out_t, nc), outs(out_p, nc), outs(out_total, nc));
    let mut cells = vec![0.0f64; nt * 3 * nf];
    let mut placed: Vec<(usize, i32)> = Vec::with_capacity(np);
    for k in 0..nc {
        let b = basis(calt[k], caz[k]);
        placed.clear();
        for j in 0..np {
            if let Some((f, _)) = g.place(vec3(tv, j), &b, cos_r, margin_min) {
                placed.push((j, f));
            }
        }
        let (r, t, p, s) = best_rate(&placed, val, nt, tgrid, nf, &mut cells);
        rate[k] = r;
        ot[k] = t;
        op[k] = p;
        tot[k] = s;
    }
}

/// Assignment for one centre and a chosen (t, p): per cell the best target (pool index) or -1.
/// Ties within 1e-12 go to the target farther from the cell edge.
#[no_mangle]
pub unsafe extern "C" fn assign_center(
    calt: c_double, caz: c_double, np: c_int, tv: *const c_double, nt: c_int, val: *const c_float,
    side: c_int, pitch: c_double, margin_min: c_double, cos_r: c_double, t: c_int, p: c_int,
    out_target: *mut c_int, out_value: *mut c_double,
) {
    let (np, nt) = (len(np), len(nt));
    let g = Grid::new(side, pitch);
    let nf = len(side * side);
    let tv = ins(tv, 3 * np);
    let val = ins(val, np * nt * 3);
    let (target, value) = (outs(out_target, nf), outs(out_value, nf));
    let mut bm = vec![-1.0f64; nf];
    target.iter_mut().for_each(|x| *x = -1);
    value.iter_mut().for_each(|x| *x = 0.0);
    let b = basis(calt, caz);
    let col = (t * 3 + p) as usize;
    for j in 0..np {
        if let Some((f, m)) = g.place(vec3(tv, j), &b, cos_r, margin_min) {
            let f = f as usize;
            let x = val[j * nt * 3 + col] as f64;
            if x > value[f] + 1e-12 || (target[f] >= 0 && (x - value[f]).abs() <= 1e-12 && m > bm[f]) {
                if x > 0.0 {
                    value[f] = x;
                    target[f] = j as c_int;
                    bm[f] = m;
                }
            }
        }
    }
}

/// Pointing-offset likelihood: for each candidate offset (dalt, daz in degrees), how many of the assigned
/// targets would land (or not land) on their fibre as observed. tv: [na][3] horizon vectors at exposure start.
#[no_mangle]
pub unsafe extern "C" fn offset_consistency(
    no: c_int, oalt: *const c_double, oaz: *const c_double, calt: c_double, caz: c_double,
    na: c_int, tv: *const c_double, fib: *const c_int, hit: *const c_int,
    side: c_int, pitch: c_double, out_agree: *mut c_int,
) {
    let (no, na) = (len(no), len(na));
    let g = Grid::new(side, pitch);
    let (oalt, oaz) = (ins(oalt, no), ins(oaz, no));
    let tv = ins(tv, 3 * na);
    let (fib, hit) = (ins(fib, na), ins(hit, na));
    let agree_out = outs(out_agree, no);
    for k in 0..no {
        let (c, up, rt) = basis(calt + oalt[k], caz + oaz[k]);
        let mut agree: c_int = 0;
        for j in 0..na {
            let u = vec3(tv, j);
            let depth = dot(u, &c);
            let mut pred: c_int = 0;
            if depth > 0.0 {
                let dal = dot(u, &up) / depth * R2D;
                let daz = dot(u, &rt) / depth * R2D;
                if dal.abs() <= g.half && daz.abs() <= g.half {
                    let (row, col) = g.cell(dal, daz);
                    pred = (row * g.side + col == fib[j]) as c_int;
                }
            }
            agree += (pred == hit[j]) as c_int;
        }
        agree_out[k] = agree;
    }
}

/// eval_centers for many groups of centres in one call. Group g holds centres [gstart[g], gend[g]) and only
/// the pool targets with dot(tv, gu[g]) >= cos_sub are considered for them, in pool order, so every centre
/// gets exactly the result of eval_centers on that subset.
/// zo (may be null): pool indices sorted by tv z (= sin altitude), zs the sorted z values and th_sub the
/// neighbourhood radius (rad): then only the altitude band that can hold the neighbourhood is scanned.
#[no_mangle]
pub unsafe extern "C" fn eval_groups(
    ng: c_int, gstart: *const c_int, gend: *const c_int, gu: *const c_double,
    calt: *const c_double, caz: *const c_double,
    np: c_int, tv: *const c_double, nt: c_int, val: *const c_float, tgrid: *const c_double,
    side: c_int, pitch: c_double, margin_min: c_double, cos_r: c_double, cos_sub: c_double,
    zo: *const c_int, zs: *const c_double, th_sub: c_double,
    out_rate: *mut c_double, out_t: *mut c_int, out_p: *mut c_int, out_total: *mut c_double,
) {
    let (ng, np, nt) = (len(ng), len(np), len(nt));
    let g = Grid::new(side, pitch);
    let nf = len(side * side);
    let (gstart, gend) = (ins(gstart, ng), ins(gend, ng));
    let gu = ins(gu, 3 * ng);
    let kmax = gend.iter().map(|&e| len(e)).max().unwrap_or(0);
    let (calt, caz) = (ins(calt, kmax), ins(caz, kmax));
    let tv = ins(tv, 3 * np);
    let val = ins(val, np * nt * 3);
    let tgrid = ins(tgrid, nt);
    let (zo, zs) = (if zo.is_null() { None } else { Some(ins(zo, np)) }, ins(zs, np));
    let (rate, ot, op, tot) = (outs(out_rate, kmax), outs(out_t, kmax), outs(out_p, kmax), outs(out_total, kmax));
    let mut sub: Vec<usize> = Vec::with_capacity(np);
    let mut placed: Vec<(usize, i32)> = Vec::with_capacity(np);
    let mut cells = vec![0.0f64; nt * 3 * nf];
    let near = |j: usize, u: &[f64; 3]| {
        let w = vec3(tv, j);
        w[0] * u[0] + w[1] * u[1] + w[2] * u[2] >= cos_sub
    };
    for gi in 0..ng {
        let u = vec3(gu, gi);
        sub.clear();
        match zo {
            Some(zo) => {
                let uz = if u[2] > 1.0 { 1.0 } else if u[2] < -1.0 { -1.0 } else { u[2] };
                let au = uz.asin();
                let (lo, hi) = (au - th_sub, au + th_sub);
                let zlo = if lo <= -PI / 2.0 { -2.0 } else { lo.sin() - 1e-9 };
                let zhi = if hi >= PI / 2.0 { 2.0 } else { hi.sin() + 1e-9 };
                // first index with zs >= zlo
                let (mut a, mut b) = (0usize, np);
                while a < b {
                    let m = (a + b) / 2;
                    if zs[m] < zlo { a = m + 1 } else { b = m }
                }
                let mut s = a;
                while s < np && zs[s] <= zhi {
                    let j = zo[s] as usize;
                    if near(j, u) {
                        sub.push(j);
                    }
                    s += 1;
                }
            }
            None => {
                for j in 0..np {
                    if near(j, u) {
                        sub.push(j);
                    }
                }
            }
        }
        for k in len(gstart[gi])..len(gend[gi]) {
            rate[k] = 0.0;
            ot[k] = 0;
            op[k] = 0;
            tot[k] = 0.0;
            if sub.is_empty() {
                continue;
            }
            let b = basis(calt[k], caz[k]);
            placed.clear();
            for &j in &sub {
                if let Some((f, _)) = g.place(vec3(tv, j), &b, cos_r, margin_min) {
                    placed.push((j, f));
                }
            }
            let (r, t, p, s) = best_rate(&placed, val, nt, tgrid, nf, &mut cells);
            rate[k] = r;
            ot[k] = t;
            op[k] = p;
            tot[k] = s;
        }
    }
}
