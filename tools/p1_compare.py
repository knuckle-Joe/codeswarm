"""P1 gate part 2: side-by-side frames, original Java (left) vs codeswarm (right).

Usage:
  python tools/p1_compare.py EVENTS.xml CONFIG JAVA_FRAMES_DIR --frames 300,700,1100
         [--pattern cs-%05d.png] [--seed 7] [--out compare.png] [--zoom X,Y,W,H]

Physics starts from random positions in both programs, so layouts differ;
compare the look: sprite size/brightness, highlight, rings, edges, text,
legend, histogram, date. Output is never overwritten (compare_1.png ...).
"""
import argparse
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _deps import require  # noqa: E402
require("numpy", "pygame", "moderngl")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import numpy as np            # noqa: E402
import pygame                 # noqa: E402

from codeswarm.app import run_headless            # noqa: E402
from codeswarm.config import build_config         # noqa: E402
from codeswarm.ingest import load_events          # noqa: E402
from codeswarm.util import unique_path            # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("events")
ap.add_argument("config")
ap.add_argument("java_dir")
ap.add_argument("--frames", default="300,700,1100")
ap.add_argument("--pattern", default="cs-%05d.png")
ap.add_argument("--seed", type=int, default=7)
ap.add_argument("--out", default="compare.png")
ap.add_argument("--zoom", help="crop X,Y,W,H and scale x3")
ap.add_argument("--java-escapes", action="store_true", default=True)
ap.add_argument("--wrap", action="store_true", help="legacy alpha wrap (flashing) like the original")
a = ap.parse_args()

wanted = [int(x) for x in a.frames.split(",")]
cfg = build_config(config_path=a.config, java_escapes=a.java_escapes, overrides={"seed": a.seed, "legacy_alpha_wrap": a.wrap})
events, _ = load_events(a.events, cfg, cache_dir=".")
ours = {}
run_headless(events, cfg, frame_callback=lambda n, img: ours.__setitem__(n, img.copy()) if n in wanted else None,
             max_frames=max(wanted))


def to_surf(img):
    return pygame.image.frombuffer(np.ascontiguousarray(img).tobytes(), (img.shape[1], img.shape[0]), "RGB")


rows = []
for n in wanted:
    jpath = os.path.join(a.java_dir, a.pattern % n)
    j = pygame.image.load(jpath) if os.path.exists(jpath) else None
    o = to_surf(ours[n]) if n in ours else None
    pair = []
    for s in (j, o):
        if s is None:
            s = pygame.Surface((cfg["width"], cfg["height"]))
        if a.zoom:
            x, y, w, h = [int(v) for v in a.zoom.split(",")]
            s = pygame.transform.scale(s.subsurface((x, y, w, h)).copy(), (w * 3, h * 3))
        pair.append(s)
    rows.append(pair)

W, H = rows[0][0].get_size()
sheet = pygame.Surface((W * 2 + 4, (H + 4) * len(rows)))
sheet.fill((90, 90, 90))
for i, (j, o) in enumerate(rows):
    sheet.blit(j, (0, i * (H + 4)))
    sheet.blit(o, (W + 4, i * (H + 4)))
out = unique_path(a.out)
pygame.image.save(sheet, out)
print("Wrote %s  (left = original Java, right = codeswarm; frames %s)" % (out, a.frames))
