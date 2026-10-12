"""Simulation: a port of code_swarm.java update() and PhysicsEngineOrderly.

One call to step() is one animation frame, exactly as in the original:
  1. consume every event dated before prev_date + update_delta
  2. relax people (Orderly: centre pull, person-person spacing, file rings)
  3. verlet position update with friction, then life decay
Node bookkeeping (life, touches, editing slots with holes, edge life,
highlight thresholds) follows the Java code line by line.  Positions and
velocities live in numpy arrays so large repositories stay fast.

Deliberate differences, each marked FIX below:
  - person-person forces are computed for all pairs at once instead of
    mutating positions inside the loop (same pair forces, order-free)
  - zero-length vectors are guarded (Java produced NaN and lost the node)
"""

import fnmatch
import math
import re
from collections import deque

import numpy as np

MIN_DISTANCE_SQR = 40000.0
RING_RADIUS = 45
NODE_SIZE = 4
FILE_FRICTION = 0.9
HUB_SPACING = 100.0       # settle mode: distance hubs keep between them
HUB_CLEAR = 60.0          # settle mode: people keep this far from a hub
HUB_LOCK = 4.0            # a hub this close to its destination locks on
PERSON_FRICTION = 0.99


def _wrap_int32(v):
    return ((int(v) + 2 ** 31) % 2 ** 32) - 2 ** 31


class ColorRules:
    """ColorAssigner + ColorTest: first full-match wins, random lerp c1..c2."""

    def __init__(self, rules, rng):
        import re
        self.rng = rng
        from .colors import group_of
        self.group_of = group_of
        # rule kinds: regex (ColorAssign), ("group", g) language group, ("repo", r) repository
        self.rules = [(r["label"], ("repo", r["repo"]) if r.get("repo") else
                       (("group", r["group"]) if r.get("group") else re.compile(r["regex"])),
                       np.array(r["color"], float), np.array(r["color2"], float))
                      for r in rules]
        # code_swarm always appends the default rule
        self.rules.append(("Misc", re.compile(".*"), np.array([128.0] * 3), np.array([128.0] * 3)))
        self.legend = [(lab, tuple(int(x) for x in c1)) for (lab, _, c1, _) in self.rules]

    def color_for(self, path, repo=""):
        grp = None
        for _, rx, c1, c2 in self.rules:
            if isinstance(rx, tuple):
                if rx[0] == "repo":
                    hit = repo == rx[1]
                else:
                    if grp is None:
                        grp = self.group_of(path)
                    hit = grp == rx[1]
            else:
                hit = rx.fullmatch(path)
            if hit:
                t = self.rng.random()
                c = c1 + (c2 - c1) * t
                return np.round(c).astype(np.int32)   # Processing lerpColor rounds
        return np.array([128, 128, 128], np.int32)


class Pool:
    """Growable arrays for one node kind."""

    def __init__(self, cap=256):
        self.n = 0
        self.pos = np.zeros((cap, 2), np.float32)
        self.last = np.zeros((cap, 2), np.float32)
        self.life = np.zeros(cap, np.int32)
        self.touches = np.zeros(cap, np.int32)
        self.color = np.zeros((cap, 3), np.int32)

    def add(self):
        if self.n == len(self.life):
            cap = 2 * len(self.life)
            for name in ("pos", "last", "life", "touches", "color"):
                a = getattr(self, name)
                b = np.zeros((cap,) + a.shape[1:], a.dtype)
                b[: self.n] = a[: self.n]
                setattr(self, name, b)
        self.n += 1
        return self.n - 1


_SEMVER_TAG = re.compile(r"^(?:[A-Za-z][\w.-]*?[-_/])?[vV]?\d+(?:\.\d+)+(?:[-.+]?[0-9A-Za-z.]+)?$")
_BUILD_TAG = re.compile(r"^[A-Za-z]{0,3}\d+$")


def select_tags(tags, mode="auto"):
    """Which tags count as releases.

    auto: version-like tags (1.2, v0.3.1, flask-2.0rc1); if a project has
    none, build-number tags (b1234, r57); otherwise none.  all / none, or a
    shell pattern such as "v*" (several separated by commas)."""
    mode = (mode or "auto").strip()
    if mode == "none":
        return []
    if mode == "all":
        return list(tags)
    if mode == "auto":
        out = [t for t in tags if _SEMVER_TAG.match(t[0])]
        if not out:
            out = [t for t in tags if _BUILD_TAG.match(t[0])]
        return out
    pats = [m.strip() for m in mode.split(",") if m.strip()]
    return [t for t in tags if any(fnmatch.fnmatchcase(t[0], q) for q in pats)]


class Swarm:
    def __init__(self, events, cfg, seed=None, time_map=None, meta=None):
        self.cfg = cfg
        self.rng = np.random.default_rng(seed)
        self.w = cfg["width"]
        self.h = cfg["height"]
        self.events = events
        self.ev_i = 0
        self.update_delta = int(86400000 / cfg["frames_per_day"])
        self.prev_date = events[0].date if events else 0
        self.frame = 0
        self.colors = ColorRules(cfg["color_rules"], self.rng)

        self.files = Pool()
        self.file_names = []
        self.file_index = {}
        self.file_editor = []          # person index or -1  (FileNode.lastEditor)
        self.people = Pool(64)
        self.person_names = []
        self.person_index = {}
        self.person_editing = []       # list of file idx or -1 (holes)
        self.person_salt = []
        self.person_flavor = []        # mixed colour (lerpColor), kept for options
        self.person_color_count = []
        self.edge_index = {}           # (file, person) -> edge idx
        self.edge_ends = []            # (file, person)
        self.edge_life = np.zeros(256, np.int32)
        self.max_touches = 0
        self.history = []              # list of sorted colour lists (ColorBins)

        c = cfg
        self.file_life0, self.file_dec = c["file_life"], c["file_decrement"]
        self.person_life0, self.person_dec = c["person_life"], c["person_decrement"]
        self.edge_life0, self.edge_dec = c["edge_life"], c["edge_decrement"]
        self.file_mass = c["file_mass"]
        hp = c["highlight_pct"]
        self.file_min_bold = int(self.file_life0 * ((100.0 - hp) / 100))
        self.person_min_bold = int(self.person_life0 * (1 - (hp / 100.0)))
        self.events_this_frame = 0
        from .timeline import TimeMap
        self.time_map = time_map or TimeMap()
        self.last_skip = None          # (frame, skipped ms) for the "N days later" note
        # accents (new): commit ripples and "most active recently" ranking
        from collections import deque
        self.ripples = []              # (person, start frame, files in that commit)
        self.ripple_frames = int(c.get("fps", 24) * 1.2)
        days = c.get("popular_window_days")
        self.popular_windowed = bool(days)
        # the rolling window also feeds the stats panel (its own length if
        # the file ranking is all-time)
        days = days or (c.get("stats_window_days") or 30 if c.get("show_stats") or c.get("people_count") else 0)
        self.window_days = days or 0
        self.window_ms = int(days * 86400000) if days else 0
        self._recent = deque()
        self._recent_count = {}        # file -> changes in window
        self._recent_people = {}       # person -> changes in window
        self._recent_status = {}       # A/M/D/R -> count in window
        self._recent_commits = {}      # commit -> changes in window (distinct commits)
        self._recent_colour = {}       # file colour -> changes in window (activity mix)
        self.commits_seen = set()
        self.totals = {"commits": len(set(e.commit for e in events)),
                       "people": len(set(e.author for e in events)),
                       "files": len(set(e.path for e in events))}
        self.person_first = []         # first change date per person (newcomers)
        self.bounds = c.get("bounds", "auto")
        self.bottom_reserve = 0
        # commit details (drawing only - nothing here touches the random numbers)
        meta = meta or {}
        self.subjects = meta.get("subjects") or {}
        self.file_status = []          # last change per file: A M D R ...
        self.file_touch_frame = []     # frame of the last change per file
        self.file_people_all = []      # distinct people per file, all time
        self._recent_fp = {}           # (file, person) -> changes in window
        self._recent_fauth = {}        # file -> distinct people in window
        self.commit_feed = deque(maxlen=200)    # (frame, person, sha, files)
        self.person_commit = {}        # person -> (frame, sha) of the latest commit
        first = events[0].date if events else 0
        last = events[-1].date if events else 0
        tm = self.time_map
        tags = []
        for name, sha, date in select_tags(meta.get("tags") or [], c.get("release_tags", "auto")):
            t = tm.anim(date) if tm.skips else date
            if first <= t <= last + self.update_delta:
                tags.append((t, name))
        # tags on the same moment (v1.0 and v1.0.0) arrive together
        self.tags = sorted(tags)
        self.tag_i = 0
        self.tag_feed = deque(maxlen=50)        # (frame, [names])
        self.history_tags = []                  # aligned with history: [tag names] or None
        self.bannered = set()                   # tag names that got a banner
        # settle mode: the busiest shared files become slow hubs between their people
        self.hub_count = int(c.get("hubs", 0) or 0) if self.window_ms else 0
        self.hub_min_people = int(c.get("hub_min_people", 2) or 1)
        self.hubs = set()
        self.hub_follow = min(max(float(c.get("hub_follow", 1.0)), 0.0), 1.0)
        self.hub_speed = max(float(c.get("hub_speed", 20.0)), 0.05)
        self.hub_rate = min(max(float(c.get("hub_rate", 0.3)), 0.01), 1.0)
        self.track = None              # measuring: {file} whose ring target is recorded
        self.keepout = []              # keep_clear: panel rectangles (sim coordinates) people stay out of
        self.keepout_fn = None         # set by the app: swarm -> rectangles, asked every few frames
        self.track_target = {}
        self.hub_gather = bool(c.get("hub_gather", False))
        self._hub_slot = {}
        self._hub_work = {}
        self.release_banner = None              # (frame, name) of the release banner on screen
        self._pending_release = None
        self._last_banner = -10 ** 9
        self._banner_gap = int(float(c.get("release_gap_seconds", 4.0) or 0) * float(c.get("fps", 24)))

    # ------------------------------------------------------------------
    @property
    def done(self):
        return self.ev_i >= len(self.events)

    def current_date(self):
        return self.prev_date

    def _random_location(self):
        return np.array([self.w * self.rng.random(), self.h * self.rng.random()], np.float32)

    def _new_file(self, path, repo=""):
        i = self.files.add()
        f = self.files
        f.life[i] = self.file_life0
        f.touches[i] = 1
        f.color[i] = self.colors.color_for(path, repo)
        f.pos[i] = self._random_location()
        # PhysicsEngine.startVelocity(FileNode)
        v = np.array([self.rng.random() * 2 - 1, self.rng.random() * 2 - 1])
        ln = math.hypot(v[0], v[1]) or 1.0      # FIX: guard zero length
        v *= (1.0 / ln) * self.rng.random() * 15 / self.file_mass
        f.last[i] = f.pos[i] + v
        self.file_names.append(path)
        self.file_index[path] = i
        self.file_editor.append(-1)
        self.file_status.append("")
        self.file_touch_frame.append(0)
        self.file_people_all.append(0)
        return i

    def _new_person(self, name, date=0):
        i = self.people.add()
        self.person_first.append(date)
        p = self.people
        p.life[i] = self.person_life0
        p.touches[i] = 1
        p.pos[i] = self._random_location()     # Orderly.pStartLocation is never called
        p.last[i] = p.pos[i]
        self.person_names.append(name)
        self.person_index[name] = i
        self.person_editing.append([])
        self.person_salt.append(int(self.rng.integers(-2 ** 31, 2 ** 31)))
        self.person_flavor.append(np.array([0.0, 0.0, 0.0]))
        self.person_color_count.append(1)
        return i

    def _set_editor(self, fi, pi):
        old = self.file_editor[fi]
        if old == pi:
            return
        if old != -1:
            lst = self.person_editing[old]
            lst[lst.index(fi)] = -1
        self.file_editor[fi] = pi
        lst = self.person_editing[pi]
        try:
            lst[lst.index(-1)] = fi
        except ValueError:
            lst.append(fi)

    # ------------------------------------------------------------------
    def step(self):
        """Advance one frame. Returns the number of events consumed."""
        self.frame += 1
        bins = []
        committed = {}                      # person -> files touched this frame (ripples)
        frame_commits = {}                  # sha -> [person, files]
        next_date = self.prev_date + self.update_delta
        ev = self.events
        f, p = self.files, self.people
        while self.ev_i < len(ev) and ev[self.ev_i].date < next_date:
            e = ev[self.ev_i]
            self.ev_i += 1
            fi = self.file_index.get(e.path)
            if fi is None:
                fi = self._new_file(e.path, getattr(e, "repo", ""))
            else:                                   # FileNode.freshen
                f.life[fi] = self.file_life0
                f.touches[fi] += 1
                if f.touches[fi] > self.max_touches:
                    self.max_touches = int(f.touches[fi])
            c = f.color[fi]
            bins.append((int(c[0]) << 16) | (int(c[1]) << 8) | int(c[2]))

            pi = self.person_index.get(e.author)
            if pi is None:
                pi = self._new_person(e.author, e.date)
            else:                                   # PersonNode.freshen
                p.life[pi] = self.person_life0
                p.touches[pi] += 1
            cc = self.person_color_count[pi]        # addColor: lerpColor(flavor, c, 1/count)
            fl = self.person_flavor[pi]
            self.person_flavor[pi] = fl + (c - fl) * (1.0 / cc)
            self.person_color_count[pi] = cc + 1

            key = (fi, pi)
            ei = self.edge_index.get(key)
            if ei is None:
                ei = len(self.edge_ends)
                if ei == len(self.edge_life):
                    self.edge_life = np.concatenate([self.edge_life, np.zeros_like(self.edge_life)])
                self.edge_ends.append(key)
                self.edge_index[key] = ei
                self.file_people_all[fi] += 1
            self.edge_life[ei] = self.edge_life0
            self._set_editor(fi, pi)
            committed[pi] = committed.get(pi, 0) + 1
            self.commits_seen.add(e.commit)
            self.file_status[fi] = e.status or "?"
            self.file_touch_frame[fi] = self.frame
            fc_ = frame_commits.get(e.commit)
            if fc_ is None:
                frame_commits[e.commit] = [pi, 1]
            else:
                fc_[1] += 1
            if self.window_ms:
                ck = bins[-1]
                st = e.status or "?"
                self._recent.append((e.date, fi, pi, st, e.commit, ck))
                for d, k in ((self._recent_count, fi), (self._recent_people, pi), (self._recent_status, st),
                             (self._recent_commits, e.commit), (self._recent_colour, ck)):
                    d[k] = d.get(k, 0) + 1
                n_fp = self._recent_fp.get((fi, pi), 0)
                self._recent_fp[(fi, pi)] = n_fp + 1
                if not n_fp:
                    self._recent_fauth[fi] = self._recent_fauth.get(fi, 0) + 1
        self.events_this_frame = len(bins)
        skipped = self.time_map.skips_between(self.prev_date, next_date) if self.time_map.skips else []
        if skipped:
            self.last_skip = (self.frame, sum(ms for _, ms in skipped))
        self.prev_date = next_date
        bins.sort()
        for pi, nfiles in committed.items():
            self.ripples.append((pi, self.frame, nfiles))
        for sha, (pi, nfiles) in frame_commits.items():
            self.commit_feed.append((self.frame, pi, sha, nfiles))
            self.person_commit[pi] = (self.frame, sha)
        names = []
        while self.tag_i < len(self.tags) and self.tags[self.tag_i][0] < next_date:
            names.append(self.tags[self.tag_i][1])
            self.tag_i += 1
        banner = None
        if names:
            self.tag_feed.append((self.frame, names))
            self._pending_release = names[-1]
        if self._pending_release and self.frame - self._last_banner >= self._banner_gap:
            # releases closer together than the gap: only the latest gets a banner
            banner = self._pending_release
            self.release_banner = (self.frame, banner)
            self.bannered.add(banner)
            self._last_banner = self.frame
            self._pending_release = None
        if self.ripples:
            keep = self.frame - self.ripple_frames
            self.ripples = [r for r in self.ripples if r[1] > keep]
        if self.window_ms:                  # forget touches older than the window
            old = next_date - self.window_ms
            while self._recent and self._recent[0][0] < old:
                _, fi, pi, st, cm, ck = self._recent.popleft()
                for d, k in ((self._recent_count, fi), (self._recent_people, pi), (self._recent_status, st),
                             (self._recent_commits, cm), (self._recent_colour, ck)):
                    d[k] -= 1
                    if not d[k]:
                        del d[k]
                n_fp = self._recent_fp[(fi, pi)] - 1
                if n_fp:
                    self._recent_fp[(fi, pi)] = n_fp
                else:
                    del self._recent_fp[(fi, pi)]
                    self._recent_fauth[fi] -= 1
                    if not self._recent_fauth[fi]:
                        del self._recent_fauth[fi]
        self.history.append(bins)
        self.history_tags.append(names or None)
        if len(self.history) > 320:
            del self.history[0]
            del self.history_tags[0]

        if self.keepout_fn is not None and (self.frame % 6 == 1 or self.frame <= 1):
            self.keepout = self.keepout_fn(self)
        self._physics()
        return self.events_this_frame

    def _physics(self):
        f, p = self.files, self.people
        nf, npp, ne = f.n, p.n, len(self.edge_ends)

        # liveness cache (+ FileNode.isAlive side effect: free the editing slot)
        f_alive = f.life[:nf] > 0
        dead_with_editor = [i for i in np.nonzero(~f_alive)[0] if self.file_editor[i] != -1]
        for i in dead_with_editor:
            lst = self.person_editing[self.file_editor[i]]
            if i in lst:
                lst[lst.index(i)] = -1
            self.file_editor[i] = -1
        p_alive = np.nonzero(p.life[:npp] > 0)[0]
        e_alive = self.edge_life[:ne] > 0
        # what Java's livingNodes/livingPeople/livingEdges hold this frame
        self.living_counts = (int(f_alive.sum()), int(len(p_alive)), int(e_alive.sum()))

        # --- Orderly onRelax(person) ---------------------------------
        if len(p_alive):
            P = p.pos[p_alive].astype(np.float64)
            mid = np.array([self.w // 2, self.h // 2], np.float64)   # int division as in Java
            d = mid - P
            ln = np.linalg.norm(d, axis=1, keepdims=True)
            P += np.where(ln > 0, d / np.where(ln > 0, ln, 1) * 0.003, 0)
            if len(p_alive) > 1:
                D = P[:, None, :] - P[None, :, :]
                d2 = (D ** 2).sum(-1)
                ln = np.sqrt(d2)
                s = np.where(d2 < MIN_DISTANCE_SQR, 0.03, -0.003)
                np.fill_diagonal(s, 0.0)
                u = np.where(ln[..., None] > 0, D / np.where(ln > 0, ln, 1)[..., None], 0)
                # each pair is visited twice (as pNode and as n): factor 2
                P += 2.0 * (s[..., None] * u).sum(axis=1)
            p.pos[p_alive] = P.astype(np.float32)

            if self.keepout:
                self._keep_out(p_alive)
            hubs = self._update_hubs() if self.hub_count else ()
            self._hub_slot = {}
            if hubs and self.hub_gather:
                self._pull_people_to_hubs(hubs)
                self._clear_hubs()
            # file rings around each person (editing list, holes kept)
            tgt_f, tgt_xy = [], []
            for k, pi in enumerate(p_alive):
                lst = self.person_editing[pi]
                if not lst:
                    continue
                px, py = p.pos[pi]
                salt = self.person_salt[pi]
                index, radius = 0, RING_RADIUS
                n_ring = int((2 * radius * math.pi) / NODE_SIZE)
                for fi in lst:
                    if index == n_ring:
                        radius += NODE_SIZE
                        n_ring = int((2 * radius * math.pi) / NODE_SIZE)
                        index = 0
                    index += 1
                    if fi == -1:
                        continue
                    ang = _wrap_int32(index * n_ring + salt)
                    x = int(radius * math.sin(ang))        # Java (int) truncates
                    y = int(radius * math.cos(ang))
                    if self.track is not None and fi in self.track:
                        self.track_target[fi] = (px + x, py + y)
                    if fi in hubs:                         # hubs go there at their own pace
                        self._hub_slot[fi] = (px + x, py + y)
                        continue
                    tgt_f.append(fi)
                    tgt_xy.append((px + x, py + y))
            if tgt_f:
                idx = np.array(tgt_f)
                T = np.array(tgt_xy, np.float32)
                f.pos[idx] += -0.01 * (f.pos[idx] - T)

        # --- onUpdate: edges decay, nodes verlet + decay ---------------
        el = self.edge_life[:ne]
        el[e_alive] = np.maximum(el[e_alive] + self.edge_dec, 0)

        fa = np.nonzero(f_alive)[0]
        if len(fa):
            v = f.pos[fa] - f.last[fa]
            f.last[fa] = f.pos[fa]
            f.pos[fa] += v * FILE_FRICTION
            f.life[fa] = np.maximum(f.life[fa] + self.file_dec, 0)
        if self.hub_count and self.hubs:
            self._move_hubs()
        if len(p_alive):
            v = p.pos[p_alive] - p.last[p_alive]
            p.last[p_alive] = p.pos[p_alive]
            p.pos[p_alive] += v * PERSON_FRICTION
            p.life[p_alive] = np.maximum(p.life[p_alive] + self.person_dec, 0)
            pp = p.pos[p_alive]
            if self.bounds == "legacy":
                pp[:, 0] = np.clip(pp[:, 0], 50, self.w - 50)
                pp[:, 1] = np.clip(pp[:, 1], 45, self.h - 15)
            else:
                # FIX: keep the whole file ring of a person on screen.  The
                # original only kept the person's centre 15-50 px from the
                # edge, so a ring (radius 45 and up) could hang half outside.
                m = np.array([self._ring_margin(i) for i in p_alive], np.float32)
                lim = min(self.w, self.h) / 2.0 - 1
                m = np.minimum(m, lim)
                pp[:, 0] = np.clip(pp[:, 0], np.maximum(m, 50), self.w - np.maximum(m, 50))
                pp[:, 1] = np.clip(pp[:, 1], np.maximum(m, 45), self.h - np.maximum(m, 15 + self.bottom_reserve))
            p.pos[p_alive] = pp

    def _keep_out(self, alive):
        """keep_clear: people (with room for their file ring, name and avatar)
        are nudged out of the panels' rectangles, toward the nearest side that
        leads back into the open - never toward the screen edge."""
        p = self.people
        P = p.pos[alive].astype(np.float64)
        M = np.array([min(max(self._ring_margin(i), 25.0), 70.0) for i in alive], np.float64)
        for x0, y0, x1, y1 in self.keepout:
            ex0, ey0, ex1, ey1 = x0 - M, y0 - M, x1 + M, y1 + M
            inside = (P[:, 0] > ex0) & (P[:, 0] < ex1) & (P[:, 1] > ey0) & (P[:, 1] < ey1)
            if not inside.any():
                continue
            big = 1e9
            exits = np.column_stack([
                np.where(ex0 > 0, P[:, 0] - ex0, big),            # leave to the left
                np.where(ex1 < self.w, ex1 - P[:, 0], big),       # to the right
                np.where(ey0 > 0, P[:, 1] - ey0, big),            # up
                np.where(ey1 < self.h, ey1 - P[:, 1], big),       # down
            ])
            side = exits.argmin(axis=1)
            pen = exits.min(axis=1)
            mv = np.minimum(pen * 0.08 + 0.3, 3.0)
            mv = np.where(inside & (pen < big), mv, 0.0)
            P[:, 0] += np.where(side == 0, -mv, np.where(side == 1, mv, 0.0))
            P[:, 1] += np.where(side == 2, -mv, np.where(side == 3, mv, 0.0))
        p.pos[alive] = P.astype(np.float32)

    # ------------------------------------------------------------------
    # settle mode
    def _update_hubs(self):
        """Hubs = the top `hubs` files of the window changed by at least
        hub_min_people people.  A hub stays a hub until it drops out of the
        top 1.5 x hubs (no flicker at the edge of the ranking)."""
        n = self.hub_count
        ranked = sorted(self._recent_count.items(), key=lambda kv: (-kv[1], kv[0]))[: int(n * 1.5) + 1]
        keep = set()
        for pos, (fi, _) in enumerate(ranked):
            if self._recent_fauth.get(fi, 0) < self.hub_min_people or self.files.life[fi] <= 0:
                continue
            if pos < n or fi in self.hubs:
                keep.add(fi)
        self.hubs = keep
        # who works on each hub (recent changes per person)
        work = {}
        for (fi, pi), cnt in self._recent_fp.items():
            if fi in keep and self.people.life[pi] > 0:
                work.setdefault(fi, []).append((pi, cnt))
        self._hub_work = work
        return keep

    def _pull_people_to_hubs(self, hubs):
        """People drift gently toward the hubs they work on, so the people
        sharing a file gather around it (stops at a ring's distance)."""
        p, f = self.people, self.files
        for fi, lst in self._hub_work.items():
            hx, hy = f.pos[fi]
            tot = float(sum(c for _, c in lst))
            for pi, cnt in lst:
                dx, dy = hx - p.pos[pi][0], hy - p.pos[pi][1]
                d = math.hypot(dx, dy)
                if d > RING_RADIUS * 2.6:
                    # a gentle drift (at most 0.25 px a frame), weaker than people
                    # pushing each other apart, so nobody piles onto a hub
                    step = min(0.25, 0.0008 * d) * (cnt / tot) ** 0.5
                    p.pos[pi][0] += dx / d * step
                    p.pos[pi][1] += dy / d * step

    def _clear_hubs(self):
        """Nobody sits on a hub: living people inside its clear zone are
        nudged out (at most 0.6 px a frame)."""
        f, p = self.files, self.people
        alive = np.nonzero(p.life[:p.n] > 0)[0]
        if not len(alive) or not self.hubs:
            return
        P = p.pos[alive].astype(np.float64)
        for fi in self.hubs:
            D = P - f.pos[fi]
            d = np.sqrt((D ** 2).sum(1))
            m = d < HUB_CLEAR
            if m.any():
                u = D[m] / np.maximum(d[m], 1e-6)[:, None]
                P[m] += u * np.minimum((HUB_CLEAR - d[m]) * 0.05, 0.6)[:, None]
        p.pos[alive] = P.astype(np.float32)

    def _move_hubs(self):
        """A hub heads for its destination with no momentum (so it never
        overshoots or orbits like the original spring): each frame it covers
        hub_rate of the distance left, at most hub_speed px, and once it is
        within HUB_LOCK px it locks on and rides along with its person.

        Destination: the ring slot of the person who changed it last (as in
        the original), blended with the weighted centre of everyone who
        changed it lately when hub_follow < 1."""
        f, p = self.files, self.people
        hubs = sorted(self.hubs)
        if not hubs:
            return
        H = f.pos[hubs].astype(np.float64)
        T = H.copy()
        for k, fi in enumerate(hubs):
            slot = self._hub_slot.get(fi)
            centre = None
            if self.hub_follow < 1.0 or slot is None:
                lst = self._hub_work.get(fi)
                if lst:
                    w = np.array([c for _, c in lst], np.float64)
                    P = p.pos[[pi for pi, _ in lst]].astype(np.float64)
                    centre = (P * w[:, None]).sum(0) / w.sum()
            if slot is not None and centre is not None:
                T[k] = self.hub_follow * np.array(slot) + (1 - self.hub_follow) * centre
            elif slot is not None:
                T[k] = slot
            elif centre is not None:
                T[k] = centre
        v = self.hub_speed
        step = (T - H) * self.hub_rate
        ln = np.linalg.norm(step, axis=1, keepdims=True)
        H += np.where(ln > v, step / np.maximum(ln, 1e-9) * v, step)
        if self.hub_follow < 1.0 and len(hubs) > 1:     # blended targets can meet: keep apart
            D = H[:, None, :] - H[None, :, :]
            d = np.sqrt((D ** 2).sum(-1))
            np.fill_diagonal(d, 1e9)
            push = np.where(d < HUB_SPACING, (HUB_SPACING - d) * 0.04, 0.0)
            u = D / np.maximum(d, 1e-6)[..., None]
            H += (push[..., None] * u).sum(1)
        # arrived: stick to the destination exactly
        near = np.linalg.norm(T - H, axis=1) < HUB_LOCK
        H[near] = T[near]
        m = 10.0
        H[:, 0] = np.clip(H[:, 0], m, self.w - m)
        H[:, 1] = np.clip(H[:, 1], m, self.h - m)
        f.pos[hubs] = H.astype(np.float32)
        f.last[hubs] = f.pos[hubs]               # no momentum: hubs never fly

    def _ring_margin(self, pi):
        """Outer radius of person pi's file rings plus room for the glow."""
        slots = len(self.person_editing[pi])
        if slots == 0:
            return 0.0
        radius = RING_RADIUS
        n_ring = int((2 * radius * math.pi) / NODE_SIZE)
        while slots > n_ring:
            slots -= n_ring
            radius += NODE_SIZE
            n_ring = int((2 * radius * math.pi) / NODE_SIZE)
        return radius + 12.0

    # ------------------------------------------------------------------
    def counts(self):
        """Living counts, same definitions as the instrumented Java build."""
        return (int((self.files.life[: self.files.n] > 0).sum()),
                int((self.people.life[: self.people.n] > 0).sum()),
                int((self.edge_life[: len(self.edge_ends)] > 0).sum()))

    def popular(self, limit=10):
        """Ranked files for the popular panel.

        With popular_window_days: files with the most changes in that recent
        window (ties: older first).  Otherwise the original drawPopular: all
        nodes ever (not only living), touches >= max/2, descending."""
        if self.popular_windowed:
            items = sorted(self._recent_count.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
            return [(self.file_names[i], n, i) for i, n in items]
        return self.popular_idx(limit)

    def file_authors(self, fi):
        """Distinct people who changed file fi (in the window when there is one)."""
        if self.window_ms:
            return self._recent_fauth.get(fi, 0)
        return self.file_people_all[fi]

    def subject(self, sha):
        return self.subjects.get(sha, "")

    def active_people(self, limit=5):
        """People with the most changes in the window: [(name, changes, index)]."""
        items = sorted(self._recent_people.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
        return [(self.person_names[i], n, i) for i, n in items]

    def stats(self):
        """Numbers for the stats panel (cumulative and in the rolling window)."""
        lo = self.prev_date - self.window_ms
        newcomers = [self.person_names[i] for i, d in enumerate(self.person_first) if self.window_ms and d >= lo]
        return {
            "commits": len(self.commits_seen), "people": self.people.n, "files": self.files.n,
            "w_commits": len(self._recent_commits), "w_people": len(self._recent_people),
            "w_files": len(self._recent_count), "w_changes": len(self._recent),
            "w_status": dict(self._recent_status), "w_colour": dict(self._recent_colour),
            "newcomers": newcomers, "window_days": self.window_days,
        }

    def popular_idx(self, limit=10):
        """drawPopular: all nodes ever (not only living), touches >= max/2, desc."""
        t = self.files.touches[: self.files.n]
        q = np.nonzero(t >= self.max_touches * 0.5)[0]
        order = q[np.argsort(-t[q], kind="stable")]
        return [(self.file_names[i], int(t[i]), int(i)) for i in order[:limit]]
