Native fixed-plane geometry backend and isolated participant release

READY: all four native participant seasons and all four same-budget fixed24
CPUPhase controls completed the official protocol under 2 CPUs, 2 GiB and
900 seconds. Native wins every card and finishes faster. The candidate source
and ZIP remained unchanged during the complete-season gates.

Default release: /Users/kamico/Downloads/observer_geometry_native.zip
SHA256: f26a1a1296e2d71d6072a5729d8e51d4c68457e4fa9d301617a08f86ba766b9f
Size: 50,944 bytes; 20 files. Build twice produced the same SHA256.
Snapshot: formal_v4/runs/geometry_native_20261003/release

The release preserves the exact frozen policy, state, utility calculations,
spherical assignment repair, exact final evaluation, exposure breakpoints and
quotas used by the measured standalone geometry experiment. Only the Numba
import and weighted_sweep definition are removed by AST ranges and replaced
with the ctypes/native function. All remaining module AST is identical.
The separate entry patches policy.SpatialPlanner to CandidateGeometryPlanner.
Production source and the Git index are unchanged.

Build: python3 formal_v4/research/geometry_native_release.py
Optional union support: --mode union --out <separate.zip> --snapshot <separate-dir>
Union uses separately supplied current geometry/phase/union sources. The
standalone release defaults to the exact measured geometry source snapshot.

Deployment requirements: CPython with ctypes, numpy==2.2.6, Linux x86_64
(or the bundled Darwin arm64 test binary). There is no compiler, Numba,
C++ runtime, remote service, card data, research label, model, schedule or
credential in the package. Linux DT_NEEDED is libc.so.6 and libm.so.6, with
maximum required glibc symbol GLIBC_2.3.4. See provenance.json for build flags,
compiler versions, source hashes and official runtime evidence.

Verification: geometry_native_verify.py --mode verify
The original 24 exhaustive random cases, 19 tie/zero/negative/empty/strided
cases and all 672 frozen real sweeps (53,840,920 arrangement cells) pass.
Centers, values and visited counts match the Numba reference and frozen
exports at the uint64 bit level. Independent exhaustive maximum error is
1.7763568394002505e-15.

The Linux checks use literal saved float64 test inputs, because the final bit
of NumPy random uniform arithmetic differs between versions/platforms. They
pass in Python 3.12.15 / NumPy 2.2.6 / Debian glibc 2.41 under 2 CPUs and 2 GiB,
read-only rootfs, no network, no compiler and no Numba.

48 representative real sweeps, five end-to-end wrapper repetitions:
Linux constrained container: median 27.4 ms, p95 149.2 ms, max 184.4 ms;
first library load plus sweep 144.9 ms. Verification RSS is about 49 MiB.
Mac arm64: median 12.95 ms, p95 68.65 ms, max 87.94 ms; about 1.43x the
warm Numba speed when comparing aggregate representative sweep times.
Wrapper measurements include validation, conversion, output allocation,
ctypes and the complete native kernel, with no candidate pruning or tuning.

Full initial planner decisions on L1/L2/L3/L4 match exactly. Native warm
choose times are 258/133/204/210 ms locally; the complete unchanged planner
is measured, including utility and spherical/exact evaluation.

Fair complete Linux protocol comparison (score; accounted wall seconds):
Card   Native geometry          Fixed24 CPUPhase         Score gain
L1     6362.021539; 438.485      6289.992617; 532.189     +72.028922
L2     6823.661561; 522.120      6792.219245; 590.931     +31.442316
L3     6004.504542; 457.663      5914.829221; 519.706     +89.675321
L4     5974.281941; 433.629      5970.553373; 508.315     +3.728568
Means: native 6291.11739575; strong control 6241.898614; gain 49.21878175.
Both use identical frozen controller/config/shared sources, the same official
host engine/cards and pinned NumPy2.2.6 image, with one complete run per card.
See comparison.json/csv and the eight raw protocol gate folders.

Historical Mac callback traces/scores differ from these independent Linux
results. The first L4 fork is explained: at request94/observe89, the frozen
SpatialPlanner uses default np.argsort on a priority shortlist containing six
equal values 52.30702702702703. The same literal float64 inputs produce a
different tie order across the tested environments, changing the last two of
24 anchors: Mac indices7517/7581 versus Linux1579/5285. Scores, factor bounds,
feedback C/E and pointing calibration are identical at the fork. Mac Numba
and Mac native state/candidates/action are identical; the Linux replay matches
the recorded Linux actions. All79 host engine/card config/truth source files
match the local originals. See trace/L4/tie_order_proof.json and literal input.
Deterministic tie sorting is a possible later experiment. It is not applied to
this frozen candidate, and no further season tests are included in this round.

READY means protocol/resource compatibility and a measured gain over the
same-environment strong control on the four supplied practice cards. It does
not assert cross-platform historical trace identity or global optimality.

Full protocol harness: research/geometry_native_gate.py. The official trusted
local runner remains outside the participant container; only the release and
pinned NumPy dependencies are mounted inside. The 16 engine files match the
official kit ENGINE_MANIFEST.json (commit db4bddf3cc67fb5f0036d9fb2cf90b9e2b7e8f4a).
Native L1/L3 container PIDs and all four control PIDs were captured. Native
L2/L4 auto-removed before PID capture; their Docker event IDs are preserved,
and that metadata limitation is recorded without repeating the runs.

No cloud submission was performed. READY.json, artifact_manifest.json and
archive_inventory.json identify the retained release and supporting evidence.
