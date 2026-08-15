# Persist Activity LINE delivery before sending

This ADR supersedes the **notification-delivery portion** of
[`0001-neon-degraded-daily-pipeline.md`](0001-neon-degraded-daily-pipeline.md).
The Daily Run's Neon gate and its `Normal → Persistence-loss` transition remain
unchanged.

Activity notifications now require persistence.  A new Activity first gets a
deterministic AI input, then its canonical `AIReport` and immutable
`LineNotification.rendered_messages` are committed before any LINE request.
The provider call runs outside the advisory lock and outside a DB session.  The
sender reacquires the lock, reloads the canonical payload, sends it, then marks
`sent_at` only after LINE accepts every batch.  A retry sends the saved payload;
it does not call Gemini or render a replacement message.

When persistence is unavailable, both the Cloud Daily Run and manual Activity
notification flow defer LINE delivery.  They do not use the former stateless
fallback, because it could send a newly generated message without durable
deduplication.  Baseline seeding still prevents historical activities from
being sent when the feature first becomes active.

This choice makes a temporary DB outage visible as deferred delivery rather
than silently delivering a potentially duplicate message.  LINE acknowledgement
and the DB `sent_at` commit are not atomic: if LINE accepts a payload but the
acknowledgement commit is lost, the stable LINE retry key protects retries for
its documented 24-hour window.  A later terminal-expiry workflow, if needed,
must preserve this ambiguity instead of claiming that the message was sent.
