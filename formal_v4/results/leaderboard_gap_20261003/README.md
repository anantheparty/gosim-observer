# Current public leaderboard gap

Normal logged-in leaderboard UI read on 2026-10-03 11:51–11:53 UTC.
The UI says each card is drawn from each team's best complete mean-score batch.
Only public aggregate fields were read.

| Card | CCB displayed total | Our latest cache total | CCB science | Our science |
|---|---:|---:|---:|---:|
| alpha | 7937.94 | 7248.868252 | 7788.10 | 7149.12 |
| beta | 7537.54 | 6517.864140 | 7487.61 | 6768.10 |
| gamma | 7435.37 | 6750.550861 | 7235.66 | 6650.83 |
| delta | 7411.98 | 6423.086757 | 7263.27 | 6523.83 |

Their displayed totals average approximately **7580.7075**, against our measured
**6735.09250250**. The gap is approximately **845.615**; science accounts for about
670.69, required penalties 150, requests 25, report 0. Rounded component arithmetic
may differ from the displayed total by 0.01. Alpha/beta of our batch timed out.

CCB observes fewer distinct targets in every card but has higher scientific sum.
This is evidence that target count alone is not the goal. It does not identify
CCB's algorithm or prove exactly which algorithmic weakness causes our gap.

Our alpha optimistic LP bound 7373.168525333 is for one restricted column pool
and conditional coefficient model. It is not a global alpha upper bound; a
competitor's public feasible 7937.94 cannot be excluded by that finite-model
certificate. Further work must enlarge the model's useful schedules and consider
season allocation/quality, not infer global near-optimality from current-pool
MIP gap 0 or from repeated equal local optima.

Source: https://create.gosim.org/survey26/platform/leaderboard .
