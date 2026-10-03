// Same fixed-plane weighted arrangement sweep as candidate_geometry_sweep.py.
// Build without fast-math or FP contraction. The ABI and dependencies are C-only.
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <limits.h>

#if defined(__GNUC__)
#define EXPORT __attribute__((visibility("default")))
#else
#define EXPORT
#endif

namespace {
struct Event { int64_t boundary, target, row, add, ordinal; };
int compare_double(const void* a, const void* b) {
    const double x = *static_cast<const double*>(a), y = *static_cast<const double*>(b);
    return (x > y) - (x < y);
}
int compare_event(const void* a, const void* b) {
    const Event& x = *static_cast<const Event*>(a);
    const Event& y = *static_cast<const Event*>(b);
    if (x.boundary != y.boundary) return (x.boundary > y.boundary) ? 1 : -1;
    return (x.ordinal > y.ordinal) - (x.ordinal < y.ordinal);
}
size_t unique_sorted(double* a, size_t count) {
    qsort(a, count, sizeof(double), compare_double);
    size_t unique = 0;
    for (size_t i = 0; i < count; ++i)
        if (!unique || a[i] != a[unique - 1]) a[unique++] = a[i];
    return unique;
}
size_t search_left(const double* a, size_t count, double key) {
    size_t lo = 0, hi = count;
    while (lo < hi) {
        const size_t middle = lo + (hi - lo) / 2;
        if (a[middle] < key) lo = middle + 1; else hi = middle;
    }
    return lo;
}
template<class T> T* allocate(size_t count) {
    if (count > SIZE_MAX / sizeof(T)) return nullptr;
    return static_cast<T*>(malloc((count ? count : 1) * sizeof(T)));
}
}

extern "C" EXPORT int geometry_native_abi_version() { return 1; }

// Return 0 on success; 1 invalid scalar/shape, 2 allocation failure, 3 overflow.
// Buffers are row-major doubles. Inputs must be finite and non-overlapping.
extern "C" EXPORT int geometry_weighted_sweep(
    const double* x, const double* y, const double* values, int64_t n64, int64_t q64,
    double pitch, double glass, int64_t side64, double radius, int64_t keep64,
    double* bestx, double* besty, double* bestv, int64_t* visited) {
    if (!x || !y || !values || !bestx || !besty || !bestv || !visited ||
        n64 < 0 || q64 < 0 || side64 < 1 || keep64 < 1 ||
        !(pitch > 0.) || !(glass > .016) || !(glass <= pitch) || !(radius > 0.) ||
        !std::isfinite(pitch) || !std::isfinite(glass) || !std::isfinite(radius)) return 1;
    const size_t n = static_cast<size_t>(n64), qs = static_cast<size_t>(q64);
    const size_t side = static_cast<size_t>(side64), keep = static_cast<size_t>(keep64);
    if (side > SIZE_MAX / side || n > (SIZE_MAX - 2) / 2 / side ||
        qs > SIZE_MAX / keep || qs > SIZE_MAX / (side * side) ||
        (n && qs > SIZE_MAX / n)) return 3;
    const size_t capacity = 2 + 2 * n * side, nf = side * side, cells = qs * nf;
    double* xs = allocate<double>(capacity);
    double* ys = allocate<double>(capacity);
    Event* events = allocate<Event>(capacity - 2);
    int64_t* col = allocate<int64_t>(n);
    int64_t* row = allocate<int64_t>(n);
    double* cell = allocate<double>(cells);
    int64_t* winner = allocate<int64_t>(cells);
    uint8_t* dirty = allocate<uint8_t>(cells);
    if (!xs || !ys || !events || !col || !row || !cell || !winner || !dirty) {
        free(xs); free(ys); free(events); free(col); free(row); free(cell); free(winner); free(dirty);
        return 2;
    }
    const double half = glass / 2. - .008;
    xs[0] = ys[0] = -radius; xs[1] = ys[1] = radius;
    size_t nx = 2, ny = 2;
    for (size_t i = 0; i < n; ++i) {
        for (size_t r = 0; r < side; ++r) {
            const double c = (static_cast<double>(r) - (side64 - 1) / 2.) * pitch;
            for (int sign = -1; sign <= 1; sign += 2) {
                const double a = x[i] - c + sign * half, b = y[i] - c + sign * half;
                if (-radius < a && a < radius) xs[nx++] = a;
                if (-radius < b && b < radius) ys[ny++] = b;
            }
        }
    }
    nx = unique_sorted(xs, nx); ny = unique_sorted(ys, ny);
    if ((nx - 1) > static_cast<size_t>(INT64_MAX) / (ny - 1)) {
        free(xs); free(ys); free(events); free(col); free(row); free(cell); free(winner); free(dirty);
        return 3;
    }
    size_t ne = 0;
    for (size_t i = 0; i < n; ++i) {
        for (size_t r = 0; r < side; ++r) {
            const double c = (static_cast<double>(r) - (side64 - 1) / 2.) * pitch;
            const double left = y[i] - c - half, right = y[i] - c + half;
            for (int add = 1; add >= 0; --add) {
                const double e = add ? left : right;
                if (ys[0] < e && e < ys[ny - 1]) {
                    events[ne] = {static_cast<int64_t>(search_left(ys, ny, e)),
                        static_cast<int64_t>(i), static_cast<int64_t>(r), add, static_cast<int64_t>(ne)};
                    ++ne;
                }
            }
        }
    }
    qsort(events, ne, sizeof(Event), compare_event);
    for (size_t i = 0; i < qs * keep; ++i) { bestx[i] = besty[i] = 0.; bestv[i] = -1e100; }
    *visited = 0;
    const double first_y = (ys[1] + ys[0]) / 2.;
    for (size_t xi = 0; xi + 1 < nx; ++xi) {
        const double xx = (xs[xi + 1] + xs[xi]) / 2.;
        for (size_t i = 0; i < n; ++i) {
            col[i] = row[i] = -1;
            const double dc = x[i] - xx;
            const int64_t c = static_cast<int64_t>(std::floor(dc / pitch + side64 / 2.));
            if (0 <= c && c < side64 && std::fabs(dc - (c - (side64 - 1) / 2.) * pitch) < half) col[i] = c;
            const double dr = y[i] - first_y;
            const int64_t r = static_cast<int64_t>(std::floor(dr / pitch + side64 / 2.));
            if (0 <= r && r < side64 && std::fabs(dr - (r - (side64 - 1) / 2.) * pitch) < half) row[i] = r;
        }
        memset(cell, 0, cells * sizeof(double));
        for (size_t i = 0; i < cells; ++i) winner[i] = -1;
        for (size_t i = 0; i < n; ++i) {
            if (col[i] >= 0 && row[i] >= 0) {
                const size_t f = static_cast<size_t>(row[i]) * side + static_cast<size_t>(col[i]);
                for (size_t q = 0; q < qs; ++q) {
                    const size_t at = q * nf + f;
                    if (values[q * n + i] > cell[at]) { cell[at] = values[q * n + i]; winner[at] = i; }
                }
            }
        }
        size_t cursor = 0;
        for (size_t yi = 0; yi + 1 < ny; ++yi) {
            if (yi > 0) {
                memset(dirty, 0, cells);
                while (cursor < ne && events[cursor].boundary <= static_cast<int64_t>(yi)) {
                    const Event& event = events[cursor]; const size_t i = event.target;
                    if (col[i] >= 0 && row[i] >= 0) {
                        const size_t f = static_cast<size_t>(row[i]) * side + static_cast<size_t>(col[i]);
                        for (size_t q = 0; q < qs; ++q)
                            if (winner[q * nf + f] == static_cast<int64_t>(i)) dirty[q * nf + f] = 1;
                    }
                    row[i] = event.add ? event.row : -1;
                    ++cursor;
                }
                for (size_t q = 0; q < qs; ++q) {
                    for (size_t f = 0; f < nf; ++f) {
                        const size_t at = q * nf + f;
                        if (dirty[at]) {
                            cell[at] = 0.; winner[at] = -1;
                            for (size_t i = 0; i < n; ++i) {
                                if (col[i] >= 0 && row[i] >= 0 &&
                                    static_cast<size_t>(row[i]) * side + static_cast<size_t>(col[i]) == f && values[q * n + i] > cell[at]) {
                                    cell[at] = values[q * n + i]; winner[at] = i;
                                }
                            }
                        }
                    }
                }
                size_t j = cursor;
                while (j > 0 && events[j - 1].boundary == static_cast<int64_t>(yi)) {
                    const size_t i = events[--j].target;
                    if (col[i] >= 0 && row[i] >= 0) {
                        const size_t f = static_cast<size_t>(row[i]) * side + static_cast<size_t>(col[i]);
                        for (size_t q = 0; q < qs; ++q) {
                            const size_t at = q * nf + f;
                            if (values[q * n + i] > cell[at]) { cell[at] = values[q * n + i]; winner[at] = i; }
                        }
                    }
                }
            }
            const double yy = (ys[yi + 1] + ys[yi]) / 2.; ++*visited;
            for (size_t q = 0; q < qs; ++q) {
                double v = 0.;
                for (size_t f = 0; f < nf; ++f) v += cell[q * nf + f];
                const size_t at = q * keep;
                if (v > bestv[at + keep - 1] + 1e-14) {
                    int64_t near = -1;
                    for (size_t j = 0; j < keep; ++j) {
                        const double dx = std::fabs(xx - bestx[at + j]), dy = std::fabs(yy - besty[at + j]);
                        if ((dx > dy ? dx : dy) < .04 * pitch) near = j;
                    }
                    if (near >= 0 && v <= bestv[at + near] + 1e-14) continue;
                    size_t j = near >= 0 ? static_cast<size_t>(near) : keep - 1;
                    bestv[at + j] = v; bestx[at + j] = xx; besty[at + j] = yy;
                    while (j > 0 && bestv[at + j] > bestv[at + j - 1]) {
                        const double tv = bestv[at + j - 1], tx = bestx[at + j - 1], ty = besty[at + j - 1];
                        bestv[at + j - 1] = bestv[at + j]; bestx[at + j - 1] = bestx[at + j]; besty[at + j - 1] = besty[at + j];
                        bestv[at + j] = tv; bestx[at + j] = tx; besty[at + j] = ty; --j;
                    }
                }
            }
        }
    }
    free(xs); free(ys); free(events); free(col); free(row); free(cell); free(winner); free(dirty);
    return 0;
}
