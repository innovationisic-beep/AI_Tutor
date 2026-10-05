"""Pass bar for a 1k-session teaching-runtime load pass.

A run meets the bar only when at least 1000 sessions finished (completed or
stuck) and the stuck rate is zero. This module does not start that load.
"""

from __future__ import annotations

LOAD_TARGET_SESSIONS = 1000
STUCK_RATE_MAX = 0.0


def meets_load_bar(*, stuck_sessions: int, completed_sessions: int) -> bool:
    stuck = max(0, int(stuck_sessions))
    completed = max(0, int(completed_sessions))
    total = stuck + completed
    if total < LOAD_TARGET_SESSIONS:
        return False
    if total == 0:
        return False
    return (stuck / total) <= STUCK_RATE_MAX
