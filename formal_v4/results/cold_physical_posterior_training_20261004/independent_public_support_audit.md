# Independent public support audit

This audit reads only frozen cal/val features, the fitted model and the independent synthetic prototype bank. It does not open test data, reconstruct worlds or modify the model.

For each path, sector center maps to the same eight-point compass direction as the official publication. Terrain support requires the entire deduplicated permanent terrain direction set to equal the opening bulletin's set carried in the query tail. Incompatible posterior mass is the sum of probabilities of paths violating that condition.

The reviewed score operator uses C = transparency × sky_quality / (seeing × q0), B = mean(O × C × H), and Q = mean(O × C × E × directional attenuation × H), followed by weight × min(1, flux × duration × Q / (f0 × T0)) × program multiplier. Band and science use their distinct official integration meshes; only factor is capped.

cal: 1297/2079 queries (62.39%) have no terrain-compatible class. Incompatible terrain mass quantiles at 0/50/90/99/100%: [0.05636936385040835, 0.9999999999999999, 1.0, 1.0000000000000002, 1.0000000000000004].

Current non-ALL weather/rocket notice sets: 37/2079 queries have no matching class; joint terrain/current-directional support: 1362/2079 have no matching class.

Same-timestamp report: 31 queries, maximum unrepaired current-fault probability 0.0; finite probabilities True.

Reference ALL rain/storm closure: 70 queries; open-slot posterior mass quantiles at 0/50/90/100%: [0.03911664731358655, 0.22553581526198513, 0.6631214196538587, 0.9644344818416011].

val: 1419/2067 queries (68.65%) have no terrain-compatible class. Incompatible terrain mass quantiles at 0/50/90/99/100%: [0.04853907354378478, 0.9999999999999999, 1.0, 1.0000000000000002, 1.0000000000000007].

Current non-ALL weather/rocket notice sets: 44/2067 queries have no matching class; joint terrain/current-directional support: 1451/2067 have no matching class.

Same-timestamp report: 19 queries, maximum unrepaired current-fault probability 0.0; finite probabilities True.

Reference ALL rain/storm closure: 69 queries; open-slot posterior mass quantiles at 0/50/90/100%: [0.09537729601123382, 0.3583326543904607, 0.6728162993091228, 0.9250873718828213].

The classifier has an exact healthy mask after a same-timestamp true or false report. It has no equivalent public-notice support filter. With an empty compatible dictionary, adding a hard mask alone would leave zero probability mass. These results qualify the output as an empirical physical-path classifier with incomplete conditional support, not a posterior satisfying all public evidence.

The non-ALL notice equality assumes the slot-aligned official event generation used by this experiment. The ALL rain/storm closure check depends on the frozen reference force_close settings and is not a universal rule for arbitrary task cards. The bank does not retain ALL weather-event descriptors, so other current ALL weather notices cannot be audited by event-set equality.

Source review found no actual future truth entering PublicHistory or common candidate assignment. Future host paths are used for labels/projection/realized value, while prototype quadrature is grouped by each path's own event boundaries. The five-slot operator already has 1743 official checks with maximum error 8.881784197001252e-16; this numerical gate does not establish conditional-support correctness. Repair divides only repaired fault multipliers and preserves quake/jitter, but immediate-post-report rows are excluded from the evaluation regret subset (evaluate.py:79).

A small candidate-geometry limitation remains: field 0 retains source assignments without filtering known zero-offset nominal misses (evaluate.py:19). The frozen cache has 2 such target misses among 13404 L1 candidates and 2 among 14900 L2 candidates. Predicted path scores assume those assignments hit; actual offset is applied only to realized value, as declared. Reviewed sources match SOURCE_LOCK; its documented operator amendment explains the initial SAMPLING_LOCK hash difference.

Reproduction: run `independent_public_support_audit.py` with NumPy from this directory. Exact input/source/model/bank hashes and all statistics are in `independent_public_support_audit.json`. No test results enter either artifact.
