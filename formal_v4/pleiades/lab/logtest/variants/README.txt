Hidden-card log-format robustness corpus

Run from /home/shu/kamico/observer (Python standard library only):

  PYTHONDONTWRITEBYTECODE=1 python work/logtest/variants.py
  PYTHONDONTWRITEBYTECODE=1 python work/logtest/evalreader.py --json work/logtest/variants/eval_c31.json
  PYTHONDONTWRITEBYTECODE=1 python work/logtest/evalreader.py --reader work/pkgs/c32/guider_log.py:GuiderLog --by-card
  PYTHONDONTWRITEBYTECODE=1 python work/logtest/evalreader.py --variants original canonical clock_styles --cards A1

The last two examples require a GuiderLog-compatible reader. Constructor:
factory(utc_offset_hours=..., **reader_kwargs). Methods: read(text, issued_epoch),
due() and probes() returning records with numeric UTC epoch field t; flats is a
dict keyed by numeric (start, end) epochs. --reader-kwargs accepts JSON.
Readers in another .py file or importable module can be selected as path:Class
or module:Class. The evaluator itself makes no model/API/network calls.

Each variant directory contains A1/B1/C1/D1.log.txt and corresponding truth.json.
All logs retain the original 220 issued blocks, card offsets and event times.
There are 512 confirmed starts, 56 unresolved alternatives and 1593 flat windows.
The original, names_tone and canonical controls are checked against all five
oracle label sets after EACH block during generation. A mismatch aborts.
Other variants use the same extracted changes and same independent truth files.
The generator never obtains labels by parsing a rewritten stress-test log.

Variants:
  original           original log control
  names_tone         renamed staff, changed conversational filler
  canonical          semantic replay control using familiar syntax
  clock_styles       12-hour AM/PM, 21h30, 2130 hours, English/Japanese/Chinese
  timezone_dates     explicit fixed offsets, ISO/month-name/Chinese dates
  equipment_aliases  new device names and calibration names with stated rules
  status_rewrites    familiar dates; new withdrawal/gossip/revision/rain wording
  status_relative    status wording plus weekday dates and calibration references
  cipher_words       ROT13/Caesar +7/+19 with supplied keys and spelled-out times
  mixed              combined transformations
  engineering_table  Chinese task names; status, class, dates and clocks in columns
  bullet_workorders  Chinese task names; each work order spans several list lines

Large variants regenerate only schedule-state changes, omitting repeated event
restatements, while retaining original unrelated weather/terrain/chatter. Cipher
instructions are explicitly scoped to their original weather section; each new
encrypted sentence has its own key. Some original unresolved rain/relative
clauses are retained to preserve their actual conditional relationships.
The source_changes field supplies exact UTC times, full original source lines,
known correction/postponement relationships, and original rain anchors.
checkpoints contains cumulative labels available after each original block;
no later block's labels are used to render an earlier block.

Truth schema (all lists use ISO 8601 UTC strings ending in Z):
  faults_utc        confirmed c31 due() starts
  flats_utc         [start,end] pairs, half-open intervals
  alternatives_utc  unresolved c31 probes(), not verified physical fault times
  rumours_utc       unconfirmed, not actionable
  cancelled_utc     cancelled/corrected/postponed-away timestamps
Source, oracle and generated-log SHA-256 hashes support provenance. The evaluator
verifies the generated log against its truth file and checks checkpoint alignment.

Metrics:
  R/P               final confirmed-start recall/precision; one-to-one matching
                    within an inclusive 120 seconds by default (--tolerance)
  TP/FN/FP          confirmed starts; duplicate predictions cannot reuse a truth
  candFP            unique due/probe timestamps outside confirmed AND legitimate
                    alternative lists; a suspected false-report candidate count
  probes/bad        returned probes / unsupported probes
  flatIoU           seconds of intersection / seconds of union after merging
                    overlapping intervals; JSON also has duration precision/recall
  streamR           checkpoint-micro recall, so longer-lived records weigh more
  streamFP          distinct unsupported candidate times seen at any checkpoint

JSON includes per-card results, individual missed/extra timestamps, checkpoint
results, known-negative hits, alternatives promoted to due, and log/truth hashes.
Precision with no predictions is N/A. Empty/empty flat IoU is 1; no predicted
windows with nonempty truth gives IoU 0. Legitimate unresolved alternatives do
not count as candFP, but promoting them to confirmed due still reduces strict
confirmed-start precision (see alternatives_as_due for that distinction).

Limits: This is a synthetic format stress test, not a sample of actual hidden
cards, and the results do not predict hidden-card competition scores. Labels
are the supplied c31 schedule oracle, not simulator outcomes; notably c31 labels
some cross-day relative statements as alternatives even when prose sounds
official. The model adapter must respect that convention for like-for-like
comparison, or report such disagreements separately.

Current final results: eval_c31_summary.txt and eval_c31.json.
The later two structured variants have separate results in
eval_c31_structured_summary.txt and eval_c31_structured.json.
eval_c31_mvp.json is a historical early checkpoint; its clock_styles renderer
predates the canonical isolation changes and should not be used for final scores.

Offline world builder:
  python work/mkvariantworld.py BASE_WORLD VARIANT_DIR CARD DST
  python work/mkvariantworld.py work/worlds/FA1 work/logtest/variants/mixed A1 work/worlds/V_mixed_A1

DST must not already exist. The six delivered worlds are:
  work/worlds/V_mixed_A1                work/worlds/V_mixed_C1
  work/worlds/V_clock_styles_A1         work/worlds/V_clock_styles_C1
  work/worlds/V_status_rewrites_A1      work/worlds/V_status_rewrites_C1

The builder only materializes confirmed faults; alternatives stay absent.
V4GF fault events require the same patched engine_g used by mkguider.py for
the first-hour x0.3 / subsequent x0.005 behavior. Original baked fault efficiency
is restored before flat-window slot efficiency is multiplied by 0.005. Request
reasons preserve the entire log body including final newlines. Existing base
requests and non-fault events are kept. Each world includes variant_world.json
with hashes, season bounds, event/request counts and modified slot IDs.

The season ends at the last slot's actual end (duration_seconds), 45 minutes
earlier than mkguider.py's last timestamp + one hour on these base worlds. This
changes only the final event's end time; it does not remove any simulated slot.
For A1, generated weather truth exactly matches GA1. All six worlds were checked
against GA1's event columns and request fields, their independent truth labels,
verbatim source blocks, efficiency arithmetic, and unchanged base-world files.
No simulator or model was run to create or validate these worlds.
