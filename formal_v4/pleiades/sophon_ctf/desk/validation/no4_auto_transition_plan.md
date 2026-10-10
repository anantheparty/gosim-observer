# No.4 fresh-auto transition experiment

## Why this is the remaining clean comparison

The only issued object associated with the missing No.4 is the bar's `pass`.
It appeared on the fifth bar request of the original state and never appeared
again in more than four hundred later bar requests, including four wrong-door
resets and four newly opened correct four-word doors.  It is therefore a
one-time story object, not a phrase-sensitive or ordinary random response.

The debug history used this order:

1. receive the decoy pass;
2. leave it unsubmitted;
3. reach the deepest room and submit the genuine pass, which solved No.10;
4. much later submit the decoy, which returned `error=fooled`.

The late repair experiment used `decoy -> fresh house -> genuine pass`, but
No.10 was already solved.  It could not exercise a transition attached to the
first successful stamping of the genuine pass.  A fresh auto run is the only
available state in which both order and first-solve status can be controlled.

## Bounded run sequence

This remains disabled until a current run proves the exact
`SOPHON_RUN_TOKEN` authentication shape.

1. At the first decision barrier, require `SOPHON_RUN_TOKEN`; never fall back
   to `OBSERVER_RUN_TOKEN`.
2. Follow the published caretaker handshake (`contact-johnny`, `answer`,
   `status`) if the current contract requires it.
3. Open the front door with `THE SHINING`, but do not submit the returned No.2
   flag.
4. Ask the bar at most twelve times.  In the original fresh state the decoy
   appeared at call 5 and all four 237-backed door words were available by
   call 7.
5. Submit the returned decoy immediately.  Continue only if the service gives
   the expected `fooled` result or explicitly identifies No.4.
6. Open the four-word door using the four values extracted from 237-backed
   statements. Submit codes issued live by this response; none are copied
   from the debug history. This catches a No.4 receipt attached to the direct
   `fooled -> correct door` transition.
7. Tell the house the already solved Introduction line, submit only codes
   issued live by that response, then enter it.
8. Crawl the current house graph breadth-first using only room identifiers
   disclosed by the current response, stopping at the dynamically issued
   genuine pass.  The graph has changed between entries, so neither room ids
   nor old door-label paths are reused.  The crawl is capped at 160 distinct
   rooms; identifiers remain in memory and are never logged.
9. Submit the genuine pass returned by the deepest room exactly once.  This is
   a dynamically issued result, not a hard-coded debug flag. If any live code
   is confirmed by the desk as No.4, log that code and stop.
10. Read the auto root/status once and stop.  Record only HTTP status, safe
    field names, board, solved number, and found numbers.  Never log the run
    token, authorization material, dynamic room identifiers, or unsubmitted
    flag values.

## Interpretation

- If the decoy submission itself solves No.4, the missing condition was the
  fresh/immediate timing.
- If the first genuine-pass submission also produces No.4, the condition was
  the `fooled -> walk the whole way` transition.
- If only No.10 is recorded, this specific transition is falsified; do not
  repeat it with wording or route variants.
- A `debug` board response or any authentication rejection stops the run
  before state-changing desk calls.
