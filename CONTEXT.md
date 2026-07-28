# AI Running Coach

AI Running Coach converts Garmin activity data into deterministic training context, AI coaching analysis, reports, and LINE notifications.

## Language

**Normal mode**:
Daily pipeline state where Neon persistence is available. It processes a 75-activity window and uses persistent LINE notification deduplication.
_Avoid_: standard mode, online mode

**Degraded mode**:
Daily pipeline state entered after Neon migration fails three times. It skips all Neon access, processes a 10-activity window, and continues Garmin, AI, report, and stateless LINE work.
_Avoid_: partial mode, fallback database mode

**Activity window**:
Newest bounded set of Garmin activities used by every downstream pipeline stage for one run.
_Avoid_: history, activity backlog

**Stateless notification**:
LINE notification sent without Neon-backed deduplication. It may repeat on later degraded or recovery runs.
_Avoid_: durable notification, exactly-once notification
