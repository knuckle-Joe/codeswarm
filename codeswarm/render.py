"""GPU renderer (moderngl, OpenGL 3.3) reproducing code_swarm's draw().

Everything is drawn into an off-screen framebuffer in pixel coordinates
(y down, like Processing).  The live window copies that framebuffer to the
screen; headless mode reads it back for PNG / video output.

All shaders output premultiplied alpha and blend with (ONE, ONE_MINUS_SRC_ALPHA),
which equals Processing's default BLEND mode for straight-alpha inputs.
"""

import colorsys
import datetime
import math
import os

import numpy as np
import moderngl

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

_HEAD = "#version 330\n"
_VS_COMMON = """
uniform vec2 u_size;
vec4 to_clip(vec2 p) { return vec4(p.x / u_size.x * 2.0 - 1.0, 1.0 - p.y / u_size.y * 2.0, 0.0, 1.0); }
"""

SPRITE_VS = _HEAD + _VS_COMMON + """
in vec2 in_corner;
in vec2 i_center; in float i_size; in vec4 i_color;
out vec2 v_uv; out vec4 v_color;
void main() {
    vec2 p = i_center + in_corner * i_size * 0.5;
    v_uv = in_corner * 0.5 + 0.5;
    v_color = i_color;
    gl_Position = to_clip(p);
}
"""
SPRITE_FS = _HEAD + """
uniform sampler2D u_tex;
in vec2 v_uv; in vec4 v_color;
out vec4 f_color;
void main() {
    vec4 t = texture(u_tex, v_uv);
    float a = t.a * v_color.a;
    f_color = vec4(t.rgb * v_color.rgb * a, a);
}
"""

CIRCLE_VS = _HEAD + _VS_COMMON + """
in vec2 in_corner;
in vec2 i_center; in float i_radius; in float i_stroke_w; in vec4 i_fill; in vec4 i_stroke;
out vec2 v_local; out float v_radius; out float v_sw; out vec4 v_fill; out vec4 v_stroke;
void main() {
    float ext = i_radius + max(i_stroke_w, 1.0) * 0.5 + 1.5;
    v_local = in_corner * ext;
    v_radius = i_radius; v_sw = i_stroke_w; v_fill = i_fill; v_stroke = i_stroke;
    gl_Position = to_clip(i_center + v_local);
}
"""
CIRCLE_FS = _HEAD + """
in vec2 v_local; in float v_radius; in float v_sw; in vec4 v_fill; in vec4 v_stroke;
out vec4 f_color;
void main() {
    float d = length(v_local);
    float fa = v_fill.a * clamp(v_radius - d + 0.5, 0.0, 1.0);
    float half_w = max(v_sw, 1.0) * 0.5;
    float sa = v_stroke.a * clamp(half_w - abs(d - v_radius) + 0.5, 0.0, 1.0) * min(v_sw, 1.0);
    vec3 rgb = v_stroke.rgb * sa + v_fill.rgb * fa * (1.0 - sa);
    float a = sa + fa * (1.0 - sa);
    if (a <= 0.0) discard;
    f_color = vec4(rgb, a);
}
"""

SEGMENT_VS = _HEAD + _VS_COMMON + """
in vec2 in_corner;
in vec2 i_a; in vec2 i_b; in float i_width; in vec4 i_color;
out vec2 v_p; out vec2 v_a; out vec2 v_b; out float v_w; out vec4 v_color;
void main() {
    vec2 d = i_b - i_a;
    float len = length(d);
    vec2 dir = len > 1e-4 ? d / len : vec2(1.0, 0.0);
    vec2 nrm = vec2(-dir.y, dir.x);
    float ext = max(i_width, 1.0) * 0.5 + 1.5;
    vec2 mid = (i_a + i_b) * 0.5;
    vec2 p = mid + dir * in_corner.x * (len * 0.5 + ext) + nrm * in_corner.y * ext;
    v_p = p; v_a = i_a; v_b = i_b; v_w = i_width; v_color = i_color;
    gl_Position = to_clip(p);
}
"""
SEGMENT_FS = _HEAD + """
in vec2 v_p; in vec2 v_a; in vec2 v_b; in float v_w; in vec4 v_color;
out vec4 f_color;
void main() {
    vec2 ab = v_b - v_a;
    float t = clamp(dot(v_p - v_a, ab) / max(dot(ab, ab), 1e-8), 0.0, 1.0);
    float d = length(v_p - (v_a + ab * t));
    float half_w = max(v_w, 1.0) * 0.5;
    float a = v_color.a * clamp(half_w - d + 0.5, 0.0, 1.0) * min(v_w, 1.0);
    if (a <= 0.0) discard;
    f_color = vec4(v_color.rgb * a, a);
}
"""

RECT_VS = _HEAD + _VS_COMMON + """
in vec2 in_corner;
in vec4 i_rect; in vec4 i_color;
out vec4 v_color;
void main() {
    vec2 t = in_corner * 0.5 + 0.5;
    vec2 p = mix(i_rect.xy, i_rect.zw, t);
    v_color = i_color;
    gl_Position = to_clip(p);
}
"""
RECT_FS = _HEAD + """
in vec4 v_color; out vec4 f_color;
void main() { f_color = vec4(v_color.rgb * v_color.a, v_color.a); }
"""

IMAGE_VS = _HEAD + _VS_COMMON + """
in vec2 in_corner;
uniform vec4 u_rect;
out vec2 v_uv;
void main() {
    vec2 t = in_corner * 0.5 + 0.5;
    v_uv = vec2(t.x, t.y);
    gl_Position = to_clip(u_rect.xy + t * u_rect.zw);
}
"""
IMAGE_FS = _HEAD + """
uniform sampler2D u_tex; uniform vec4 u_color;
in vec2 v_uv; out vec4 f_color;
void main() {
    vec4 t = texture(u_tex, v_uv);
    float a = t.a * u_color.a;
    f_color = vec4(t.rgb * u_color.rgb * a, a);
}
"""

BLUR_VS = _HEAD + """
in vec2 in_corner; out vec2 v_uv;
void main() { v_uv = in_corner * 0.5 + 0.5; gl_Position = vec4(in_corner, 0.0, 1.0); }
"""
BLUR_FS = _HEAD + """
uniform sampler2D u_tex; uniform vec2 u_step; uniform float u_weights[10]; uniform int u_radius;
in vec2 v_uv; out vec4 f_color;
void main() {
    vec4 acc = texture(u_tex, v_uv) * u_weights[0];
    for (int i = 1; i <= u_radius; i++) {
        acc += texture(u_tex, v_uv + u_step * float(i)) * u_weights[i];
        acc += texture(u_tex, v_uv - u_step * float(i)) * u_weights[i];
    }
    f_color = acc;
}
"""

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def ui_scale(cfg):
    """'auto' (default): 1 at 720 lines, 1.5 at 1080, 2 at 1440, 3 at 2160."""
    v = cfg.get("ui_scale", "auto")
    if v in (None, "auto"):
        return max(1.0, cfg["height"] / 720.0)
    return max(0.25, float(v))


def sim_size(cfg):
    """Canvas size the simulation runs on (screen size / ui scale)."""
    k = ui_scale(cfg)
    return int(round(cfg["width"] / k)), int(round(cfg["height"] / k))


def java_medium_date(ms, utc=False):
    """DateFormat.getDateInstance() in en_US: 'Jul 1, 2008' (no platform strftime quirks)."""
    if utc:
        d = datetime.datetime.fromtimestamp(ms / 1000.0, datetime.timezone.utc)
    else:
        d = datetime.datetime.fromtimestamp(ms / 1000.0)
    return "%s %d, %d" % (_MONTHS[d.month - 1], d.day, d.year)


def java_alpha(life, wrap):
    """Alpha byte Processing used for fill/tint/stroke(int colour, life).

    colorCalcARGB() did not clamp: alpha = (int)(255 * (life / 255)) and only the
    low 8 bits survived the << 24 shift, so a life of 300 gave alpha 44.  That
    is the 'flashing' noted in the original TODO.  wrap=False clamps instead."""
    a = np.asarray(life, np.float32)
    if wrap:
        ai = (np.float32(255.0) * (a / np.float32(255.0))).astype(np.int64)
        return (ai & 255).astype(np.float32)
    return np.clip(a, 0, 255)


def highlight_rgb(rgb):
    """Processing: colorMode(HSB); tint(hue(c), saturation(c) - 192, 255)."""
    r, g, b = [x / 255.0 for x in rgb]
    h, s, _ = colorsys.rgb_to_hsv(r, g, b)
    s2 = max(s * 255 - 192, 0) / 255.0
    return [x * 255 for x in colorsys.hsv_to_rgb(h, s2, 1.0)]


# ---------------------------------------------------------------------------
class Fonts:
    """pygame.font based text -> texture cache."""

    def __init__(self, ctx, cfg):
        import pygame
        pygame.font.init()
        self.pg = pygame
        self.ctx = ctx
        self.cfg_font = cfg["font"]
        k = ui_scale(cfg)
        self.normal = self._load(cfg["font"], round(cfg["font_size"] * k))
        self.bold = self._load(cfg.get("bold_font") or cfg["font"], round(cfg["bold_font_size"] * k))
        self.cache = {}

    # Java's logical "SansSerif" font is DejaVu Sans on Linux (Arial on Windows).
    # DejaVu Sans is bundled, so names look the same everywhere and accented
    # letters (r with caron, Polish, Turkish, Greek, Cyrillic) never turn into boxes.
    _SANS_FILES = [
        os.path.join(ASSETS, "fonts", "DejaVuSans.ttf"),
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arial.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]

    def _load(self, name, size):
        # Java point size == pixel size at 72 dpi; pygame sizes are pixels too.
        size = int(size)
        if name and os.path.isfile(name):                  # a .ttf path
            return self.pg.font.Font(name, size)
        if not name or name.lower() in ("sansserif", "sans-serif", "sans", "dialog"):
            for path in self._SANS_FILES:
                if os.path.isfile(path):
                    return self.pg.font.Font(path, size)
            return self.pg.font.SysFont("arial,dejavusans,liberationsans,helvetica,freesans", size)
        return self.pg.font.SysFont(name, size)

    _BOLD_FILES = [
        os.path.join(ASSETS, "fonts", "DejaVuSans-Bold.ttf"),
        os.path.join(os.environ.get("WINDIR", r"C:\\Windows"), "Fonts", "arialbd.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ]

    def sized(self, size, bold=False):
        """Extra font sizes for cards (cached)."""
        key = (int(size), bool(bold))
        cache = self.__dict__.setdefault("_sized", {})
        if key not in cache:
            name = self.cfg_font
            f = None
            if bold and (not name or name.lower() in ("sansserif", "sans-serif", "sans", "dialog")):
                for path in self._BOLD_FILES:
                    if os.path.isfile(path):
                        f = self.pg.font.Font(path, key[0])
                        break
            if f is None:
                f = self._load(name, key[0])
                if bold:
                    f.set_bold(True)
            cache[key] = f
        return cache[key]

    _FALLBACK_NAMES = "notosanscjksc,notosanscjkjp,notosanscjk,notosanscjkkr,sourcehansans,sourcehansanssc," \
                      "droidsansfallback,wenquanyizenhei,wenquanyimicrohei,unifont,microsoftyahei,msgothic,malgungothic"
    _GENERAL_NAMES = "notosans,dejavusans,freesans,segoeui,arialunicodems,arial,liberationsans,unifont"

    @staticmethod
    def _needs_cjk(text):
        for ch in text:
            o = ord(ch)
            if 0x2E80 <= o <= 0x9FFF or 0xAC00 <= o <= 0xD7AF or 0xF900 <= o <= 0xFAFF or 0xFF00 <= o <= 0xFFEF \
                    or 0x20000 <= o <= 0x2FFFF:
                return True
        return False

    def _missing(self, font, ch):
        """True if `font` has no glyph for `ch`.

        pygame reports no error for a missing glyph - it draws the font's
        'no glyph' box - so compare the character with a code point no font
        has (U+FFFF): same picture = missing."""
        cache = self.__dict__.setdefault("_miss", {})
        key = (id(font), ch)
        hit = cache.get(key)
        if hit is None:
            nd = cache.get((id(font), None))
            if nd is None:
                surf = font.render("\uffff", True, (255, 255, 255))
                nd = (surf.get_size(), self.pg.image.tobytes(surf, "RGBA"))
                cache[(id(font), None)] = nd
            try:
                surf = font.render(ch, True, (255, 255, 255))
                hit = (surf.get_size(), self.pg.image.tobytes(surf, "RGBA")) == nd
            except (self.pg.error, ValueError):
                hit = True
            cache[key] = hit
        return hit

    def _candidate_paths(self, missing):
        """Font files that may draw the missing characters, best first."""
        out = []
        if any(self._needs_cjk(ch) for ch in missing):
            out.append(self.pg.font.match_font(self._FALLBACK_NAMES))
        import shutil
        import subprocess
        if shutil.which("fc-match"):            # fontconfig: a font that has this character
            for ch in missing[:3]:
                try:
                    r = subprocess.run(["fc-match", "-f", "%{file}", ":charset=%x" % ord(ch)],
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5)
                    out.append(r.stdout.decode("utf-8", "replace").strip() or None)
                except (OSError, subprocess.SubprocessError):
                    pass
        out.append(self.pg.font.match_font(self._GENERAL_NAMES))
        if not any(self._needs_cjk(ch) for ch in missing):
            out.append(self.pg.font.match_font(self._FALLBACK_NAMES))
        seen, paths = set(), []
        for p_ in out:
            if p_ and p_ not in seen and os.path.isfile(p_):
                seen.add(p_)
                paths.append(p_)
        return paths

    def _fallback(self, font, text):
        """The font itself, or a same-height font that has every character of
        `text` (decided per character, cached)."""
        if text.isascii():
            return font
        missing = sorted(ch for ch in set(text) if not ch.isspace() and self._missing(font, ch))
        if not missing:
            return font
        fb = self.__dict__.setdefault("_fb", {})
        key = (id(font), "".join(missing))
        if key in fb:
            return fb[key] or font
        fonts = self.__dict__.setdefault("_fb_fonts", {})
        size = font.get_height()
        choice = None
        for path in self._candidate_paths(missing):
            fk = (path, size)
            if fk not in fonts:
                try:
                    fonts[fk] = self.pg.font.Font(path, max(6, int(round(size / 1.17))))
                except (OSError, FileNotFoundError, self.pg.error):
                    fonts[fk] = None
            f = fonts[fk]
            # the whole text is drawn with one font, so it must have every character
            if f is not None and not any(self._missing(f, ch) for ch in set(text) if not ch.isspace()):
                choice = f
                break
        fb[key] = choice
        return choice or font

    def texture(self, text, font, shadow=False):
        key = (text, id(font), bool(shadow))
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        if len(self.cache) > 4000:
            for v in self.cache.values():
                v[0].release()
            self.cache.clear()
        f = self._fallback(font, text)
        if not text.isascii():
            # characters no installed font has (often emoji): leave them out
            # rather than drawing empty boxes
            clean = "".join(ch for ch in text if ch.isspace() or not self._missing(f, ch))
            if clean != text:
                text = " ".join(clean.split()) or " "
        try:
            surf = f.render(text, True, (255, 255, 255))
        except (self.pg.error, ValueError):            # "Text has zero width" on other pygame versions
            surf = self.pg.Surface((1, f.get_height()), self.pg.SRCALPHA, 32)
            shadow = False
        if shadow:
            # dark rim around the letters: readable over glows and lines
            ow = max(1, f.get_height() // 9)
            f.outline = ow
            rim = f.render(text, True, (0, 0, 0))
            f.outline = 0
            out = self.pg.Surface(rim.get_size(), self.pg.SRCALPHA, 32)
            out.blit(rim, (0, 0))
            out.blit(surf, (ow, ow))
            surf = out
        surf = surf.convert_alpha() if self.pg.display.get_init() and self.pg.display.get_surface() else surf
        w, h = surf.get_size()
        if w < 1 or h < 1:
            # text that draws nothing (only invisible characters such as a
            # zero-width space): some pygame versions return an empty image
            surf = self.pg.Surface((1, max(h, 1)), self.pg.SRCALPHA, 32)
            w, h = surf.get_size()
        data = self.pg.image.tobytes(surf, "RGBA", False)
        tex = self.ctx.texture((w, h), 4, data)
        tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        hit = (tex, w, h)
        self.cache[key] = hit
        return hit


def _box_blur(a, r):
    """Separable box blur of a 2-D float array (two passes ~ gaussian)."""
    if r <= 0:
        return a
    for _ in range(2):
        for axis in (0, 1):
            pad = [(0, 0), (0, 0)]
            pad[axis] = (r + 1, r)
            c = np.cumsum(np.pad(a, pad), axis=axis)
            n = a.shape[axis]
            hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
            lo = np.take(c, np.arange(0, n), axis=axis)
            a = (hi - lo) / (2 * r + 1)
    return a


def styled_text_rgba(font, text, rgb, style="outline", glow=True):
    """Title text as an RGBA array.

    outline: glyph outlines only (TRON-like), solid: filled glyphs,
    plain: filled, no glow.  glow adds a soft halo of the same colour."""
    import pygame
    ow = max(1, font.get_height() // 22)
    font.outline = 0
    filled = pygame.surfarray.array_alpha(font.render(text, True, (255, 255, 255))).T.astype(np.float32)
    if style == "outline":
        font.outline = ow
        thick = pygame.surfarray.array_alpha(font.render(text, True, (255, 255, 255))).T.astype(np.float32)
        font.outline = 0
        inner = np.zeros_like(thick)
        h, w = filled.shape
        inner[ow:ow + h, ow:ow + w] = filled
        shape = np.clip(thick - inner, 0, 255)
    else:
        shape = filled
    pad = max(4, font.get_height() // 4) if glow and style != "plain" else 0
    shape = np.pad(shape, pad)
    alpha = shape / 255.0
    if pad:
        halo = _box_blur(alpha, max(2, pad // 2))
        alpha = np.clip(alpha + halo * 0.9, 0, 1)
    rgba = np.zeros(alpha.shape + (4,), np.uint8)
    rgba[..., 0], rgba[..., 1], rgba[..., 2] = rgb[0], rgb[1], rgb[2]
    rgba[..., 3] = (alpha * 255).round().astype(np.uint8)
    return rgba, pad


class Renderer:
    def __init__(self, ctx, cfg):
        self.ctx = ctx
        self.cfg = cfg
        self.w, self.h = cfg["width"], cfg["height"]
        # ui scale: the simulation runs on a (w/k, h/k) canvas and everything in
        # it - dots, rings, lines, names, avatars - is drawn k times larger
        self.k = float(ui_scale(cfg))
        self.wrap = bool(cfg.get("legacy_alpha_wrap", False))
        self.tex = ctx.texture((self.w, self.h), 4)
        self.fbo = ctx.framebuffer(color_attachments=[self.tex])
        self.tmp_tex = ctx.texture((self.w, self.h), 4)
        self.tmp_fbo = ctx.framebuffer(color_attachments=[self.tmp_tex])
        for t in (self.tex, self.tmp_tex):
            t.filter = (moderngl.LINEAR, moderngl.LINEAR)
            t.repeat_x = t.repeat_y = False

        quad = np.array([-1, -1, 1, -1, -1, 1, 1, 1], "f4")
        self.quad = ctx.buffer(quad.tobytes())
        self.progs = {}
        self.inst = {}
        self._prog("sprite", SPRITE_VS, SPRITE_FS, "2f 1f 4f", ["i_center", "i_size", "i_color"])
        self._prog("circle", CIRCLE_VS, CIRCLE_FS, "2f 1f 1f 4f 4f",
                   ["i_center", "i_radius", "i_stroke_w", "i_fill", "i_stroke"])
        self._prog("segment", SEGMENT_VS, SEGMENT_FS, "2f 2f 1f 4f", ["i_a", "i_b", "i_width", "i_color"])
        self._prog("rect", RECT_VS, RECT_FS, "4f 4f", ["i_rect", "i_color"])
        self.image_prog = ctx.program(vertex_shader=IMAGE_VS, fragment_shader=IMAGE_FS)
        self.image_vao = ctx.vertex_array(self.image_prog, [(self.quad, "2f", "in_corner")])
        self.blur_prog = ctx.program(vertex_shader=BLUR_VS, fragment_shader=BLUR_FS)
        self.blur_vao = ctx.vertex_array(self.blur_prog, [(self.quad, "2f", "in_corner")])
        for p in list(self.progs.values()) + [self.image_prog]:
            p["u_size"].value = (float(self.w), float(self.h))

        self.sprite_tex = self._load_sprite()
        self.fonts = Fonts(ctx, cfg)
        self.avatar_px = {}
        self.avatar_tex = {}
        self._styled = {}
        cf = cfg.get("caption_font") or "orbitron"
        self.caption_font_path = (os.path.join(ASSETS, "fonts", "Orbitron-Medium.ttf")
                                  if cf.lower() == "orbitron" else cf)

    # ------------------------------------------------------------------
    def _prog(self, name, vs, fs, fmt, attrs):
        prog = self.ctx.program(vertex_shader=vs, fragment_shader=fs)
        self.progs[name] = prog
        self.inst[name] = None   # (buffer, vao, capacity_bytes)
        self.__dict__["_fmt_" + name] = (fmt, attrs)

    # leading columns that are positions/sizes, per program (scaled for world draws)
    _WORLD_COLS = {"sprite": 3, "circle": 4, "segment": 5, "rect": 4}

    def _draw_instances(self, name, data, world=False):
        """world=True: data is in simulation coordinates; scale to the screen."""
        if data is None or len(data) == 0 or self.__dict__.get("_measuring"):
            return
        data = np.array(data, dtype="f4")
        if world and self.k != 1.0:
            data[:, : self._WORLD_COLS[name]] *= self.k
        raw = data.tobytes()
        entry = self.inst[name]
        if entry is None or entry[2] < len(raw):
            if entry is not None:
                entry[1].release()
                entry[0].release()
            cap = max(len(raw), 4096) * 2
            buf = self.ctx.buffer(reserve=cap, dynamic=True)
            fmt, attrs = self.__dict__["_fmt_" + name]
            vao = self.ctx.vertex_array(self.progs[name], [
                (self.quad, "2f", "in_corner"),
                (buf, fmt + "/i", *attrs),
            ])
            entry = (buf, vao, cap)
            self.inst[name] = entry
        entry[0].write(raw)
        entry[1].render(moderngl.TRIANGLE_STRIP, instances=len(data))

    def _load_sprite(self):
        import pygame
        surf = pygame.image.load(os.path.join(ASSETS, "particle.png"))
        rgb = pygame.surfarray.array3d(surf).transpose(1, 0, 2)      # (h, w, 3)
        # sprite.mask(sprite): Processing uses the blue channel as alpha
        a = rgb[..., 2:3]
        rgba = np.concatenate([rgb, a], axis=2).astype("u1")
        tex = self.ctx.texture((rgba.shape[1], rgba.shape[0]), 4, rgba.tobytes())
        tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        return tex

    # ------------------------------------------------------------------
    def text(self, s, x, y, rgba, font=None, align_x="left", align_y="top", shadow=False):
        if not s or rgba[3] <= 0 or self.__dict__.get("_measuring"):
            return
        font = font or self.fonts.normal
        tex, w, h = self.fonts.texture(s, font, shadow)
        if align_x == "center":
            x -= w / 2.0
        elif align_x == "right":
            x -= w
        if align_y == "center":
            y -= h / 2.0
        elif align_y == "baseline":
            y -= font.get_ascent()
        tex.use(0)
        self.image_prog["u_tex"].value = 0
        self.image_prog["u_rect"].value = (float(round(x)), float(round(y)), float(w), float(h))
        self.image_prog["u_color"].value = tuple(min(max(c, 0), 255) / 255.0 for c in rgba)
        self.image_vao.render(moderngl.TRIANGLE_STRIP)

    def blur(self, radius=3):
        """Processing filter(BLUR, radius) approximation: separable gaussian."""
        r = int(radius)
        sigma = max(radius, 0.5)
        wts = [math.exp(-(i * i) / (2 * sigma * sigma)) for i in range(r * 3 + 1)][:10]
        r = len(wts) - 1
        tot = wts[0] + 2 * sum(wts[1:])
        wts = [w / tot for w in wts] + [0.0] * (10 - len(wts))
        self.blur_prog["u_weights"].value = wts
        self.blur_prog["u_radius"].value = r
        self.ctx.disable(moderngl.BLEND)
        for src, dst, step in ((self.tex, self.tmp_fbo, (1.0 / self.w, 0.0)),
                               (self.tmp_tex, self.fbo, (0.0, 1.0 / self.h))):
            dst.use()
            src.use(0)
            self.blur_prog["u_tex"].value = 0
            self.blur_prog["u_step"].value = step
            self.blur_vao.render(moderngl.TRIANGLE_STRIP)
        self.ctx.enable(moderngl.BLEND)
        self.fbo.use()

    # ------------------------------------------------------------------
    def draw(self, sw, st, info=None):
        """Draw one frame of Swarm `sw` with display state `st` (dict of toggles)."""
        ctx, cfg = self.ctx, self.cfg
        self.fbo.use()
        ctx.viewport = (0, 0, self.w, self.h)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
        bg = [c / 255.0 for c in cfg["background"]]
        ctx.clear(bg[0], bg[1], bg[2], 1.0)

        f, p = sw.files, sw.people
        fc = cfg["font_color"]
        # panels of the previous frame: names keep out of them
        self._panels_prev = getattr(self, "_panels_now", [])
        self._panels_now = []

        # edges (all edges with life > 40)
        if st["show_edges"] and sw.edge_ends:
            el = sw.edge_life[: len(sw.edge_ends)]
            idx = np.nonzero(el > 40)[0]
            if len(idx):
                ends = np.array(sw.edge_ends)[idx]
                a = f.pos[ends[:, 0]]
                b = p.pos[ends[:, 1]]
                alpha = np.minimum(el[idx] + 100, 255) / 255.0
                data = np.column_stack([a, b, np.full(len(idx), 0.35), np.ones((len(idx), 3)), alpha])
                self._draw_instances("segment", data, world=True)

        if getattr(sw, "regions", None) and st.get("show_regions", True):
            self._draw_regions(sw, st)
        living_p = np.nonzero(p.life[: p.n] > 0)[0]
        self._subjects = self._name_subjects(sw) if st.get("commit_text") and \
            self.cfg.get("commit_text", "off") in ("names", "both") else {}
        self._focus = self._update_focus(sw, living_p)
        self._layout = self._layout_names(sw, living_p) if st.get("name_spread") else None
        if st["draw_names_halos"]:
            self._draw_names(sw, living_p, fc)
            self.blur(3 * self.k)
        if st["draw_names_sharp"]:
            self._draw_names(sw, living_p, fc)

        if st.get("ripples"):
            self._draw_ripples(sw)
        self._draw_files(sw, st, fc)

        if st.get("show_engine"):
            fn = self.fonts.normal
            # bottom right, two lines above the date (the line between is for "... later")
            self.text("PhysicsEngineOrderly", self.w - 3,
                      self.h - (2 + abs(fn.get_descent())) - 2 * (fn.get_linesize() + 2),
                      fc + [200], align_x="right", align_y="baseline")
        self._top = 3                       # top-left stack: caption, legend, popular
        self._draw_caption()
        if st["show_debug"]:
            self._draw_debug(sw, fc, info)
        elif st["show_legend"]:
            self._draw_legend(sw, fc)
        self._pop_marks = None
        if st["show_popular"]:
            self._draw_popular(sw, fc)
            self._draw_rank_marks(sw)
        if st.get("show_stats"):
            self._draw_stats(sw, fc)
        if st["show_history"]:
            self._draw_history(sw, st)
        if st.get("show_releases"):
            self._draw_release_banner(sw)
        if st.get("commit_text") and self.cfg.get("commit_text", "off") in ("ticker", "both"):
            self._draw_ticker(sw, fc, st)
        if st["show_date"]:
            fn = self.fonts.normal
            real = sw.time_map.real(sw.prev_date) if getattr(sw, "time_map", None) else sw.prev_date
            self.text(java_medium_date(real, cfg.get("utc_dates", False)),
                      self.w - 3, self.h - (2 + abs(fn.get_descent())), fc + [255],
                      align_x="right", align_y="baseline")
            note = getattr(sw, "last_skip", None)
            if note:
                age = sw.frame - note[0]
                span = int(cfg.get("fps", 24) * 2.5)
                if age < span:
                    from .timeline import humanize_ms
                    a = 255 * min(1.0, (span - age) / (span * 0.4))
                    self.text("... " + humanize_ms(note[1]), self.w - 3,
                              self.h - (2 + abs(fn.get_descent())) - fn.get_linesize() - 2,
                              fc + [a], align_x="right", align_y="baseline")
        self._overlays_last(st, fc)

    def _glow_texture(self):
        """White square whose alpha rises smoothly from the edges to the middle
        (for the neighbourhood cells), made once."""
        tex = getattr(self, "_glow_tex", None)
        if tex is None:
            n = 128
            t = (np.arange(n) + 0.5) / n
            edge = np.minimum(t, 1 - t) * 2                     # 0 at the border, 1 in the middle
            ramp = np.clip(edge / 0.55, 0, 1)
            ramp = ramp * ramp * (3 - 2 * ramp)                 # smoothstep
            a = np.outer(ramp, ramp) * (0.55 + 0.45 * np.outer(edge, edge))
            rgba = np.zeros((n, n, 4), np.uint8)
            rgba[..., :3] = 255
            rgba[..., 3] = np.clip(a * 255, 0, 255).astype(np.uint8)
            tex = self.ctx.texture((n, n), 4, rgba.tobytes())
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self._glow_tex = tex
        return tex

    def _draw_regions(self, sw, st=None):
        """Neighbourhoods.  Grid: the whole frame is tiled 3 x 3; each cell
        glows faintly in its legend colour, the glows reach into the next cell
        so the colours blend into one field, and the folder name is written in
        the caption font, in a neon shade of the cell's colour.  A name whose
        spot is under a panel slides toward the middle of the screen (staying
        in its cell).  Ring: names around an oval."""
        rects = getattr(sw, "region_rect", None)
        if rects:
            k = self.k
            tex = self._glow_texture()
            tex.use(0)
            self.image_prog["u_tex"].value = 0
            for name in sw.regions:
                x0, y0, x1, y1 = [v * k for v in rects[name]]
                cw, ch = x1 - x0, y1 - y0
                c = [v / 255.0 for v in sw.region_color.get(name, (128, 128, 128))]
                # 1.5x the cell: soft edges overlap the neighbours (seamless)
                self.image_prog["u_rect"].value = (float(x0 - cw * 0.25), float(y0 - ch * 0.25),
                                                   float(cw * 1.5), float(ch * 1.5))
                self.image_prog["u_color"].value = (c[0], c[1], c[2], 0.11)
                self.image_vao.render(moderngl.TRIANGLE_STRIP)
            size = max(12, self.h // 34)
            self.region_labels = {}
            # glide only from the frame just drawn (frames skipped: go straight to the spot)
            glide = getattr(self, "_label_frame", None) == sw.frame - 1
            self._label_frame = sw.frame
            # where the panels are this frame (measured, so a first frame knows too)
            panels = self.panel_rects(sw, st) if st is not None else list(getattr(self, "_panels_prev", []))
            for name in sw.regions:
                x0, y0, x1, y1 = [v * k for v in rects[name]]
                tw, th = self._styled_size(name, size)
                cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
                held = self.__dict__.setdefault("_label_goal", {}).get(name)
                wait = self.__dict__.setdefault("_label_wait", {})
                pref = self._label_spot(x0, y0, x1, y1, tw, th, panels)   # its best spot in the cell, if one is clear
                best = pref
                if held is not None and held[2] == (tw, th) and self._label_free(held[0], held[1], tw, th, panels):
                    # still clear: the name stays where it is; it goes back to its
                    # better spot only once that has been clear for 5 seconds
                    far = pref is not None and math.hypot(pref[0] - held[0], pref[1] - held[1]) > 30 * k
                    wait[name] = wait.get(name, 0) + 1 if far else 0
                    if wait[name] < 5 * int(self.cfg.get("fps", 30)):
                        best = held[:2]
                    else:
                        wait[name] = 0
                if best is None:
                    # no free spot in the cell: let it reach half a cell toward the screen centre
                    hw, hh = (x1 - x0) / 2.0, (y1 - y0) / 2.0
                    ex0 = x0 - hw if cx > self.w * 0.6 else x0
                    ex1 = x1 + hw if cx < self.w * 0.4 else x1
                    ey0 = y0 - hh if cy > self.h * 0.6 else y0
                    ey1 = y1 + hh if cy < self.h * 0.4 else y1
                    best = self._label_spot(ex0, ey0, ex1, ey1, tw, th, panels, (cx, cy), force=True)
                self._label_goal[name] = (best[0], best[1], (tw, th))
                # glide to a new spot over about half a second instead of jumping
                cur = self.__dict__.setdefault("_label_at", {}).get(name)
                if cur is None or not glide or math.hypot(best[0] - cur[0], best[1] - cur[1]) < 1.0:
                    cur = best
                else:
                    cur = (cur[0] + 0.15 * (best[0] - cur[0]), cur[1] + 0.15 * (best[1] - cur[1]))
                self._label_at[name] = cur
                px, py = cur
                self.region_labels[name] = (px - tw / 2.0, py - th / 2.0, px + tw / 2.0, py + th / 2.0)
                panels = panels + [self.region_labels[name]]   # names keep clear of each other too
                self.styled(name, size, px, py, self._neon(sw.region_color.get(name, (128, 128, 128))),
                            0.75, "center", "center", style="outline")
            return
        size = max(14, self.h // 26)
        for name in sw.regions:
            ax, ay = sw.region_anchor[name]
            self.styled(name, size, ax * self.k, ay * self.k, [150, 160, 190], 0.22, "center", "center",
                        style="outline")

    @staticmethod
    def _neon(rgb):
        """A bright, saturated shade of a colour (grey stays a light grey)."""
        r, g, b = [x / 255.0 for x in rgb]
        h, s_, v = colorsys.rgb_to_hsv(r, g, b)
        s_ = min(1.0, s_ * 1.15) if s_ > 0.08 else 0.0
        return [int(round(x * 255)) for x in colorsys.hsv_to_rgb(h, s_ * 0.85, 1.0)]

    def _styled_size(self, text, size):
        """Width and height a caption-style text takes (without its glow)."""
        import pygame
        cache = self.__dict__.setdefault("_styled_sz", {})
        key = (text, int(size))
        if key not in cache:
            try:
                f = pygame.font.Font(self.caption_font_path, int(size))
            except (OSError, FileNotFoundError):
                f = self.fonts.sized(int(size), True)
            cache[key] = f.size(text)
        return cache[key]

    def _draw_caption(self):
        cfg = self.cfg
        if cfg.get("caption"):
            size = max(16, self.h // 22)
            hgt = self.styled(cfg["caption"], size, 8, 8, cfg.get("caption_color", [110, 230, 255]))
            self._top = 8 + hgt + 12
            self._panels_now.append((0, 0, 8 + self._styled_w(cfg["caption"], size), self._top))

    def _label_free(self, qx, qy, tw, th, panels):
        """Is a zone name centred at (qx, qy) clear of the panels (with margin) and of the screen edge?"""
        m = 22.0 * self.k
        if qx - tw / 2.0 < 0.03 * self.w or qx + tw / 2.0 > 0.97 * self.w or qy - th / 2.0 < 0.05 * self.h or qy + th / 2.0 > 0.95 * self.h:
            return False
        box = (qx - tw / 2.0 - m, qy - th / 2.0 - m, qx + tw / 2.0 + m, qy + th / 2.0 + m)
        return not any(box[0] < q[2] and q[0] < box[2] and box[1] < q[3] and q[1] < box[3] for q in panels)

    def _label_spot(self, x0, y0, x1, y1, tw, th, panels, centre=None, force=False):
        """The spot for a zone name inside (x0, y0, x1, y1) and inside the
        inner ~90% of the frame, clear of every panel (with the soft backing's
        margin), nearest the area's middle (pulled a little toward the screen
        centre).  None when no spot is clear, unless force (then the least covered)."""
        mx, my = 0.03 * self.w, 0.05 * self.h
        x0, x1 = max(x0, mx), min(x1, self.w - mx)
        y0, y1 = max(y0, my), min(y1, self.h - my)
        cx, cy = centre or ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
        gx = np.linspace(x0 + tw / 2.0 + 10, x1 - tw / 2.0 - 10, 17) if x1 - x0 > tw + 20 else np.array([(x0 + x1) / 2.0])
        gy = np.linspace(y0 + th / 2.0 + 10, y1 - th / 2.0 - 10, 13) if y1 - y0 > th + 20 else np.array([(y0 + y1) / 2.0])
        m = 22.0 * self.k   # the soft backing reaches this far past a panel
        best, best_cost = None, None
        for qx in gx:
            for qy in gy:
                box = (qx - tw / 2.0 - m, qy - th / 2.0 - m, qx + tw / 2.0 + m, qy + th / 2.0 + m)
                cover = sum(max(0.0, min(box[2], q[2]) - max(box[0], q[0])) *
                            max(0.0, min(box[3], q[3]) - max(box[1], q[1])) for q in panels)
                dist = math.hypot(qx - cx, qy - cy) + 0.15 * math.hypot(qx - self.w / 2.0, qy - self.h / 2.0)
                cost = (cover > 0, cover, dist)
                if best_cost is None or cost < best_cost:
                    best, best_cost = (float(qx), float(qy)), cost
        if best_cost is not None and best_cost[0] and not force:
            return None
        return best

    def panel_rects(self, sw, st):
        """Screen rectangles the panels take this frame (caption, legend, file
        list, repository panel, ticker), measured without drawing anything.
        The simulation asks for them every few frames to keep the swarm out
        (keep_clear), the same whether or not a frame is drawn."""
        keep = {k_: self.__dict__.get(k_) for k_ in ("_panels_now", "_top", "_pop_marks", "ticker_drawn", "ticker_base")}
        self._measuring = True
        self._panels_now = []
        fc = self.cfg["font_color"]
        try:
            self._top = 3
            self._draw_caption()
            if st["show_legend"] and not st["show_debug"]:
                self._draw_legend(sw, fc)
            if st["show_popular"]:
                self._draw_popular(sw, fc)
            if st.get("show_stats"):
                self._draw_stats(sw, fc)
            if st.get("commit_text") and self.cfg.get("commit_text", "off") in ("ticker", "both"):
                self._draw_ticker(sw, fc, st)
            rects = list(self._panels_now)
        finally:
            self._measuring = False
            for k_, v in keep.items():
                if v is None:
                    self.__dict__.pop(k_, None)
                else:
                    self.__dict__[k_] = v
        return rects

    def styled(self, text, size, x, y, rgb, alpha=1.0, align_x="left", align_y="top", style=None):
        """Caption-style text (bundled Orbitron by default): outline + glow."""
        import pygame
        style = style or self.cfg.get("caption_style", "outline")
        key = (text, int(size), style, tuple(rgb))
        hit = self._styled.get(key)
        if hit is None:
            try:
                font = pygame.font.Font(self.caption_font_path, int(size))
            except (OSError, FileNotFoundError):
                font = self.fonts.sized(int(size), True)
            px, pad = styled_text_rgba(font, text, rgb, style)
            tex = self.ctx.texture((px.shape[1], px.shape[0]), 4, px.tobytes())
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            hit = (tex, px.shape[1], px.shape[0], pad)
            self._styled[key] = hit
        tex, w, h, pad = hit
        self._last_styled_w = w - 2 * pad
        if self.__dict__.get("_measuring"):
            return h - 2 * pad
        if align_x == "center":
            x -= w / 2.0
        elif align_x == "right":
            x -= w - pad
        else:
            x -= pad
        if align_y == "center":
            y -= h / 2.0
        else:
            y -= pad
        tex.use(0)
        self.image_prog["u_tex"].value = 0
        self.image_prog["u_rect"].value = (float(round(x)), float(round(y)), float(w), float(h))
        self.image_prog["u_color"].value = (1.0, 1.0, 1.0, max(0.0, min(1.0, alpha)))
        self.image_vao.render(moderngl.TRIANGLE_STRIP)
        return h - 2 * pad

    def _styled_w(self, text, size):
        style = self.cfg.get("caption_style", "outline")
        for key, hit in self._styled.items():
            if key[0] == text and key[1] == int(size) and key[2] == style:
                return hit[1] - 2 * hit[3]
        return self.w // 3

    def _begin_plain(self):
        ctx = self.ctx
        self.fbo.use()
        ctx.viewport = (0, 0, self.w, self.h)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
        bg = [c / 255.0 for c in self.cfg["background"]]
        ctx.clear(bg[0], bg[1], bg[2], 1.0)

    def draw_card(self, title, subtitle_lines, alpha, legend=None):
        """Intro card: big title, smaller lines under it, optional colour legend."""
        self._begin_plain()
        fc = self.cfg["font_color"]
        big = self.fonts.sized(max(18, self.h // 14), True)
        mid = self.fonts.sized(max(11, self.h // 40))
        y = self.h * 0.40
        self.styled(title, max(18, self.h // 14), self.w / 2.0, y, self.cfg.get("caption_color", [110, 230, 255]),
                    alpha, "center", "center")
        y += big.get_linesize() * 0.9
        for line in subtitle_lines:
            self.text(line, self.w / 2.0, y, fc + [200 * alpha], mid, "center", "center")
            y += mid.get_linesize() * 1.15
        if legend:
            y += mid.get_linesize() * 0.6
            widths = [mid.size(lab)[0] + 34 for lab, _ in legend]
            x = (self.w - sum(widths)) / 2.0
            rects = []
            for (lab, c), wdt in zip(legend, widths):
                rects.append([x, y - 5, x + 10, y + 5, c[0] / 255.0, c[1] / 255.0, c[2] / 255.0, alpha])
                self.text(lab, x + 16, y, list(c) + [230 * alpha], mid, "left", "center")
                x += wdt
            self._draw_instances("rect", np.array(rects, np.float32))

    def draw_credits(self, heading, entries, alpha):
        """Closing card: heading + people (avatar, name, count) in columns."""
        self._begin_plain()
        fc = self.cfg["font_color"]
        big = self.fonts.sized(max(16, self.h // 22), True)
        f = self.fonts.sized(max(10, self.h // 48))
        top = self.h * 0.12
        self.text(heading, self.w / 2.0, top, fc + [255 * alpha], big, "center", "center")
        if not entries:
            return
        row_h = max(f.get_linesize() + 10, 30)
        avail = self.h - top - big.get_linesize() - 40
        rows = max(1, int(avail // row_h))
        cols = (len(entries) + rows - 1) // rows
        rows = (len(entries) + cols - 1) // cols
        col_w = min(self.w * 0.9 / cols, 420)
        x0 = (self.w - col_w * cols) / 2.0
        y0 = top + big.get_linesize() + 10
        icon = row_h - 6
        for i, (name, count) in enumerate(entries):
            c, rr = i // rows, i % rows
            x = x0 + c * col_w
            y = y0 + rr * row_h
            tex = self._avatar(name) if self.avatar_px else None
            if tex is not None:
                tex.use(0)
                self.image_prog["u_tex"].value = 0
                self.image_prog["u_rect"].value = (float(round(x)), float(round(y)), float(icon), float(icon))
                self.image_prog["u_color"].value = (1.0, 1.0, 1.0, alpha)
                self.image_vao.render(moderngl.TRIANGLE_STRIP)
            self.text(name, x + icon + 10, y + icon / 2.0, fc + [235 * alpha], f, "left", "center")
            self.text(str(count), x + col_w - 24, y + icon / 2.0, fc + [150 * alpha], f, "right", "center")

    def _overlays_last(self, st, fc):
        if st.get("show_help"):
            self._draw_help(st, fc)

    def set_avatars(self, images):
        """images: display name -> (size, size, 4) uint8 RGBA. Uploaded lazily."""
        self.avatar_px = dict(images or {})
        self.avatar_tex = {}

    def _avatar(self, name):
        tex = self.avatar_tex.get(name)
        if tex is None:
            px = self.avatar_px.get(name)
            if px is None:
                return None
            tex = self.ctx.texture((px.shape[1], px.shape[0]), 4, px.tobytes())
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self.avatar_tex[name] = tex
        return tex

    # ------------------------------------------------------------------
    # names: alpha, commit subjects, overlap-free placement
    def _name_alpha(self, sw, i):
        life = int(sw.people.life[i])
        a = float(java_alpha(life, self.wrap))
        focus = getattr(self, "_focus", None)
        if focus is not None:
            a *= 0.55 + 0.45 * focus.get(int(i), 0.0)
        if self.cfg.get("dim_idle_names"):
            # bright while active, settles to ~40% while idle, then the usual fade
            frac = life / float(sw.person_life0 or 1)
            a *= 0.4 + 0.6 * min(max((frac - 0.3) / 0.5, 0.0), 1.0)
        return a

    def _name_font(self, sw, i):
        return self.fonts.bold if sw.people.life[i] >= sw.person_min_bold else self.fonts.normal

    def subject_text(self, text):
        """One line, cut at subject_length characters."""
        text = " ".join((text or "").split())
        n = int(self.cfg.get("subject_length", 64) or 0)
        if n and len(text) > n:
            text = text[: max(n - 3, 1)].rstrip() + "..."
        return text

    def _name_subjects(self, sw):
        """person -> (subject, alpha 0..1) for the newest commits (commit_text_max of them)."""
        fps = float(self.cfg.get("fps", 24))
        span = max(1.0, float(self.cfg.get("commit_text_seconds", 3.0)) * fps)
        limit = int(self.cfg.get("commit_text_max", 3) or 0)
        out = {}
        if not limit or not sw.subjects:
            return out
        for frame, pi, sha, _ in reversed(sw.commit_feed):
            age = sw.frame - frame
            if age >= span:
                break
            if pi in out or sw.people.life[pi] <= 0:
                continue
            subj = self.subject_text(sw.subject(sha))
            if not subj:
                continue
            fade = min(1.0, (span - age) / (span * 0.3), (age + 1) / max(1.0, fps * 0.2))
            out[pi] = (subj, max(0.0, fade))
            if len(out) >= limit:
                break
        return out

    def _update_focus(self, sw, living_p):
        """avatar_focus N: pictures only for the N most active people lately and
        the 6 most recent committers (last 1.5 seconds); the others show their name,
        a little dimmer.  person -> 0..1, eased so pictures fade in and out."""
        n = int(self.cfg.get("avatar_focus", 0) or 0)
        if not n or not self.avatar_px:
            return None
        fps = float(self.cfg.get("fps", 24))
        want = {pi for _, _, pi in sw.active_people(n)} if sw.window_ms else set()
        if not want:                                   # no window: most changes so far
            t = sw.people.touches[: sw.people.n]
            want = set(np.argsort(-t)[:n].tolist())
        # plus the people committing right now: the 6 most recent, within 1.5 seconds
        recent = sorted(((fr, pi) for pi, (fr, _) in sw.person_commit.items() if sw.frame - fr < fps * 1.5),
                        reverse=True)[:6]
        want.update(pi for _, pi in recent)
        self._focus_want = want
        state = self.__dict__.setdefault("_focus_state", {})
        last = self.__dict__.get("_focus_frame")
        if last is not None and sw.frame < last:
            state.clear()
        k = 1.0 - 0.85 ** max(1, sw.frame - (last if last is not None else sw.frame - 1))
        self._focus_frame = sw.frame
        out = {}
        for pi in living_p:
            pi = int(pi)
            a = state.get(pi, 1.0 if pi in want else 0.0)
            a += ((1.0 if pi in want else 0.0) - a) * k
            state[pi] = out[pi] = a
        for pi in list(state):
            if pi not in out:
                del state[pi]
        return out

    def _subject_font(self):
        f = getattr(self, "_sfont", None)
        if f is None:
            f = self.fonts.sized(max(8, int(round(self.fonts.normal.get_height() / 1.17 * 0.92))))
            self._sfont = f
        return f

    def _layout_names(self, sw, living_p):
        """Screen offset per person so names do not overlap.

        Only the name moves, and only a little (at most about two lines down,
        one up when there is no avatar above, or a short step sideways), so it
        always stays with its avatar.  The commit subject hangs under the name
        and never moves it: if it would cover another name it is drawn faint.
        The most active names keep their place; a name with no free place
        nearby is drawn dimmer.  Offsets glide from frame to frame."""
        k = self.k
        p = sw.people
        show_name = self.cfg["show_user_name"]
        state = self.__dict__.setdefault("_lay_state", {})   # person -> [target dx, dy, cur dx, dy]
        if getattr(self, "_lay_frame", None) is not None and sw.frame < self._lay_frame:
            state.clear()                                    # a new run
        # glide 30% of the way per frame (frames not drawn count too)
        glide = 1.0 - 0.7 ** max(1, sw.frame - (getattr(self, "_lay_frame", None) or sw.frame - 1))
        self._lay_frame = sw.frame
        items = []
        avatars = []
        for i in living_p:
            x, y = p.pos[i]
            sx, sy = x * k, y * k
            tex = self._avatar(sw.person_names[i]) if self.avatar_px else None
            focus = getattr(self, "_focus", None)
            if tex is not None and focus is not None and focus.get(int(i), 0.0) < 0.3:
                tex = None                                 # no picture shown: no obstacle
            if tex is not None:
                size = tex.size[0]
                top = sy - (size - (5 if show_name else 15) * k)
                avatars.append((sx - size / 2.0, top, sx + size / 2.0, top + size * 0.85, i))
            if not show_name:
                continue
            a = self._name_alpha(sw, i)
            if a < 10:
                continue
            _, w, h = self.fonts.texture(sw.person_names[i], self._name_font(sw, i),
                                         self.cfg.get("text_shadow", False))
            subj = self._subjects.get(i)
            sub_wh = None
            if subj:
                _, sw_, sh_ = self.fonts.texture(subj[0], self._subject_font(), True)
                sub_wh = (sw_, sh_)
            cx, cy = sx, sy + 10 * k
            prio = (1 if subj else 0, float(p.life[i]))
            items.append((prio, i, cx, cy, w + 4 * k, h, sub_wh, tex is not None))
        items.sort(key=lambda t: (-t[0][0], -t[0][1], t[1]))
        panels = [tuple(q) for q in getattr(self, "_panels_prev", [])]
        # obstacles: placed labels, avatars (except the person's own), panels
        obs = np.zeros((2 * len(items) + len(avatars) + len(panels), 4), np.float32)
        owner = np.full(len(obs), -1, np.int64)
        n_obs = 0
        for q in panels:
            obs[n_obs] = q
            n_obs += 1
        for q in avatars:
            obs[n_obs] = q[:4]
            owner[n_obs] = q[4]
            n_obs += 1
        out = {}
        for prio, i, cx, cy, w, h, sub_wh, has_avatar in items:
            first_h = self._name_font(sw, i).get_linesize()
            step = first_h * 0.6
            # own place first, then where it was last frame (stability), then
            # close by: down, up (only without an avatar above), a short step aside
            cands = [(0.0, 0.0)]
            prev = state.get(i)
            if prev is not None:
                cands.append((prev[0], prev[1]))
            side = min(0.35 * w, 30.0 * k)
            for n in (1, 2, 3):
                cands.append((0.0, n * step))
                if not has_avatar and n <= 2:
                    cands.append((0.0, -n * step))
            for dx in (side, -side):
                cands += [(dx, 0.0), (dx, step), (dx, 2 * step)]
            c = np.array(cands, np.float32)
            x0 = cx + c[:, 0] - w / 2.0
            y0 = cy + c[:, 1] - first_h / 2.0
            rect = np.column_stack([x0, y0, x0 + w, y0 + h])
            ok = (rect[:, 0] >= 0) & (rect[:, 2] <= self.w) & (rect[:, 1] >= 0) & (rect[:, 3] <= self.h)
            if n_obs:
                o = obs[:n_obs]
                hit = ((rect[:, None, 0] < o[None, :, 2]) & (o[None, :, 0] < rect[:, None, 2]) &
                       (rect[:, None, 1] < o[None, :, 3]) & (o[None, :, 1] < rect[:, None, 3]))
                hit &= (owner[:n_obs] != i)[None, :]
                ok &= ~hit.any(axis=1)
            # back home only once home has been free for half a second (no flip-flop)
            home_free = 0
            if prev is not None:
                home_free = (prev[4] + 1) if ok[0] else 0
                prev[4] = home_free
                away = abs(prev[0]) + abs(prev[1]) > 0.5
                if away and ok[1] and home_free < max(2, int(self.cfg.get("fps", 24) * 0.5)):
                    ok[0] = False
            free_ = np.nonzero(ok)[0]
            crowded = not len(free_)
            j = int(free_[0]) if len(free_) else (1 if prev is not None else 0)
            dx, dy = float(c[j, 0]), float(c[j, 1])
            if prev is None:
                prev = [dx, dy, dx, dy, 0]
            else:
                prev[0], prev[1] = dx, dy
                gx = prev[2] + (dx - prev[2]) * glide
                gy = prev[3] + (dy - prev[3]) * glide
                if not crowded and n_obs:
                    # gliding would cross another label: go straight to the free place
                    o = obs[:n_obs]
                    g0, g1 = cx + gx - w / 2.0, cy + gy - first_h / 2.0
                    hit = ((g0 < o[:, 2]) & (o[:, 0] < g0 + w) & (g1 < o[:, 3]) & (o[:, 1] < g1 + h) &
                           (owner[:n_obs] != i))
                    # a short hop only: a name never leaps across its avatar
                    if hit.any() and abs(dx - gx) + abs(dy - gy) <= step:
                        gx, gy = dx, dy
                prev[2], prev[3] = gx, gy
            # what others must avoid is where this name is actually drawn
            x0_ = cx + prev[2] - w / 2.0
            y0_ = cy + prev[3] - first_h / 2.0
            obs[n_obs] = (x0_, y0_, x0_ + w, y0_ + h)
            owner[n_obs] = i
            n_obs += 1
            # the subject hangs under the name; it never moves it, it fades if it would cover something
            sub_fade = 1.0
            if sub_wh is not None:
                sx0 = cx + prev[2] - sub_wh[0] / 2.0
                sy0 = cy + prev[3] + first_h / 2.0
                srect = (sx0, sy0, sx0 + sub_wh[0], sy0 + sub_wh[1])
                o = obs[:n_obs]
                hit = ((srect[0] < o[:, 2]) & (o[:, 0] < srect[2]) & (srect[1] < o[:, 3]) & (o[:, 1] < srect[3]) &
                       (owner[:n_obs] != i))
                if hit.any():
                    sub_fade = 0.3
                else:
                    obs[n_obs] = srect
                    owner[n_obs] = i
                    n_obs += 1
            state[i] = prev
            # no room anywhere near: active names stay readable, idle ones step back
            fade = 1.0
            if crowded:
                fade = 0.5 if prio[0] or p.life[i] >= sw.person_min_bold else 0.22
            out[i] = (prev[2], prev[3], fade, sub_fade)
        for i in list(state):
            if i not in out:
                del state[i]
        return out

    def _draw_names(self, sw, living_p, fc):
        """PersonNode.draw(): name (if ShowUserName), then the avatar above it."""
        p = sw.people
        show_name = self.cfg["show_user_name"]
        layout = getattr(self, "_layout", None)
        subjects = getattr(self, "_subjects", None) or {}
        shadow = self.cfg.get("text_shadow", False)
        self.drawn_labels = []          # (x0, y0, x1, y1, alpha, person) - read by the checks
        for i in living_p:
            life = int(p.life[i])
            x, y = p.pos[i]
            name = sw.person_names[i]
            sx, sy = x * self.k, y * self.k
            if show_name:
                font = self._name_font(sw, i)
                a = self._name_alpha(sw, i)
                dx = dy = 0.0
                sub_f = 1.0
                if layout is not None:
                    dx, dy, f_, sub_f = layout.get(i, (0.0, 0.0, 1.0, 1.0))
                    a *= f_
                ny = sy + 10 * self.k + dy
                self.text(name, sx + dx, ny, fc + [a], font, "center", "center", shadow=shadow)
                _, tw, th = self.fonts.texture(name, font, shadow)
                self.drawn_labels.append((sx + dx - tw / 2.0, ny - th / 2.0, sx + dx + tw / 2.0, ny + th / 2.0, a, int(i)))
                subj = subjects.get(i)
                if subj:
                    self.text(subj[0], sx + dx, ny + font.get_linesize() / 2.0,
                              [175, 215, 235, 235 * subj[1] * sub_f], self._subject_font(), "center", "top", shadow=True)
                    _, tw, th = self.fonts.texture(subj[0], self._subject_font(), True)
                    y1 = ny + font.get_linesize() / 2.0
                    self.drawn_labels.append((sx + dx - tw / 2.0, y1, sx + dx + tw / 2.0, y1 + th,
                                              235 * subj[1] * sub_f, int(i)))
            tex = self._avatar(name) if self.avatar_px else None
            focus = getattr(self, "_focus", None)
            fa = 1.0 if focus is None else focus.get(int(i), 0.0)
            if tex is not None and fa > 0.02:
                size = tex.size[0]
                alpha = min(max(life - 80, 0), 255) / 255.0 * fa  # tint(255,255,255,max(0,life-80))
                if self.cfg.get("dim_idle_avatars"):
                    frac = life / float(sw.person_life0 or 1)
                    alpha *= 0.3 + 0.7 * min(max((frac - 0.3) / 0.5, 0.0), 1.0)
                x, y = sx, sy
                top = y - (size - (5 if show_name else 15) * self.k)
                tex.use(0)
                self.image_prog["u_tex"].value = 0
                self.image_prog["u_rect"].value = (float(round(x - size / 2.0)), float(round(top)),
                                                   float(size), float(size))
                self.image_prog["u_color"].value = (1.0, 1.0, 1.0, alpha)
                self.image_vao.render(moderngl.TRIANGLE_STRIP)

    def growth(self, touches):
        """How much a file has grown: sqrt(changes) in the original (a file
        changed 3,000 times glows 20x wider than a new one).  file_size
        "gentle": the same for the first 4 changes, then logarithmic, so the
        busiest file is only about 2.5x a new one."""
        t = np.maximum(np.asarray(touches, np.float64), 0)
        if self.cfg.get("file_size", "original") != "gentle":
            return np.sqrt(t)
        return np.where(t <= 4, np.sqrt(t), 2.0 + 0.5 * np.log2(np.maximum(t, 4) / 4.0))

    def _draw_files(self, sw, st, fc):
        f = sw.files
        idx = np.nonzero(f.life[: f.n] > 0)[0]
        if not len(idx):
            return
        pos = f.pos[idx]
        last = f.last[idx]
        life = f.life[idx].astype(np.float32)
        touches = f.touches[idx].astype(np.float32)
        col = f.color[idx].astype(np.float32)
        alpha = java_alpha(life, self.wrap) / 255.0
        bold = f.life[idx] >= sw.file_min_bold
        n = len(idx)
        cur_w = np.zeros(n, np.float32)
        P = 2.0  # PARTICLE_SIZE

        if st["draw_files_sharp"]:
            w = np.full(n, 3 * P, np.float32)
            cur_w[:] = w
            w = np.where(bold, w * 2, w)
            stroke = np.zeros((n, 4), np.float32)
            stroke[bold] = [1, 1, 1, 128 / 255.0]
            data = np.column_stack([pos, w / 2, np.ones(n), col / 255.0, alpha, stroke])
            self._draw_instances("circle", data, world=True)

        if st["draw_files_fuzzy"]:
            w = (8 + self.growth(touches) * 4) * P
            cur_w[:] = w
            tint = col.copy()
            ta = alpha.copy()
            if bold.any():
                tint[bold] = [highlight_rgb(c) for c in col[bold]]
                ta[bold] = np.clip(life[bold], 0, 255) / 255.0   # float HSB path clamps
            data = np.column_stack([pos, w, tint / 255.0, ta])
            self.sprite_tex.use(0)
            self.progs["sprite"]["u_tex"].value = 0
            self._draw_instances("sprite", data, world=True)

        if st["draw_files_jelly"]:
            w = self.growth(touches) * P
            cur_w[:] = w
            stroke = np.column_stack([col / 255.0, alpha])
            stroke[bold] = [1, 1, 1, 1]
            data = np.column_stack([pos, w / 2, np.ones(n), np.zeros((n, 4)), stroke])
            self._draw_instances("circle", data, world=True)

        # motion blur line
        d = np.linalg.norm(pos - last, axis=1)
        a = np.minimum(255 * (d / 10), 255) / 10 / 255.0
        m = a > 0
        if m.any():
            data = np.column_stack([pos[m], last[m], cur_w[m] / 4, col[m] / 255.0, a[m]])
            self._draw_instances("segment", data, world=True)

        if st["show_popular"] and self.cfg.get("popular_style", "classic") == "classic":
            q = np.nonzero(f.touches[idx] >= sw.max_touches * 0.5)[0]
            for k in q:
                t = int(touches[k])
                self.text(str(t), pos[k][0] * self.k, (pos[k][1] - (8 + int(self.growth(t)))) * self.k,
                          fc + [200], None, "center", "center")

    def _backing(self, x0, y0, x1, y1):
        """Soft dark plate so panel text stays readable over the swarm: solid
        behind the text, fading out over a margin around it, so it blends into
        whatever lies under it (the swarm, a neighbourhood's glow) with no edge."""
        self.__dict__.setdefault("_panels_now", []).append((x0, y0, x1, y1))
        if self.cfg.get("panel_backing", True) and not self.__dict__.get("_measuring"):
            pad = 18.0 * self.k
            tex = self._plate_texture()
            tex.use(0)
            self.image_prog["u_tex"].value = 0
            self.image_prog["u_rect"].value = (float(x0 - pad), float(y0 - pad),
                                               float(x1 - x0 + 2 * pad), float(y1 - y0 + 2 * pad))
            self.image_prog["u_color"].value = (0.0, 0.0, 0.0, 0.62)
            self._plate_pad = pad
            self.image_vao.render(moderngl.TRIANGLE_STRIP)

    def _plate_texture(self):
        """Alpha 1 in the middle, smooth fall-off to 0 over the outer band.  The
        band is a fixed share of the texture; the drawn plate is the panel plus
        a margin, so most of the fall-off happens in that margin."""
        tex = getattr(self, "_plate_tex", None)
        if tex is None:
            n = 256
            t = (np.arange(n) + 0.5) / n
            edge = np.minimum(t, 1 - t)                         # 0 at the border, 0.5 in the middle
            ramp = np.clip(edge / 0.08, 0, 1)
            ramp = ramp * ramp * (3 - 2 * ramp)
            a = np.outer(ramp, ramp)
            rgba = np.zeros((n, n, 4), np.uint8)
            rgba[..., :3] = 255
            rgba[..., 3] = np.clip(a * 255, 0, 255).astype(np.uint8)
            tex = self.ctx.texture((n, n), 4, rgba.tobytes())
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self._plate_tex = tex
        return tex

    def _legend_font(self):
        """Font for the colour legend: the names font, or Orbitron / a .ttf (--legend-font)."""
        choice = (self.cfg.get("legend_font") or "sans")
        if choice.lower() in ("sans", "default", ""):
            return self.fonts.normal
        f = getattr(self, "_lfont", None)
        if f is None:
            import pygame
            path = os.path.join(ASSETS, "fonts", "Orbitron-Medium.ttf") if choice.lower() == "orbitron" else choice
            try:
                # Orbitron is wide: a slightly smaller size matches the sans line height
                size = self.fonts.normal.get_height() * (0.82 if choice.lower() == "orbitron" else 1.0)
                f = pygame.font.Font(path, max(8, int(round(size))))
            except (OSError, FileNotFoundError):
                f = self.fonts.normal
            self._lfont = f
        return f

    def _draw_legend(self, sw, fc):
        lf = self._legend_font()
        fs = max(lf.get_linesize(), self.fonts.normal.get_linesize()) - 2   # line pitch, scales with the ui
        y0 = self._top
        if self.cfg.get("popular_style") == "ranked":
            wmax = max([lf.size(l)[0] for l, _ in sw.colors.legend] + [60]) + fs + 8
            self._backing(0, y0 - 2, wmax, y0 + (len(sw.colors.legend) + 1) * (fs + 2) + 4)
        self.text("Legend:", 3, y0, fc + [255], lf)
        for i, (label, c1) in enumerate(sw.colors.legend):
            self.text(label, fs, y0 + (i + 1) * (fs + 2), list(c1) + [220], lf)
        self._top = y0 + (len(sw.colors.legend) + 1) * (fs + 2) + 10

    def _draw_popular(self, sw, fc):
        pop = sw.popular(int(self.cfg.get("popular_count", 10)))
        if self.cfg.get("popular_style", "classic") == "ranked":
            return self._draw_popular_ranked(sw, fc, pop)
        if self.cfg.get("popular_position") == "left":
            # Stack Exchange patch: under the legend, left aligned (below it, wherever it ends)
            y0 = max(self._top, 105 * self.k)
            lh = self.fonts.normal.get_linesize()
            self.text("Popular Nodes (touches):", 3, y0, fc + [200])
            for i, (name, t, _) in enumerate(pop, 1):
                self.text("%s  (%d)" % (name, t), 10, y0 + lh * i, fc + [200])
        else:
            self.text("Popular Nodes (touches):", self.w - 120, 0, fc + [200], align_x="right")
            for i, (name, t, _) in enumerate(pop, 1):
                self.text("%s  (%d)" % (name, t), self.w - 100, 10 * i, fc + [200], align_x="right")

    def _draw_popular_ranked(self, sw, fc, pop):
        """Numbered list; the same numbers mark those files in the swarm."""
        acc = list(self.cfg.get("accent", [255, 196, 64]))
        f = self.fonts.normal
        lh = f.get_linesize() + 1
        days = self.cfg.get("popular_window_days")
        what = "folders" if self.cfg.get("_folders") else "files"
        title = ("Most active %s (last %g days)" % (what, days)) if days else "Most changed " + what
        y0 = self._top
        # keep the list above the histogram
        room = int((self.hist_top() - 8 - y0) // lh) - 1
        pop = pop[:max(room, 0)]
        alive = sw.files.life
        nw = f.size("10")[0] + 6
        wmax = max([f.size(title)[0] + 6] + [8 + nw + f.size(nm)[0] + 8 + f.size(str(n))[0] + 6
                                             for nm, n, _ in pop])
        self._backing(0, y0 - 3, wmax, y0 + (len(pop) + 1) * lh + 3)
        self.text(title, 3, y0, fc + [220])
        for i, (name, n, fi) in enumerate(pop, 1):
            y = y0 + i * lh
            on = alive[fi] > 0
            self.text(str(i), 6 + nw - 4, y, acc + [255 if on else 120], align_x="right")
            self.text(name, 8 + nw, y, fc + [220 if on else 110])
            self.text(str(n), 8 + nw + f.size(name)[0] + 8, y, [150, 150, 150, 200 if on else 100])
        self._top = y0 + (len(pop) + 1) * lh + 8
        marks = int(self.cfg.get("popular_marks", 10))
        self._pop_marks = [(i, fi) for i, (_, _, fi) in enumerate(pop, 1) if alive[fi] > 0 and i <= marks]

    def _draw_stats(self, sw, fc):
        """Top-right panel: repository numbers so far, the last N days, the
        change mix, newcomers, and the most active people."""
        f = self.fonts.normal
        hf = self._legend_font()
        lh = f.get_linesize() + 1
        st = sw.stats()
        tot = getattr(sw, "totals", None) or {}
        days = st["window_days"]
        grey = [160, 160, 160]
        acc = list(self.cfg.get("accent", [255, 196, 64]))
        rows = []                                   # (kind, payload)

        def num(n):
            return "{:,}".format(int(n))

        rows.append(("head", "Repository"))
        rows.append(("kv", ("Commits", num(st["commits"]), "of " + num(tot["commits"]) if tot else "")))
        rows.append(("kv", ("People", num(st["people"]), ("of %s" % num(tot["people"])) if tot else "")))
        rows.append(("kv", ("Folders" if self.cfg.get("_folders") else "Files", num(st["files"]),
                            ("of %s" % num(tot["files"])) if tot else "")))
        if days:
            rows.append(("gap", None))
            rows.append(("head", "Last %g days" % days))
            rows.append(("kv", ("Commits", num(st["w_commits"]), "")))
            rows.append(("kv", ("Active people", num(st["w_people"]), "")))
            rows.append(("kv", ("Folders changed" if self.cfg.get("_folders") else "Files changed",
                                num(st["w_files"]), "")))
            s_ = st["w_status"]
            parts = []
            for code, word in (("A", "added"), ("M", "changed"), ("D", "deleted"), ("R", "moved")):
                if s_.get(code):
                    parts.append("%s %s" % (num(s_[code]), word))
            if parts:
                rows.append(("text", (",  ".join(parts), "")))
            if st["w_changes"]:
                rows.append(("mix", st["w_colour"]))
            if st["newcomers"]:
                nm = st["newcomers"][-3:]
                more = len(st["newcomers"]) - len(nm)
                rows.append(("text", ("New: " + ", ".join(nm) + (" +%d" % more if more else ""), "")))
            n_people = int(self.cfg.get("people_count", 0) or 0)
            if n_people:
                act = sw.active_people(n_people)
                if act:
                    rows.append(("gap", None))
                    rows.append(("head", "Most active people"))
                    for i, (name, n, pi) in enumerate(act, 1):
                        rows.append(("rank", (i, name, n)))

        # measure
        pad = 8
        width = 0
        for kind, pl in rows:
            if kind == "head":
                width = max(width, hf.size(pl)[0])
            elif kind == "kv":
                width = max(width, f.size(pl[0])[0] + 16 + f.size(pl[1] + "  " + pl[2])[0])
            elif kind == "text":
                width = max(width, f.size(pl[0])[0] + (f.size("  " + pl[1])[0] if pl[1] else 0))
            elif kind == "rank":
                width = max(width, f.size("20 ")[0] + f.size(pl[1])[0] + 12 + f.size(str(pl[2]))[0])
        width = max(width, int(220 * self.k))
        height = sum({"gap": lh // 2, "mix": lh}.get(k, lh) for k, _ in rows)
        x0 = self.w - width - pad - 3
        y0 = 8
        self._backing(x0 - pad, y0 - 4, self.w, y0 + height + 4)
        y = y0
        key_w = max([f.size(pl[0])[0] for k, pl in rows if k == "kv"] + [0]) + 16
        legend = {tuple(c): lab for lab, c in sw.colors.legend}
        for kind, pl in rows:
            if kind == "gap":
                y += lh // 2
                continue
            if kind == "head":
                self.text(pl, x0, y, fc + [235], hf)
            elif kind == "kv":
                self.text(pl[0], x0, y, grey + [220])
                self.text(pl[1], x0 + key_w, y, fc + [235])
                if pl[2]:
                    self.text(pl[2], x0 + key_w + f.size(pl[1] + "  ")[0], y, grey + [170])
            elif kind == "text":
                self.text(pl[0], x0, y, fc + [220])
                if pl[1]:
                    self.text(pl[1], x0 + f.size(pl[0] + "  ")[0], y, grey + [150])
            elif kind == "mix":
                total = float(sum(pl.values())) or 1.0
                bx, bw, bh = x0, width, max(4, int(lh * 0.45))
                rects = []
                for ck, n in sorted(pl.items(), key=lambda kv: -kv[1]):
                    seg = bw * n / total
                    c = ((ck >> 16) & 255) / 255.0, ((ck >> 8) & 255) / 255.0, (ck & 255) / 255.0
                    rects.append([bx, y + (lh - bh) / 2.0, bx + seg, y + (lh + bh) / 2.0, c[0], c[1], c[2], 0.95])
                    bx += seg
                self._draw_instances("rect", np.array(rects, np.float32))
            elif kind == "rank":
                i, name, n = pl
                nw = f.size("20")[0]
                self.text(str(i), x0 + nw, y, acc + [255], align_x="right")
                self.text(name, x0 + nw + 8, y, fc + [230])
                self.text(str(n), x0 + width, y, grey + [190], align_x="right")
            y += lh

    def _draw_rank_marks(self, sw):
        """Accent ring + rank number on the files listed in the panel."""
        marks = getattr(self, "_pop_marks", None)
        if not marks:
            return
        acc = [c / 255.0 for c in self.cfg.get("accent", [255, 196, 64])]
        f = sw.files
        rows = []
        ticks = []
        flash = self.cfg.get("status_flash") and hasattr(sw, "file_touch_frame")
        span = max(1.0, float(self.cfg.get("fps", 24)) * 1.0)
        for rank, fi in marks:
            x, y = f.pos[fi]
            # just outside the file's own ring (gentle) or the original fixed size
            if self.cfg.get("file_size", "original") == "gentle":
                r = float(self.growth(f.touches[fi])) + 3.0
                base_w = 1.1
            else:
                r = min(7 + math.sqrt(f.touches[fi]) * 1.3, 22)
                base_w = 1.5
            col, width, alpha = acc, base_w, 0.9
            if flash:
                age = sw.frame - sw.file_touch_frame[fi]
                if 0 <= age < span:
                    t = (age / span) ** 0.7
                    sc = self.STATUS_RGB.get(sw.file_status[fi], self.STATUS_RGB["M"])
                    col = [sc[j] / 255.0 * (1 - t) + acc[j] * t for j in range(3)]
                    width = base_w + 1.0 * (1 - t)       # colour carries the news, not size
                    alpha = 1.0
            rows.append([x, y, r, width, 0, 0, 0, 0, col[0], col[1], col[2], alpha])
            if self.cfg.get("author_ticks") and hasattr(sw, "file_authors"):
                n = min(int(sw.file_authors(fi)), 12)
                for j in range(n):
                    ang = -math.pi / 2 + j * 2 * math.pi / n
                    ca, sa = math.cos(ang), math.sin(ang)
                    r0, r1 = r + 1.5, r + 3.5
                    ticks.append([x + ca * r0, y + sa * r0, x + ca * r1, y + sa * r1, 1.0,
                                  acc[0], acc[1], acc[2], 0.8])
        self._draw_instances("circle", np.array(rows, np.float32), world=True)
        if ticks:
            self._draw_instances("segment", np.array(ticks, np.float32), world=True)
        font = self.fonts.bold
        shadow = self.cfg.get("text_shadow", False)
        taken = []
        for (rank, fi), row in zip(marks, rows):
            x, y, r = row[0] * self.k, row[1] * self.k, row[2] * self.k
            _, tw, th = self.fonts.texture(str(rank), font, shadow)
            asc = font.get_ascent()
            d = r * 0.75 + 2
            # upper right as before; another corner if a number is already there
            best = None
            for sx_, sy_ in ((1, -1), (-1, -1), (1, 1), (-1, 1)):
                bx = x + d if sx_ > 0 else x - d - tw
                by = y - d if sy_ < 0 else y + d + asc
                box = (bx, by - asc, bx + tw, by - asc + th)
                if not any(box[0] < q[2] and q[0] < box[2] and box[1] < q[3] and q[1] < box[3] for q in taken):
                    best = (bx, by, box)
                    break
            if best is None:
                bx, by = x + d, y - d
                best = (bx, by, (bx, by - asc, bx + tw, by - asc + th))
            taken.append(best[2])
            self.text(str(rank), best[0], best[1], [int(c * 255) for c in acc] + [255],
                      font, align_x="left", align_y="baseline", shadow=shadow)

    STATUS_RGB = {"A": (90, 230, 120), "M": (255, 255, 255), "D": (255, 80, 80),
                  "R": (90, 170, 255), "C": (90, 170, 255)}

    # ------------------------------------------------------------------
    def _draw_ticker(self, sw, fc, st):
        """Bottom right, above the date: the latest commit subjects, newest last."""
        n = int(self.cfg.get("ticker_lines", 4) or 0)
        if not n or not sw.subjects or not sw.commit_feed:
            return
        fps = float(self.cfg.get("fps", 24))
        keep = fps * 20.0                    # lines fade out after 20 seconds of video
        lines = []
        for frame, pi, sha, _ in reversed(sw.commit_feed):
            age = sw.frame - frame
            if age > keep:
                break
            subj = self.subject_text(sw.subject(sha))
            if subj:
                lines.append((subj, sw.person_names[pi], age))
            if len(lines) >= n:
                break
        if not lines:
            return
        f = self.fonts.normal
        lh = f.get_linesize() + 1
        self.ticker_drawn = len(lines)
        # just above the date; one more line up while the engine name or a "... later" note shows
        up = 1
        note = getattr(sw, "last_skip", None)
        if note and sw.frame - note[0] < int(self.cfg.get("fps", 24) * 2.5):
            up = 2                                    # "... 3 months later" sits on line 1
        if st.get("show_engine"):
            up = 3                                    # engine name sits on line 2
        base = self.h - (2 + abs(f.get_descent())) - up * (f.get_linesize() + 2)
        self.ticker_base = base
        shadow = True
        grey = [185, 200, 210]
        wmax = 0
        for subj, who, _ in lines:
            wmax = max(wmax, self.fonts.texture(who, f, shadow)[1] + 6 + self.fonts.texture(subj + "  -", f, shadow)[1])
        top = base - (len(lines) - 1) * lh - f.get_ascent() - 3
        self._backing(self.w - wmax - 10, top, self.w, base + abs(f.get_descent()) + 3)
        for row, (subj, who, age) in enumerate(lines):
            y = base - row * lh
            a = 255 * min(1.0, (keep - age) / (keep * 0.35)) * max(0.35, 1.0 - 0.09 * row)
            _, wn, _ = self.fonts.texture(who, f, shadow)
            self.text(who, self.w - 3, y, fc + [a], f, "right", "baseline", shadow=shadow)
            self.text(subj + "  -", self.w - 3 - wn - 6, y, grey + [a * 0.9], f, "right", "baseline", shadow=shadow)

    def _draw_release_banner(self, sw):
        """Release tag in the caption font, top centre, for a few seconds."""
        b = getattr(sw, "release_banner", None)
        if not b:
            return
        fps = float(self.cfg.get("fps", 24))
        span = fps * 3.0
        age = sw.frame - b[0]
        if age < 0 or age >= span:
            return
        a = min(1.0, (age + 1) / (fps * 0.3), (span - age) / (fps * 0.8))
        size = max(18, self.h // 20)
        acc = list(self.cfg.get("accent", [255, 196, 64]))
        f = self.fonts.normal
        self.text("release", self.w / 2.0, 10, [200, 200, 200, 220 * a], f, "center", "top", shadow=True)
        self.styled(b[1], size, self.w / 2.0, 12 + f.get_linesize(), acc, a, "center", "top")

    def _draw_ripples(self, sw):
        """Expanding ring around a person at each commit, in the commit's colour mix."""
        if not sw.ripples:
            return
        p = sw.people
        rows = []
        span = float(sw.ripple_frames)
        for pi, start, nfiles in sw.ripples:
            t = (sw.frame - start) / span
            if t < 0 or t > 1 or p.life[pi] <= 0:
                continue
            x, y = p.pos[pi]
            reach = 40 + 14 * math.log2(1 + nfiles)
            r = 10 + t * reach
            c = np.clip(np.array(sw.person_flavor[pi]) * 0.6 + 255 * 0.4, 0, 255) / 255.0
            a = 0.75 * (1 - t) ** 1.5
            rows.append([x, y, r, 1.6, 0, 0, 0, 0, c[0], c[1], c[2], a])
        if rows:
            self._draw_instances("circle", np.array(rows, np.float32), world=True)

    def hist_top(self):
        """Screen y of the tallest the histogram may get (its cap)."""
        cap = self.cfg.get("histogram_max")
        if not cap or not self.cfg.get("show_history", True):
            return self.h
        return self.h * (1.0 - float(cap))

    def _draw_history(self, sw, st=None):
        rects = []
        h = self.h / self.k
        hs = float(self.cfg.get("histogram_scale", 1) or 1)
        cap = self.cfg.get("histogram_max")
        cap_px = (h * float(cap)) if cap else None
        for x, bins in enumerate(sw.history):
            if not bins:
                continue
            start = 0
            run = bins[0]
            end = 0
            # FIX: the Java loop never drew the last run of each column
            for c in bins + [None]:
                if c == run:
                    end += 1
                    continue
                r, g, b = (run >> 16) & 255, (run >> 8) & 255, run & 255
                y_hi, y_lo = end * hs, start * hs
                if cap_px is not None:
                    y_hi, y_lo = min(y_hi, cap_px), min(y_lo, cap_px)
                if y_hi > y_lo or cap_px is None:
                    rects.append([(x - 1) * hs, h - y_hi - 3 - 1, (x + 1) * hs, h - y_lo - 3 + 1,
                                  r / 255.0, g / 255.0, b / 255.0, 1.0])
                start = end
                end += 1
                run = c
        if rects:
            self._draw_instances("rect", np.array(rects, np.float32), world=True)
        if st and st.get("show_releases") and getattr(sw, "history_tags", None):
            self._draw_release_marks(sw, h, hs, cap_px)

    def _draw_release_marks(self, sw, h, hs, cap_px):
        """Thin accent line over the histogram at each release; the released
        name over the latest banners (dense build tags get short ticks only)."""
        cols = [(x, t) for x, t in enumerate(sw.history_tags) if t]
        if not cols:
            return
        acc = [c / 255.0 for c in self.cfg.get("accent", [255, 196, 64])]
        dense = len(cols) > max(8, len(sw.history_tags) // 10)
        top = cap_px if cap_px is not None else h * 0.2
        rects = []
        bannered = getattr(sw, "bannered", set())
        for x, t in cols:
            big = not dense or any(n in bannered for n in t)
            hgt = top if big else 5.0
            rects.append([x * hs - 0.4, h - 3 - hgt, x * hs + 0.4, h - 3, acc[0], acc[1], acc[2], 0.75 if big else 0.35])
        self._draw_instances("rect", np.array(rects, np.float32), world=True)
        f = self.fonts.normal
        right = None
        for x, t in reversed(cols):
            named = [n for n in t if n in bannered] if dense else list(t)
            if not named:
                continue
            label = named[-1]
            sx = x * hs * self.k
            _, w, _ = self.fonts.texture(label, f, True)
            if right is not None and sx + w / 2.0 + 6 > right:
                continue
            self.text(label, sx, (h - 3 - top) * self.k - 2, [int(c * 255) for c in acc] + [230], f,
                      "center", "baseline", shadow=True)
            right = sx - w / 2.0

    def _draw_debug(self, sw, fc, info):
        lines = ["Nodes: %d" % sw.files.n, "People: %d" % sw.people.n,
                 "Queue: %d" % (len(sw.events) - sw.ev_i),
                 "Last render time: %s" % ((info or {}).get("ms", "-"))]
        for i, s in enumerate(lines):
            self.text(s, 0, self.fonts.normal.get_linesize() * i, fc + [200])

    # (key, what it does, state key or None) - two columns in the panel
    HELP = [
        ("space", "pause / resume", None), ("q, Esc", "quit", None),
        ("a", "name halos (glow)", "draw_names_halos"), ("s", "names", "draw_names_sharp"),
        ("f", "fuzzy files (glow)", "draw_files_fuzzy"), ("j", "jelly files (rings)", "draw_files_jelly"),
        ("S", "sharp files (dots)", "draw_files_sharp"), ("e", "edges (person-file)", "show_edges"),
        ("l", "legend", "show_legend"), ("p", "popular files", "show_popular"),
        ("h", "histogram", "show_history"), ("d", "date", "show_date"),
        ("b", "debug numbers", "show_debug"), ("E", "physics engine name", "show_engine"),
        ("r", "commit ripples", "ripples"), ("i", "repository stats", "show_stats"),
        ("c", "commit messages", "commit_text"), ("t", "release tags", "show_releases"),
        ("n", "spread overlapping names", "name_spread"), ("g", "neighbourhood names", "show_regions"),
        ("?, F1", "this help", "show_help"),
    ]

    def _draw_help(self, st, fc):
        """Centred panel on a dark backing, current on/off state per key."""
        f = self.fonts.normal
        line = f.get_linesize() + 3
        key_w = max(f.size(k)[0] for k, _, _ in self.HELP) + 12
        desc_w = max(f.size(d)[0] for _, d, _ in self.HELP) + 12
        state_w = f.size("off")[0] + 8
        col_w = key_w + desc_w + state_w
        gap = 28
        rows = (len(self.HELP) + 1) // 2
        pad = 16
        title_h = line + 8
        w = 2 * col_w + gap + 2 * pad
        h = title_h + rows * line + 2 * pad
        x0 = int((self.w - w) / 2)
        y0 = int((self.h - h) / 2)
        border = (0.55, 0.55, 0.55, 0.9)
        rects = [[x0, y0, x0 + w, y0 + h, 0.0, 0.0, 0.0, 0.93],
                 [x0, y0, x0 + w, y0 + 1, *border], [x0, y0 + h - 1, x0 + w, y0 + h, *border],
                 [x0, y0, x0 + 1, y0 + h, *border], [x0 + w - 1, y0, x0 + w, y0 + h, *border]]
        self._draw_instances("rect", np.array(rects, np.float32))
        self.text("Keys", x0 + w / 2.0, y0 + pad, fc + [255], self.fonts.bold, align_x="center")
        for i, (key, desc, state) in enumerate(self.HELP):
            col, row = i // rows, i % rows
            cx = x0 + pad + col * (col_w + gap)
            cy = y0 + pad + title_h + row * line
            self.text(key, cx, cy, fc + [255])
            self.text(desc, cx + key_w, cy, fc + [200])
            if state:
                on = bool(st.get(state))
                self.text("on" if on else "off", cx + key_w + desc_w, cy,
                          ([120, 220, 120] if on else [150, 150, 150]) + [230])

    # ------------------------------------------------------------------
    def read_rgb(self):
        """Current frame as (h, w, 3) uint8, top row first."""
        raw = self.fbo.read(components=3, alignment=1)
        img = np.frombuffer(raw, np.uint8).reshape(self.h, self.w, 3)
        return img[::-1]
