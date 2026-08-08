# AI Running Coach

AI Running Coach converts Garmin activity data into deterministic training context, AI coaching analysis, reports, and LINE notifications.

## Language

**Normal mode**:
Cloud Daily Run state where Neon persistence is available. It processes a 75-activity window and uses persistent LINE notification deduplication.
_Avoid_: standard mode, online mode

**Degraded mode**:
Cloud Daily Run state entered after Neon migration fails three times. It skips all later Neon access, processes a 10-activity window, and continues Garmin, AI, report, and stateless LINE work.
_Avoid_: partial mode, fallback database mode

**Persistence-loss mode**:
Cloud Daily Run state entered when Neon becomes unavailable after Normal mode starts. It retains the already-selected 75-activity window, stops Neon use for the rest of that run, and allows at most three stateless notifications.
_Avoid_: degraded mode, database retry mode

**Activity window**:
Newest bounded set of Garmin activities used by every downstream pipeline stage for one run.
Its size and order are selected before preprocessing. Activity-window normalization then
owns eligibility filtering, canonical Activity identity, source interpretation, and unit
conversion exactly once; it never chooses the run mode, limit, or ordering.
_Avoid_: history, activity backlog

**Stateless notification**:
LINE notification sent without Neon-backed deduplication. A sent-but-unrecorded notification counts toward the current run's stateless limit and may repeat on a later run.
_Avoid_: durable notification, exactly-once notification

**Swimming rest interval**:
A Garmin swimming interval with positive duration but no distance, moving time, active lengths, or swim stroke. Missing source indices alone never establish a rest interval.
_Avoid_: inferred rest, index-gap rest

**Swimming elapsed time**:
Wall-clock duration of a swimming activity, including swimming, rest, and any unclassified gaps reported by Garmin.
_Avoid_: timer duration, moving time

**Swimming time**:
Duration Garmin reports as moving time for a swimming activity. It is not inferred from elapsed-time differences.
_Avoid_: active-time estimate, elapsed time

**Swimming rest time**:
Duration Garmin reports directly as rest, or the sum of reliably identified swimming rest intervals. It is never calculated as elapsed time minus swimming time.
_Avoid_: residual time, inferred rest time

**Average swimming pace**:
Total swimming distance divided by swimming time, expressed per 100 metres.
_Avoid_: elapsed average pace

**Elapsed swimming pace**:
Total swimming distance divided by swimming elapsed time, expressed per 100 metres.
_Avoid_: average swimming pace
