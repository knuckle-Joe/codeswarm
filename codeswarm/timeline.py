"""Time handling between the history and the animation.

compress_gaps(): quiet periods longer than max_gap are shortened to max_gap,
so a project that sleeps for months does not show months of empty frames.
The returned TimeMap converts animation time back to real dates (the date
overlay always shows the real date) and lists where the jumps are, so the
renderer can say "3 months later".

frames_per_day_for(): the frames-per-day that makes the animation last a
given number of frames.
"""

import bisect

DAY_MS = 86400000


class TimeMap:
    def __init__(self, starts=None, offsets=None, skips=None):
        self.starts = starts or [0]          # animation times where an offset begins
        self.offsets = offsets or [0]        # real = animation + offset
        self.skips = skips or []             # (animation time, skipped ms)

    def real(self, t):
        i = bisect.bisect_right(self.starts, t) - 1
        return t + self.offsets[max(i, 0)]

    def anim(self, real):
        """Animation time of a real date (dates inside a shortened gap land at its end)."""
        reals = [st + off for st, off in zip(self.starts, self.offsets)]
        i = bisect.bisect_right(reals, real) - 1
        if i < 0:
            return real - self.offsets[0]
        t = real - self.offsets[i]
        if i + 1 < len(self.starts):
            t = min(t, self.starts[i + 1])
        return t

    def skips_between(self, t0, t1):
        """Skips whose animation time is in (t0, t1]."""
        return [(t, ms) for (t, ms) in self.skips if t0 < t <= t1]


def compress_gaps(events, max_gap_days):
    """Return (events with animation dates, TimeMap). Order is unchanged."""
    if not events or not max_gap_days or max_gap_days <= 0:
        return events, TimeMap()
    g = int(max_gap_days * DAY_MS)
    out = []
    shift = 0
    starts, offsets, skips = [events[0].date], [0], []
    prev = events[0].date
    for e in events:
        gap = e.date - prev
        if gap > g:
            cut = gap - g
            shift += cut
            t = e.date - shift
            starts.append(t)
            offsets.append(shift)
            skips.append((t, cut))
        prev = e.date
        out.append(e._replace(date=e.date - shift))
    return out, TimeMap(starts, offsets, skips)


def span_days(events):
    if len(events) < 2:
        return 0.0
    return (events[-1].date - events[0].date) / float(DAY_MS)


def frames_per_day_for(events, frames):
    """frames-per-day so the swarm part lasts about `frames` frames."""
    days = span_days(events)
    if days <= 0:
        return 25.0
    return max((frames - 1) / days, 0.01)


def humanize_ms(ms):
    days = ms / float(DAY_MS)
    if days < 2:
        return "%d hours later" % max(1, round(days * 24))
    if days < 60:
        return "%d days later" % round(days)
    if days < 730:
        return "%d months later" % round(days / 30.44)
    return "%.1f years later" % (days / 365.25)
