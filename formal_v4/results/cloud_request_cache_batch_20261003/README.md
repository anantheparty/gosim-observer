# Request cache: official four-card batch

| Card | Total | Termination | Accounted seconds |
|---|---:|---|---:|
| alpha | 7248.868252 | global_wallclock_expired | 900.000 |
| beta | 6517.864140 | global_wallclock_expired | 899.991 |
| gamma | 6750.550861 | survey_complete | 883.744 |
| delta | 6423.086757 | survey_complete | 587.273 |

The measured mean is **6735.09250250**, +20.10858275 over the preceding
Verified Portfolio batch. Alpha and beta remain incomplete; these are retained
platform scores, not a claim that all surveys completed. Six practice evaluations
remain today. No remarks or design materials were supplied.

All four individual official downloads passed the published decisions/messages/
observations SHA checks and nested workflow-report equality. All initial remote
checks are explicitly disabled; completed-card summaries report zero calls.

Alpha retains the entire original Request 1056-action prefix and continues for
232 additional submitted actions. Beta retains its original 1209-action prefix
and continues for another 45. Their score gains therefore include additional
survey progress. Delta's actions, decisions, messages, observations and full
score_report are byte-for-byte equal to the original Request result. Its elapsed
wallclock differs, so that alone does not imply an algorithmic improvement.

Gamma first differs at action index 101. The cause has not been established.
This evaluation combines the exact cache and removal of failed optional remote
initialization, on another runtime allocation; it does not separately measure
an isolated causal cache speedup. Local strict cache gates and source snapshots
remain under request_exact_cache_20261003 and request_exact_cache_candidate_20261003.

The historical componentwise 6836.95278225 remains an arithmetic combination
of older card results, not a measured score from this package.
