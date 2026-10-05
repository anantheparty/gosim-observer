// Field evaluation kernel for the v4 observer policy.
// Geometry mirrors challenge/v4_fiber_map.py: gnomonic plane at the field centre,
// rows along +alt ("up"), columns along +az ("right"), cell = floor(d/pitch + side/2).
#include <math.h>
#include <stdlib.h>
#include <string.h>

static void basis(double alt_deg, double az_deg, double c[3], double up[3], double rt[3]) {
    const double D = M_PI / 180.0;
    double a = alt_deg * D, z = az_deg * D;
    double ca = cos(a), sa = sin(a), cz = cos(z), sz = sin(z);
    c[0] = ca * cz; c[1] = ca * sz; c[2] = sa;
    up[0] = -sa * cz; up[1] = -sa * sz; up[2] = ca;
    rt[0] = -sz; rt[1] = cz; rt[2] = 0.0;
}

// Classify pool targets for one centre. Returns number of valid targets written to cell/margin arrays.
static int classify(double calt, double caz, int np, const double *tv, int side, double pitch,
                    double margin_min, double cos_r, int *cell_out, int *idx_out, double *margin_out) {
    double c[3], up[3], rt[3];
    basis(calt, caz, c, up, rt);
    const double R2D = 180.0 / M_PI;
    double half = side * pitch / 2.0;
    double mid = side / 2.0;
    int n = 0;
    for (int j = 0; j < np; j++) {
        const double *u = tv + 3 * j;
        double depth = u[0] * c[0] + u[1] * c[1] + u[2] * c[2];
        if (depth < cos_r) continue;
        double dal = (u[0] * up[0] + u[1] * up[1] + u[2] * up[2]) / depth * R2D;
        double daz = (u[0] * rt[0] + u[1] * rt[1] + u[2] * rt[2]) / depth * R2D;
        if (fabs(dal) > half || fabs(daz) > half) continue;
        int row = (int)floor(dal / pitch + mid);
        int col = (int)floor(daz / pitch + mid);
        if (row < 0) row = 0; if (row >= side) row = side - 1;
        if (col < 0) col = 0; if (col >= side) col = side - 1;
        double cn = (row - (side - 1) / 2.0) * pitch, ce = (col - (side - 1) / 2.0) * pitch;
        double m = pitch / 2.0 - (fabs(dal - cn) > fabs(daz - ce) ? fabs(dal - cn) : fabs(daz - ce));
        if (m < margin_min) continue;
        cell_out[n] = row * side + col;
        idx_out[n] = j;
        margin_out[n] = m;
        n++;
    }
    return n;
}

// val: [np][nt][3] float values (already include -inf/0 for disallowed); tgrid: [nt] seconds.
// For each centre returns best rate and its (t, p).
void eval_centers(int nc, const double *calt, const double *caz,
                             int np, const double *tv, int nt, const float *val, const double *tgrid,
                             int side, double pitch, double margin_min, double cos_r,
                             double *out_rate, int *out_t, int *out_p, double *out_total) {
    int F = side * side;
    int *cell = (int *)malloc(sizeof(int) * (np > 0 ? np : 1));
    int *idx = (int *)malloc(sizeof(int) * (np > 0 ? np : 1));
    double *marg = (double *)malloc(sizeof(double) * (np > 0 ? np : 1));
    double *cells = (double *)malloc(sizeof(double) * (size_t)nt * 3 * F);
    for (int k = 0; k < nc; k++) {
        int n = classify(calt[k], caz[k], np, tv, side, pitch, margin_min, cos_r, cell, idx, marg);
        memset(cells, 0, sizeof(double) * (size_t)nt * 3 * F);
        for (int q = 0; q < n; q++) {
            const float *v = val + (size_t)idx[q] * nt * 3;
            int f = cell[q];
            for (int t = 0; t < nt; t++) {
                for (int p = 0; p < 3; p++) {
                    double x = v[t * 3 + p];
                    double *cv = &cells[((size_t)t * 3 + p) * F + f];
                    if (x > *cv) *cv = x;
                }
            }
        }
        double best = -1.0; int bt = 0, bp = 0; double btot = 0.0;
        for (int t = 0; t < nt; t++) {
            for (int p = 0; p < 3; p++) {
                const double *cc = cells + ((size_t)t * 3 + p) * F;
                double tot = 0.0;
                for (int f = 0; f < F; f++) tot += cc[f];
                double r = tot / tgrid[t];
                if (r > best + 1e-12 || (fabs(r - best) <= 1e-12 && tot > btot)) { best = r; bt = t; bp = p; btot = tot; }
            }
        }
        out_rate[k] = best; out_t[k] = bt; out_p[k] = bp; out_total[k] = btot;
    }
    free(cell); free(idx); free(marg); free(cells);
}

// Assignment for one centre and chosen (t, p): per cell the best target (pool index) or -1.
void assign_center(double calt, double caz, int np, const double *tv, int nt, const float *val,
                              int side, double pitch, double margin_min, double cos_r, int t, int p,
                              int *out_target, double *out_value) {
    int F = side * side;
    int *cell = (int *)malloc(sizeof(int) * (np > 0 ? np : 1));
    int *idx = (int *)malloc(sizeof(int) * (np > 0 ? np : 1));
    double *marg = (double *)malloc(sizeof(double) * (np > 0 ? np : 1));
    double *bm = (double *)malloc(sizeof(double) * F);
    int n = classify(calt, caz, np, tv, side, pitch, margin_min, cos_r, cell, idx, marg);
    for (int f = 0; f < F; f++) { out_target[f] = -1; out_value[f] = 0.0; bm[f] = -1.0; }
    for (int q = 0; q < n; q++) {
        double x = val[(size_t)idx[q] * nt * 3 + t * 3 + p];
        int f = cell[q];
        if (x > out_value[f] + 1e-12 || (out_target[f] >= 0 && fabs(x - out_value[f]) <= 1e-12 && marg[q] > bm[f])) {
            if (x > 0) { out_value[f] = x; out_target[f] = idx[q]; bm[f] = marg[q]; }
        }
    }
    free(cell); free(idx); free(marg); free(bm);
}

// Pointing-offset likelihood: for each candidate offset (dalt, daz in deg), count how many of the
// assigned targets would land on their assigned fibre. tv: [na][3] horizon vectors at exposure start.
void offset_consistency(int no, const double *oalt, const double *oaz, double calt, double caz,
                                   int na, const double *tv, const int *fib, const int *hit,
                                   int side, double pitch, int *out_agree) {
    double half = side * pitch / 2.0, mid = side / 2.0;
    const double R2D = 180.0 / M_PI;
    for (int k = 0; k < no; k++) {
        double c[3], up[3], rt[3];
        basis(calt + oalt[k], caz + oaz[k], c, up, rt);
        int agree = 0;
        for (int j = 0; j < na; j++) {
            const double *u = tv + 3 * j;
            double depth = u[0] * c[0] + u[1] * c[1] + u[2] * c[2];
            int pred = 0;
            if (depth > 0) {
                double dal = (u[0] * up[0] + u[1] * up[1] + u[2] * up[2]) / depth * R2D;
                double daz = (u[0] * rt[0] + u[1] * rt[1] + u[2] * rt[2]) / depth * R2D;
                if (fabs(dal) <= half && fabs(daz) <= half) {
                    int row = (int)floor(dal / pitch + mid), col = (int)floor(daz / pitch + mid);
                    if (row < 0) row = 0; if (row >= side) row = side - 1;
                    if (col < 0) col = 0; if (col >= side) col = side - 1;
                    pred = (row * side + col) == fib[j];
                }
            }
            agree += (pred == hit[j]);
        }
        out_agree[k] = agree;
    }
}

// eval_centers for many groups of centres in one call: group g holds centres [gstart[g], gend[g]) and only the
// pool targets with dot(tv, gu[g]) >= cos_sub are considered for them (the caller's neighbourhood rule), in
// pool order, so every centre gets exactly the result of eval_centers on that subset. Groups are independent:
// callers may split them across threads (no shared state; outputs are written per centre).
// zo (optional, may be NULL): pool indices sorted by tv z (= sin altitude) with zs the sorted z values and th_sub
// the neighbourhood radius (rad, acos(cos_sub)): then only the altitude band that can hold the neighbourhood is
// scanned. The cell maxima do not depend on the order of the targets, so the results are the same.
void eval_groups(int ng, const int *gstart, const int *gend, const double *gu,
                 const double *calt, const double *caz,
                 int np, const double *tv, int nt, const float *val, const double *tgrid,
                 int side, double pitch, double margin_min, double cos_r, double cos_sub,
                 const int *zo, const double *zs, double th_sub,
                 double *out_rate, int *out_t, int *out_p, double *out_total) {
    int F = side * side;
    int *sub = (int *)malloc(sizeof(int) * (np > 0 ? np : 1));
    int *cell = (int *)malloc(sizeof(int) * (np > 0 ? np : 1));
    int *idx = (int *)malloc(sizeof(int) * (np > 0 ? np : 1));
    double *cells = (double *)malloc(sizeof(double) * (size_t)nt * 3 * F);
    const double R2D = 180.0 / M_PI;
    double half = side * pitch / 2.0;
    double mid = side / 2.0;
    for (int g = 0; g < ng; g++) {
        const double *u = gu + 3 * g;
        int ns = 0;
        if (zo != NULL) {
            double au = asin(u[2] > 1.0 ? 1.0 : (u[2] < -1.0 ? -1.0 : u[2]));
            double lo = au - th_sub, hi = au + th_sub;
            double zlo = lo <= -M_PI / 2 ? -2.0 : sin(lo) - 1e-9;
            double zhi = hi >= M_PI / 2 ? 2.0 : sin(hi) + 1e-9;
            int a = 0, b = np;               // first index with zs >= zlo
            while (a < b) { int m = (a + b) / 2; if (zs[m] < zlo) a = m + 1; else b = m; }
            for (int s = a; s < np && zs[s] <= zhi; s++) {
                int j = zo[s];
                const double *v = tv + 3 * j;
                if (v[0] * u[0] + v[1] * u[1] + v[2] * u[2] >= cos_sub) sub[ns++] = j;
            }
        } else {
            for (int j = 0; j < np; j++) {
                const double *v = tv + 3 * j;
                if (v[0] * u[0] + v[1] * u[1] + v[2] * u[2] >= cos_sub) sub[ns++] = j;
            }
        }
        for (int k = gstart[g]; k < gend[g]; k++) {
            out_rate[k] = 0.0; out_t[k] = 0; out_p[k] = 0; out_total[k] = 0.0;
            if (ns == 0) continue;
            double c[3], up[3], rt[3];
            basis(calt[k], caz[k], c, up, rt);
            int n = 0;
            for (int s = 0; s < ns; s++) {
                int j = sub[s];
                const double *w = tv + 3 * j;
                double depth = w[0] * c[0] + w[1] * c[1] + w[2] * c[2];
                if (depth < cos_r) continue;
                double dal = (w[0] * up[0] + w[1] * up[1] + w[2] * up[2]) / depth * R2D;
                double daz = (w[0] * rt[0] + w[1] * rt[1] + w[2] * rt[2]) / depth * R2D;
                if (fabs(dal) > half || fabs(daz) > half) continue;
                int row = (int)floor(dal / pitch + mid);
                int col = (int)floor(daz / pitch + mid);
                if (row < 0) row = 0; if (row >= side) row = side - 1;
                if (col < 0) col = 0; if (col >= side) col = side - 1;
                double cn = (row - (side - 1) / 2.0) * pitch, ce = (col - (side - 1) / 2.0) * pitch;
                double m = pitch / 2.0 - (fabs(dal - cn) > fabs(daz - ce) ? fabs(dal - cn) : fabs(daz - ce));
                if (m < margin_min) continue;
                cell[n] = row * side + col;
                idx[n] = j;
                n++;
            }
            memset(cells, 0, sizeof(double) * (size_t)nt * 3 * F);
            for (int q = 0; q < n; q++) {
                const float *v = val + (size_t)idx[q] * nt * 3;
                int f = cell[q];
                for (int t = 0; t < nt; t++) {
                    for (int p = 0; p < 3; p++) {
                        double x = v[t * 3 + p];
                        double *cv = &cells[((size_t)t * 3 + p) * F + f];
                        if (x > *cv) *cv = x;
                    }
                }
            }
            double best = -1.0; int bt = 0, bp = 0; double btot = 0.0;
            for (int t = 0; t < nt; t++) {
                for (int p = 0; p < 3; p++) {
                    const double *cc = cells + ((size_t)t * 3 + p) * F;
                    double tot = 0.0;
                    for (int f = 0; f < F; f++) tot += cc[f];
                    double r = tot / tgrid[t];
                    if (r > best + 1e-12 || (fabs(r - best) <= 1e-12 && tot > btot)) { best = r; bt = t; bp = p; btot = tot; }
                }
            }
            out_rate[k] = best; out_t[k] = bt; out_p[k] = bp; out_total[k] = btot;
        }
    }
    free(sub); free(cell); free(idx); free(cells);
}
