# Compound time graph: independent official model (2026-10-04)

Established before reading portfolio/research code. Sources: official runner, scorer,
fiber map, participant guide, initialize payload construction; only L1/L2 public
catalog/calendar/scoring/instrument configuration inspected.

State at a public decision is (integer UTC t, best score B_i, max raw factor M_i,
valid action history, active request within-window factor maxima R_ri, weather and
offset belief). B and M are independent maxima. Repeated exposure is a replacement,
never a sum. A compound action is 2–3 complete observe actions, each with its own
start-dependent field, common program, duration and unique fiber assignments.

For field a starting at t with duration d, official geometry fixes hits at t;
telescope sidereal tracking does not freeze target altitude, airmass, lunar or event
coverage. Every assigned target needs min_altitude([t,t+d]) >= limit. The end is
clipped at the current night boundary. q_exp integrates <=120s pieces, slot and event
boundaries. q_band excludes efficiency and directional event multipliers. Thus one
field can contain several true bands. g_i=min(f_i*d*q_exp/(f0*t0),1),
c_i=w_i*g_i*program_multiplier. State transition is B_i'=max(B_i,c_i),
M_i'=max(M_i,g_i); request maxima update only when the exposure is wholly within
the published request window.

Terminal exact objective on any finite public horizon: sum B_i - required penalty
- U(1-Jain(completed/total in RA bands)) + completed active request rewards +
report settlement. Edge science gain is sum max(c_i-B_i,0); required gain is a
threshold crossing, Jain is recomputed jointly, and request reward is a gate on
minimum_completed. Summing stand-alone field gains is wrong when fields overlap.
Unknown future requests never enter planning. Rank utility, if used, is a separate
public tournament-belief utility E[F(S)] and must not be presented as official score.
Loss risk requires scenario-wise raw ledger validity (and fallback order statistics),
not scaling every score by a common survival probability.

Time graph nodes have continuous physical geometry but integer action seconds.
A node at t joins t+d for d in allowed duration set; add wait edges to public slot,
request and night boundaries. Edge choice includes field, program and complete
assignment. State-dependent edge weights mean a scalar longest-path DP is invalid;
a beam can retain sparse ledger deltas and completed gate masks. Dominance is safe
only for same t and same belief with >= B, >= M, >= each request factor and compatible
loss histories; otherwise an apparently lower-score state may retain better geometry
or protection from action-window loss. The first committed action is followed by
public feedback and replanning; the compound need not be executed open-loop.

Within an already sampled current slot, a short 900s horizon can use a causally
calibrated slot belief. Future slot weather remains a declared public belief with
multiple scenarios; exact truth belongs only to the final scorer. Duration candidates
include min/max/horizon, each target's best-score replacement crossing, required/
request threshold, saturation, and public boundary limits. Crossings must be solved
with time-varying q, not assuming factor proportional to duration. Refining around
crossings and duration-pair exchange roots can reduce integer search.

Greedy max marginal score/time has no optimality guarantee: saturation differs by
flux, existing B creates zero-gain prefixes, requests create complementarity, assigning
one fiber now changes its later alternatives, and later start changes grid orientation
and full-interval altitude feasibility. A short high-rate field can consume the only
start window for a larger joint schedule. This is a mechanism claim, not evidence of
an actual gain on a strong base.

Predeclared microvalidation domain: for each L1/L2 strong native release, replay the
public source prefix and choose the first decision among first 200 observe actions
that is an observe, is after prior same-slot feedback, and has >=600s until current
slot end. Candidate search is bounded by that slot end and 2–3 complete fields;
selection uses only public catalog, public messages and causal prefix feedback.
No selection based on candidate truth scores or the future base actions. Exact
candidate adjudication may load official scenario truth only after search is frozen.

## Static-quality reduction and its limits

For two fixed fields/assignments and fixed bands in a known static slot, set
alpha_ij=w_i*m_ij*k_ij. Under d2=H-d1 each uncapped contribution is affine in d1.
The joint target science term is max(B_i, min(alpha_i1*d1,w_i*m_i1),
min(alpha_i2*(H-d1),w_i*m_i2)). A repeated target's two exposure contributions
must therefore be maxed, not added. The crossing of the two unsaturated alternatives
is d1=alpha_i2*H/(alpha_i1+alpha_i2); it can be an additional breakpoint beyond
saturation, replacement and gate roots. Between all such breakpoints, science is
piecewise affine and raw completion/gate counts are constant, so Jain and request
rewards are constant and a fixed-assignment interval optimum is at an endpoint.
Full fiber reassignment adds upper-envelope intersections and multiple completion
states. This reduction is useful for candidate generation but does not justify the
probe's limited root set as globally exact. Public time-varying airmass/lunar and
program thresholds further require actual integration/root refinement.

If two exposures have identical field/program/assignment under genuinely constant
geometry/quality, merging them dominates their separate best-only contributions,
provided all window/altitude bounds still hold and loss/rank semantics are irrelevant.
This does not apply to two exposures allocating the same cell to different targets:
merging would destroy one target's slot. Unrestricted greedy can profit from exactly
that multiplexing, with no slew/configuration overhead in the official runner.
Consequently a fixed two-action search can lose to a strong greedy path with three
or five actions even after solving its duration shares much more accurately.

## Actual outcome and scope

The two predeclared prefixes contain 16/13 valid observed target rows, with every
scoring/hit field exactly reproduced from strong source; row-ID order differs only
with assignment-key insertion order. The next natural release action matches both
source actions exactly. Double-field conditional comparison gives positive official
short-domain differences, but actual source multi-field control beats the selected
compound by 53.351853 on L1 and 122.192665 on L2. A bounded L2 three-field public
rollout/exchange also loses by 1.459190. These are true short-domain negative labels,
not causal continuation/season labels. No full causal replan, GPU job or remote CPU
job started. The fixed action-count family is stopped; variable action-count DAG must
retain the public greedy path before any future production claim.
