"""One-slot, constant-site-state proof kernel; no fitted or private teacher.

This is deliberately a restricted mechanical prototype, not a production actor.
C = transparency*sky/(seeing*q0), Z=C*efficiency. An observed score bin
intersects the continuous (C,Z) prior. Bands are cells in C; each cell leaves
one interval in Z, including an unbounded upper endpoint for saturation.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class PublicHit:
    score: float
    weight: float
    flux: float
    seconds: float
    geometric_h: float
    declared: str


@dataclass(frozen=True)
class Cell:
    c_lo: float
    c_hi: float
    z_lo: float
    z_hi: float
    raw_mass: float


class ContinuousPosterior:
    """Exact cell integrals for an explicit toy Uniform(C) x Uniform(E) prior.

    The C/E ranges are assumptions of this toy prior, never protocol constants.
    No latent C, Z, factor or band is accepted as a public observation.
    """
    def __init__(self, scoring, hits, c_range=(.02, 1.8),
                 e_range=(.1, 1.), closed_probability=.08):
        self.scoring = scoring
        self.hits = tuple(hits)
        self.c_lo, self.c_hi = c_range
        self.e_lo, self.e_hi = e_range
        if not (0 < self.c_lo < self.c_hi and 0 < self.e_lo < self.e_hi):
            raise ValueError("invalid toy prior")
        if not 0 <= closed_probability < 1:
            raise ValueError("invalid closure mass")
        self.open_density = (1-closed_probability) / (
            (self.c_hi-self.c_lo)*(self.e_hi-self.e_lo))
        self.closed_mass = closed_probability if all(
            self.score_interval(h.score)[0] <= 0 <= self.score_interval(h.score)[1]
            for h in self.hits) else 0.
        cuts = {self.c_lo, self.c_hi}
        for h in self.hits:
            self.validate(h)
            cuts.update(self.band_cuts(h.geometric_h))
        cuts = sorted(x for x in cuts if self.c_lo <= x <= self.c_hi)
        self.cells = []
        for a, b in zip(cuts, cuts[1:]):
            mid = (a+b)/2
            zlo, zhi = 0., math.inf
            possible = True
            for h in self.hits:
                m = self.multiplier(h.declared, self.band(mid*h.geometric_h))
                scale = self.scale(h.flux, h.seconds, h.geometric_h)
                wm = h.weight*m
                lo, hi = self.score_interval(h.score)
                if lo > wm or hi < 0:
                    possible = False
                    break
                zlo = max(zlo, lo/(wm*scale))
                if hi < wm:
                    zhi = min(zhi, hi/(wm*scale))
            if possible and zhi > zlo:
                mass = self.integrate(a, b, zlo, zhi)
                if mass > 0:
                    self.cells.append(Cell(a, b, zlo, zhi, mass))
        self.normalizer = self.closed_mass + self.open_density*sum(
            c.raw_mass for c in self.cells)
        if self.normalizer <= 0:
            raise ValueError("zero likelihood in this restricted prior/scope")

    @staticmethod
    def validate(h):
        if min(h.weight, h.flux, h.seconds, h.geometric_h) <= 0:
            raise ValueError("positive public scaling required")

    @staticmethod
    def score_interval(score):
        # Conservative half-bin endpoints; floating ties have zero continuous mass.
        return max(0., float(score)-.500001e-6), float(score)+.500001e-6

    def scale(self, flux, seconds, h):
        return flux*seconds*h / (
            self.scoring['flux_zero_point']*
            self.scoring['exposure_zero_point_seconds'])

    def band_cuts(self, h):
        bands = self.scoring['program']['bands']
        return (float(bands['BRIGHT'])/h, float(bands['DARK'])/h)

    def band(self, band_quality):
        bands = self.scoring['program']['bands']
        return ('DARK' if band_quality >= bands['DARK'] else
                'BRIGHT' if band_quality >= bands['BRIGHT'] else 'BACKUP')

    def multiplier(self, declared, actual):
        p = self.scoring['program']
        return float(p['multipliers'][declared] if declared == actual
                     else p['mismatch_multiplier'])

    @staticmethod
    def gain_primitive(z, wm, scale, best):
        if best >= wm:
            return 0.
        slope = wm*scale
        start, cap = best/slope, 1/scale
        if z <= start:
            return 0.
        if z < cap:
            return .5*slope*z*z-best*z+.5*best*best/slope
        return (wm-best)*z-(wm*wm-best*best)/(2*slope)

    @classmethod
    def primitive_coefficients(cls, p, q, c_mid, wm, scale, best):
        """Coefficients of primitive(p*C+q), on a fixed regime.

        Endpoints here are either p*C or constants q, never both nonzero.
        Returns coefficients in C^2, C, 1.
        """
        if p == 0:
            return (0., 0., cls.gain_primitive(q, wm, scale, best))
        if best >= wm:
            return (0., 0., 0.)
        z, slope = p*c_mid, wm*scale
        if z <= best/slope:
            return (0., 0., 0.)
        if z < 1/scale:
            return (.5*slope*p*p, -best*p, .5*best*best/slope)
        return (0., (wm-best)*p, -(wm*wm-best*best)/(2*slope))

    def integrate(self, ca, cb, zlo, zhi, gain=None):
        """Analytic integral with density 1/C over the clipped Z interval.

        gain=None integrates probability. gain=(weight*multiplier,scale,best)
        integrates the positive part. Every break of an endpoint or primitive
        is included before applying polynomial/log antiderivatives.
        """
        cuts = {ca, cb}
        zcuts = [zlo, zhi]
        if gain is not None:
            wm, scale, best = gain
            if best >= wm:
                return 0.
            zcuts += [best/(wm*scale), 1/scale]
        for z in zcuts:
            if math.isfinite(z):
                for e in (self.e_lo, self.e_hi):
                    c = z/e
                    if ca < c < cb:
                        cuts.add(c)
        total = 0.
        seq = sorted(cuts)
        for a, b in zip(seq, seq[1:]):
            mid = (a+b)/2
            low = ((0., zlo) if zlo >= self.e_lo*mid else (self.e_lo, 0.))
            high = ((0., zhi) if zhi <= self.e_hi*mid else (self.e_hi, 0.))
            if low[0]*mid+low[1] >= high[0]*mid+high[1]:
                continue
            if gain is None:
                a2 = 0.
                a1 = high[0]-low[0]
                a0 = high[1]-low[1]
            else:
                # Integrate linear/plateau pieces using differences factored by
                # interval width. Subtracting two almost equal primitives loses
                # precision at six-decimal observation widths.
                slope = wm*scale
                start, cap = best/slope, 1/scale
                lo_at = low[0]*mid+low[1]
                hi_at = high[0]*mid+high[1]
                la = low if lo_at >= start else (0., start)
                lb = high if hi_at <= cap else (0., cap)
                a2 = a1 = a0 = 0.
                if la[0]*mid+la[1] < lb[0]*mid+lb[1]:
                    dp, dq = lb[0]-la[0], lb[1]-la[1]
                    a2 += .5*slope*dp*(lb[0]+la[0])
                    a1 += slope*(lb[0]*lb[1]-la[0]*la[1])-best*dp
                    a0 += dq*(.5*slope*(lb[1]+la[1])-best)
                sa = low if lo_at >= cap else (0., cap)
                if sa[0]*mid+sa[1] < hi_at:
                    a1 += (wm-best)*(high[0]-sa[0])
                    a0 += (wm-best)*(high[1]-sa[1])
            delta = b-a
            total += a2*delta*(b+a)/2 + a1*delta + a0*math.log1p(delta/a)
        return max(0., total)

    def expected_gain(self, weight, flux, seconds, h, declared, best):
        if min(weight, flux, seconds, h) <= 0 or best < 0:
            raise ValueError("invalid query scaling")
        total = 0.
        scale = self.scale(flux, seconds, h)
        query_cuts = self.band_cuts(h)
        for cell in self.cells:
            cuts = sorted({cell.c_lo, cell.c_hi, *(x for x in query_cuts
                           if cell.c_lo < x < cell.c_hi)})
            for a, b in zip(cuts, cuts[1:]):
                m = self.multiplier(declared, self.band((a+b)/2*h))
                total += self.integrate(a, b, cell.z_lo, cell.z_hi,
                                        (weight*m, scale, best))
        # Closed C=Z=0 has zero positive gain for nonnegative best.
        return self.open_density*total/self.normalizer

    def contains(self, c, efficiency):
        z = c*efficiency
        return any(cell.c_lo <= c <= cell.c_hi and
                   cell.z_lo <= z <= cell.z_hi and
                   self.e_lo*c <= z <= self.e_hi*c for cell in self.cells)

    def public_receipt(self):
        return {'continuous_cells': len(self.cells),
                'likelihood_probability': self.normalizer,
                'posterior_closed_probability': self.closed_mass/self.normalizer,
                'cells': [dict(c_lo=c.c_lo, c_hi=c.c_hi, z_lo=c.z_lo,
                               z_hi=c.z_hi if math.isfinite(c.z_hi) else None,
                               posterior_mass=self.open_density*c.raw_mass/self.normalizer)
                          for c in self.cells]}
