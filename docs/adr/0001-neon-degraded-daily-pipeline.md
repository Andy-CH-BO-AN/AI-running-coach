# Continue daily coaching when Neon is unavailable

The daily pipeline retries Neon migration three times, then enters degraded mode instead of failing. Degraded mode omits every Neon read, write, engine, session, and advisory lock; it analyzes ten newest Garmin activities and sends at most three stateless LINE notifications. We accept possible repeated notifications because GitHub Actions runners have no durable state when Neon is unavailable; adding external notification state would enlarge failure surface and operational scope.
