# Joint compensation research — READY

## Result

The incumbent remains **7289.494481** (official historical Phase α result). Net conditional gain is **0**, selected new column indices are **[]**, and no new official score was produced.

This master uses the latest historical Phase α incumbent, not the older cloud_cd2 α7094.664204 baseline. Its reconstructed conservative score is 7289.494439125726, differing by 0.000041874274 from the official rounded exposure coefficients. The history/report/repair interpretation and quality conditions are frozen; observe columns can exchange normally. This is not comparable as an incremental gain on the latest full portfolio without a new replay.

## Mathematical experiment

A required target leads to a completing exposure, which overlaps incumbent exposures and creates a set of displaced mandatory targets. These target–exposure debt sets form an alternating hypergraph. We generated completing columns for the three missing targets, solved the joint time DAG/science winner/mandatory/REQ master, collected 18 displaced targets, and generated completing compensation columns at other supported times. The master then optimized all 1714 columns together.

The initial 1514 columns include the fresh 1376-column master, 120 earlier GPU columns, and six forced completing columns for each of V4T001295, V4T005424 and V4T008897. This round adds 120 GPU-refined columns plus 80 forced compensation columns. The final pool has 6, 10 and 10 completing forced witnesses for the three missing targets, respectively, and at least four for each of the 18 blockers. No candidate from an interrupted CPU attempt was reused.

The finite LP objective with constants remains 7373.168525333 (change 7.28e−12). The final integer master has 26327 variables and 34236 rows, reports status 0 and gap 3.59e−14, and supplies no improving schedule. Jain uniformity is recomputed after solving and is outside the MIP objective, so the MIP gap certifies only its finite surrogate objective.

The same three previously selected forced branches were rechecked in this expanded pool: deficits improve from −374.629358 to −239.747655 (1295), −378.270326 to −243.388473 (5424), and −507.150398 to −460.209959 (8897). Compensation can restore some debts, but these branches remain worse. See forced_branch_after_compensation.json for actual selected compensation columns and settlements.

## Physical execution and checks

The owned RTX PRO 6000 executed 8 cases, 61 durations, 32768 centers and 3 programs: **5996544 finite columns**. Actual GPU pricing took 1.171547 s; the full device phase took 1.474681 s. Independent CPU pricing checked 1845 columns with maximum error 2.13e−14. The 0.03-degree fiber margin is included by shrinking pricing glass by 0.06 degrees while retaining the pitch. CPU refinement uses the official FiberGrid and whole-exposure visibility with the original glass and strict margin.

CPU official refinement took 46.672742 s, with 2754 checks; 120 columns were retained. Forced compensation took 3.598992 s, performed 853 checks and retained 80 columns. The final master stage took 2.722997 s. The optional three forced-branch diagnostics took 95.662719 s end to end, including reconstruction, despite subsecond individual MIP solves.

Fresh optimal-face dual stabilization and subsequent original LP KKT gates are recorded in fresh_repricing_dual_proof.json and result.json. Final LP stationarity residual is 2.15e−13 and dual/primal objective residual is 6.55e−11. All NPZ pricing values are finite and nonnegative. Remote hashes match the corresponding prepared files.

The main READY record was 28 min 35 s after task start, exceeding the intended approximately 15 minutes. This includes preparation/transfer/tool waits and an aborted CPU attempt: repeated access to a compressed NPZ field decompressed the full tensor inside each fiber loop. That owned process was interrupted after an observed elapsed lower bound of 311 s; materializing the same arrays once corrected the data-loading overhead. runtime.json reports the measured timings and explicitly does not invent an exact aborted runtime.

## Scope and provenance

This is one bounded blocking-set expansion using finite existing nodes, zero pointing offsets, reference-direction quality bounds and a narrow supported public conditional profile. It does not cover all exposure times, pointings, repairs or weather realizations. The new feasible CCB leaderboard α7937.94 reported by the parent is already above this 7373 finite LP value, demonstrating that this pool/conditional model cannot serve as a global upper bound. No global-optimum or competition-score claim follows from this experiment.

The physical gpu_top_physical.json is preserved unmodified. gpu_top.json is an explicitly derived first-25-per-case shortlist for bounded CPU refinement and records its raw source SHA. The prepared device driver is frozen separately from the current CPU research source; manifest.json records both hashes. Current source: formal_v4/research/joint_compensation.py, SHA256 7f0aa07ad3814444d4acb7e0b9fecbb716c513707985a30293a48d70b80f3cc7. The manifest covers all evidence artifacts, including the forced-branch diagnostic and this README.

Production code, submission ZIP, services, APIs, power settings and Git index were not changed. The GPU is free. This round is archived with no improvement; no additional enumeration is pending.
