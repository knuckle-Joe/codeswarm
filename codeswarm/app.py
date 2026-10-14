"""Run loops: live window (pygame + OpenGL) and headless frame output."""

import os
import time

import numpy as np

from .sim import Swarm
from .util import say, warn

TOGGLE_KEYS = {
    "a": "draw_names_halos", "b": "show_debug", "d": "show_date", "e": "show_edges",
    "E": "show_engine", "f": "draw_files_fuzzy", "h": "show_history", "j": "draw_files_jelly",
    "l": "show_legend", "p": "show_popular", "s": "draw_names_sharp", "S": "draw_files_sharp",
    "?": "show_help", "r": "ripples", "i": "show_stats",
    "c": "commit_text", "t": "show_releases", "n": "name_spread", "g": "show_regions",
}


KEY_HELP = [
    "Keys:  space  pause / resume        q, Esc  quit",
    "       a  name halos (glow)         s  names",
    "       f  fuzzy files (glow)        j  jelly files (rings)",
    "       S  sharp files (dots)        e  edges (person-file lines)",
    "       l  legend                    p  popular files",
    "       h  histogram                 d  date",
    "       b  debug numbers             E  physics engine name",
    "       r  commit ripples            i  repository stats",
    "       c  commit messages           t  release tags",
    "       n  spread overlapping names   g  neighbourhood names",
    "       ?, F1  help panel",
]


# keys that work whatever the keyboard layout (key codes, not characters)
_KEYCODE_ACTIONS = {"K_ESCAPE": "quit", "K_F1": "show_help"}


def key_actions(pygame, events):
    """Turn a batch of pygame events into actions.

    Characters come from TEXTINPUT events: they carry the real character for
    any layout ('?' is Shift+6 on a Canadian French keyboard, Shift+/ on US).
    KEYDOWN.unicode is often empty for shifted keys on SDL2 - that made '?'
    and the capital-letter keys (E, S) hit or miss.  KEYDOWN is used only for
    layout-free keys (Esc, F1) and as a fallback when the platform sends no
    TEXTINPUT at all."""
    actions = []
    text_seen = any(ev.type == pygame.TEXTINPUT for ev in events)
    for ev in events:
        if ev.type == pygame.QUIT:
            actions.append("quit")
        elif ev.type == pygame.TEXTINPUT:
            for ch in ev.text:
                actions.extend(_char_action(ch))
        elif ev.type == pygame.KEYDOWN:
            for name, act in _KEYCODE_ACTIONS.items():
                if ev.key == getattr(pygame, name):
                    actions.append(act)
                    break
            else:
                if not text_seen and getattr(ev, "unicode", ""):
                    actions.extend(_char_action(ev.unicode))
    return actions


def _char_action(ch):
    if ch == " ":
        return ["pause"]
    if ch in ("q", "Q"):
        return ["quit"]
    if ch in TOGGLE_KEYS:
        return [TOGGLE_KEYS[ch]]
    return []


def sim_cfg(cfg):
    """The simulation runs on the screen size divided by the ui scale, so the
    swarm keeps its proportions and the renderer draws it larger."""
    from .render import sim_size
    w, h = sim_size(cfg)
    return dict(cfg, width=w, height=h)


def initial_state(cfg):
    keys = ["show_edges", "draw_names_halos", "draw_names_sharp", "draw_files_sharp",
            "draw_files_fuzzy", "draw_files_jelly", "show_legend", "show_history",
            "show_date", "show_debug", "show_popular"]
    st = {k: bool(cfg[k]) for k in keys}
    st["show_engine"] = bool(cfg.get("show_engine", False))
    st["ripples"] = bool(cfg.get("ripples", False))
    st["show_stats"] = bool(cfg.get("show_stats", False))
    st["commit_text"] = cfg.get("commit_text", "off") != "off"
    st["show_releases"] = bool(cfg.get("show_releases", False))
    st["name_spread"] = cfg.get("name_layout", "off") == "spread"
    st["show_regions"] = True
    st["show_help"] = False
    return st


def keep_clear(sw, r, st, cfg):
    """keep_clear: the swarm stays out of the panels (asked every few frames,
    measured without drawing, so videos and the window behave the same)."""
    if cfg.get("keep_clear"):
        k = r.k
        sw.keepout_fn = lambda s_: [(x0 / k, y0 / k, x1 / k, y1 / k) for x0, y0, x1, y1 in r.panel_rects(s_, st)]


def _standalone_context():
    import moderngl
    try:
        return moderngl.create_standalone_context(require=330)
    except Exception as first:
        try:
            return moderngl.create_standalone_context(require=330, backend="egl")
        except Exception:
            raise first


def unique_dir(path):
    if not os.path.exists(path) or (os.path.isdir(path) and not os.listdir(path)):
        return path
    n = 1
    while os.path.exists("%s_%d" % (path, n)):
        n += 1
    return "%s_%d" % (path, n)


def save_png(img, path):
    import pygame
    surf = pygame.image.frombuffer(np.ascontiguousarray(img).tobytes(), (img.shape[1], img.shape[0]), "RGB")
    pygame.image.save(surf, path)


def estimate_frames(events, cfg, max_frames=None, show=None):
    """Frames the run will take: intro + one per update_delta + linger + credits."""
    if not events:
        return 0
    delta = int(86400000 / cfg["frames_per_day"])
    if cfg.get("pace"):
        n = Swarm.paced_frames(events, delta, float(cfg["pace"]) / float(cfg.get("fps", 24)))
        n += int(cfg.get("linger_frames", 0))
    else:
        n = (events[-1].date - events[0].date) // delta + 1 + int(cfg.get("linger_frames", 0))
    if show:
        n += show.intro_frames + show.credits_frames
    return min(n, max_frames) if max_frames else n


class ShowSpec:
    """What surrounds the swarm: intro card and closing credits (all optional)."""

    def __init__(self, cfg, title=None, subtitle=None, legend=None, credits=None,
                 intro_seconds=0.0, credits_seconds=0.0, time_map=None):
        fps = cfg["fps"]
        self.title = title
        self.subtitle = subtitle or []
        self.legend = legend
        self.credits = credits or []
        self.intro_frames = int(round(intro_seconds * fps)) if title else 0
        self.credits_frames = int(round(credits_seconds * fps)) if credits else 0
        self.fade = max(1, int(fps * 0.6))
        self.time_map = time_map

    def _alpha(self, i, n):
        return max(0.0, min(1.0, (i + 1) / float(self.fade), (n - i) / float(self.fade)))


def show_frames(sw, r, st, cfg, spec=None):
    """Yield (kind, draw) for every output frame, in order.

    kind is "intro", "swarm" or "credits"; draw() renders that frame into the
    renderer's framebuffer.  The simulation steps exactly once per swarm frame
    whether or not the frame is drawn, and the intro/credits consume no random
    numbers, so the swarm part is identical with or without cards."""
    spec = spec or ShowSpec(cfg)
    for i in range(spec.intro_frames):
        a = spec._alpha(i, spec.intro_frames)
        yield "intro", (lambda a=a: r.draw_card(spec.title, spec.subtitle, a, spec.legend))
    linger = int(cfg.get("linger_frames", 0))
    tail = 0
    while True:
        if sw.done:
            tail += 1
        sw.step()
        yield "swarm", (lambda: r.draw(sw, st, {"ms": getattr(r, "last_ms", "-")}))
        if sw.done and tail >= linger:
            break
    for i in range(spec.credits_frames):
        a = spec._alpha(i, spec.credits_frames)
        yield "credits", (lambda a=a: r.draw_credits("Contributors", spec.credits, a))


class Progress:
    """One ASCII status line, refreshed in place every `period` seconds."""

    def __init__(self, total, label="frame", period=1.0):
        import sys
        self.out = sys.stdout
        self.total = max(total, 1)
        self.label = label
        self.period = period
        self.t0 = time.time()
        self.last = 0.0

    def update(self, n, force=False):
        now = time.time()
        if not force and now - self.last < self.period:
            return
        self.last = now
        el = now - self.t0
        rate = n / el if el > 0 else 0.0
        eta = (self.total - n) / rate if rate > 0 else 0.0
        self.out.write("\r  %s %d/%d (%3d%%)  %.0f fps  elapsed %s  left %s   "
                       % (self.label, n, self.total, min(100, 100 * n // self.total), rate,
                          _hms(el), _hms(max(eta, 0))))
        self.out.flush()

    def done(self):
        self.out.write("\n")
        self.out.flush()


def _hms(sec):
    sec = int(sec)
    return "%d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)


def run_headless(events, cfg, frames_dir=None, pattern="cs-%05d.png", start=1,
                 every=1, max_frames=None, frame_callback=None, progress=False, avatars=None,
                 spec=None, time_map=None, meta=None):
    """Render without a window. Writes PNGs to frames_dir (if given) and/or
    passes each RGB frame to frame_callback(frame_no, img). Returns stats.
    Frame numbers count every output frame (intro, swarm, credits)."""
    from .render import Renderer
    ctx = _standalone_context()
    r = Renderer(ctx, cfg)
    r.set_avatars(avatars)
    sw = Swarm(events, sim_cfg(cfg), seed=cfg.get("seed"), time_map=time_map, meta=meta)
    st = initial_state(cfg)
    keep_clear(sw, r, st, cfg)
    if frames_dir:
        os.makedirs(frames_dir, exist_ok=True)
    t0 = time.time()
    t_draw = t_io = 0.0
    written = 0
    fno = 0
    prog = Progress(estimate_frames(events, cfg, max_frames, spec)) if progress else None
    for kind, draw in show_frames(sw, r, st, cfg, spec):
        fno += 1
        if prog:
            prog.update(fno)
        if fno >= start and (fno - start) % every == 0:
            b = time.time()
            draw()
            c = time.time()
            img = r.read_rgb()
            if frames_dir:
                save_png(img, os.path.join(frames_dir, pattern % fno))
            if frame_callback:
                frame_callback(fno, img)
            written += 1
            t_draw += c - b
            t_io += time.time() - c
        if max_frames and fno >= max_frames:
            break
    if prog:
        prog.update(fno, force=True)
        prog.done()
    ctx.release()
    total = time.time() - t0
    return {"frames": fno, "swarm_frames": sw.frame, "written": written, "seconds": total,
            "sim_s": max(total - t_draw - t_io, 0.0), "draw_s": t_draw, "io_s": t_io}


def run_live(events, cfg, title="codeswarm", max_frames=None, avatars=None, spec=None, time_map=None,
             meta=None):
    """Interactive window with the original keyboard toggles."""
    import pygame
    import moderngl
    from .render import Renderer

    pygame.display.init()      # no pygame.init(): it also opens audio
    pygame.font.init()
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE)
    pygame.display.set_mode((cfg["width"], cfg["height"]), pygame.OPENGL | pygame.DOUBLEBUF)
    pygame.display.set_caption(title)
    ctx = moderngl.create_context()
    r = Renderer(ctx, cfg)
    r.set_avatars(avatars)
    sw = Swarm(events, sim_cfg(cfg), seed=cfg.get("seed"), time_map=time_map, meta=meta)
    st = initial_state(cfg)
    keep_clear(sw, r, st, cfg)
    clock = pygame.time.Clock()
    pygame.key.start_text_input()         # deliver TEXTINPUT events (layout-correct characters)
    for line in KEY_HELP:
        say(line)
    frames = show_frames(sw, r, st, cfg, spec)
    paused = False
    running = True
    fno = 0
    draw = None
    last_ms = 0
    while running:
        changed = False
        for action in key_actions(pygame, pygame.event.get()):
            if action == "quit":
                running = False
            elif action == "pause":
                paused = not paused
                say("  [key] %s" % ("paused" if paused else "running"))
            elif action in st or action in TOGGLE_KEYS.values():
                st[action] = not st.get(action, False)
                changed = True
                say("  [key] %s: %s" % (action, "on" if st[action] else "off"))
        if not running:
            break
        if not paused or draw is None:
            t = time.time()
            try:
                kind, draw = next(frames)
            except StopIteration:
                break
            fno += 1
            draw()
            last_ms = int((time.time() - t) * 1000)
            r.last_ms = last_ms
        elif changed:
            draw()                         # toggles show up while paused
        ctx.copy_framebuffer(ctx.screen, r.fbo)
        pygame.display.flip()
        clock.tick(cfg["fps"])
        if max_frames and fno >= max_frames:
            running = False
    stats = {"frames": fno, "fps": clock.get_fps()}
    pygame.quit()
    return stats
