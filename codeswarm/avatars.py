"""Avatars: fetch once, cache on disk, hand RGBA pixels to the renderer.

Sources (--avatars):
  github    GitHub picture: from noreply emails directly, else one API call
            per person (repository commit endpoint), then Gravatar fallback
  gravatar  Gravatar by email; people without one get the fallback style
            (identicon by default, as in the original)
  local     DIR/<name>.png (also <login>, <email>; .png/.jpg/.gif), else default pic
  none      no pictures
  auto      github for GitHub repositories, gravatar otherwise

Without a token GitHub allows 60 API calls per hour, so at most
--github-api-budget (default 50) lookups are made per run; set GITHUB_TOKEN
(or GH_TOKEN) to lift that.  Results, including "no picture", are cached
in <cache>/avatars so the next run makes no requests.
"""

import hashlib
import io
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from .identity import github_login
from .util import say, warn

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
# Overridable for tests (tools/p3_check.py points them at a local server)
GRAVATAR_URL = os.environ.get("CODESWARM_GRAVATAR_URL", "https://www.gravatar.com/avatar/")
GITHUB_API = os.environ.get("CODESWARM_GITHUB_API", "https://api.github.com")
GITHUB_AVATARS = os.environ.get("CODESWARM_GITHUB_AVATARS", "https://avatars.githubusercontent.com")
MISS_RETRY_DAYS = 7
UA = "codeswarm-rewrite (+https://github.com)"


def github_slug(source):
    """'owner/repo' if the source is a GitHub repository, else None."""
    s = source.strip()
    m = re.match(r"^(?:https?://|git@|ssh://git@)?github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", s)
    if m:
        return "%s/%s" % (m.group(1), m.group(2))
    if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", s) and not os.path.exists(s):
        return s
    return None


class AvatarStore:
    def __init__(self, cfg, cache_dir, source="", offline=False, token=None, repo_sources=None):
        self.cfg = cfg
        self.size = int(cfg.get("avatar_size", 40))
        self.circular = bool(cfg.get("circular_avatars", True))
        self.fallback = cfg.get("gravatar_fallback", "identicon")
        self.mode = cfg.get("avatars", "auto")
        self.slug = github_slug(source) if source else None
        # several repositories: repo label -> GitHub slug (None for non-GitHub)
        self.repo_slugs = {lab: github_slug(src) for lab, src in (repo_sources or {}).items()}
        if self.slug is None and any(self.repo_slugs.values()):
            self.slug = next(v for v in self.repo_slugs.values() if v)
        if self.mode == "auto":
            self.mode = "github" if self.slug else "gravatar"
        self.offline = offline
        self.token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        self.budget = int(cfg.get("github_api_budget", 50)) if not self.token else 10 ** 9
        self.dir = os.path.join(cache_dir, "avatars")
        os.makedirs(self.dir, exist_ok=True)
        self.lookup_file = os.path.join(self.dir, "github_lookup.json")
        try:
            with open(self.lookup_file, "r", encoding="utf-8") as fh:
                self.lookup = json.load(fh)
        except (OSError, ValueError):
            self.lookup = {}
        self.lock = threading.Lock()
        self.stats = {"cached": 0, "downloaded": 0, "missing": 0, "api_calls": 0, "errors": 0,
                      "local": 0, "rate_limited": False}
        self._mask = None
        self.net_fail = 0
        self.api_allowed = set()
        self.looked_up = []

    # ------------------------------------------------------------------ http
    def _get(self, url, api=False):
        if self.offline:
            return None, 0
        headers = {"User-Agent": UA}
        if api:
            headers["Accept"] = "application/vnd.github+json"
            if self.token:
                headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.read(), 200
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and api:
                with self.lock:
                    self.stats["rate_limited"] = True
                    self.budget = 0
            if e.code != 404:
                with self.lock:
                    self.stats["errors"] += 1
            return None, e.code
        except (urllib.error.URLError, OSError, ValueError):
            with self.lock:
                self.stats["errors"] += 1
                self.net_fail += 1
                # circuit breaker: no network at all -> stop trying, don't wait on every person
                if self.net_fail >= 12 and self.stats["downloaded"] == 0 and not self.offline:
                    self.offline = True
                    self.stats["gave_up"] = True
            return None, 0

    def _cached_download(self, url):
        """Bytes of url from disk cache, else download. None if no image."""
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        img = os.path.join(self.dir, key + ".img")
        miss = os.path.join(self.dir, key + ".miss")
        if os.path.isfile(img):
            with self.lock:
                self.stats["cached"] += 1
            with open(img, "rb") as fh:
                return fh.read()
        if os.path.isfile(miss) and time.time() - os.path.getmtime(miss) < MISS_RETRY_DAYS * 86400:
            return None
        data, status = self._get(url)
        definite_miss = status == 404
        if data:
            tmp = img + ".tmp%d" % threading.get_ident()
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, img)
            with self.lock:
                self.stats["downloaded"] += 1
            return data
        if definite_miss:          # only a real 404 is remembered; network errors retry next run
            open(miss, "w").close()
        return None

    def slug_for(self, person):
        """GitHub owner/repo to ask about this person's sample commit."""
        rp = getattr(person, "commit_repo", "")
        if rp in self.repo_slugs:
            return self.repo_slugs[rp]
        return self.slug

    # --------------------------------------------------------------- sources
    def _gravatar_url(self, email, default):
        h = hashlib.md5((email or "").strip().lower().encode("utf-8")).hexdigest()
        return "%s%s?%s" % (GRAVATAR_URL, h, urllib.parse.urlencode({"s": self.size * 2, "d": default}))

    def _github_url(self, person):
        for e in person.emails:
            login, gid = github_login(e)
            if gid:
                return "%s/u/%d?s=%d" % (GITHUB_AVATARS, gid, self.size * 2)
            if login:
                return "%s/%s?s=%d" % (GITHUB_AVATARS, urllib.parse.quote(login), self.size * 2)
        slug = self.slug_for(person)
        if not slug or not person.commit_sample:
            return None
        key = "%s@%s" % (slug, person.commit_sample)
        with self.lock:
            if key in self.lookup:
                return self.lookup[key] or None
            if self.budget <= 0 or self.offline or person.display not in self.api_allowed:
                return None
            self.budget -= 1
            self.stats["api_calls"] += 1
            self.looked_up.append(person.display)
        raw, status = self._get("%s/repos/%s/commits/%s" % (GITHUB_API, slug, person.commit_sample), api=True)
        url = ""
        if raw:
            try:
                info = json.loads(raw.decode("utf-8"))
                av = (info.get("author") or {}).get("avatar_url") or ""
                if av:
                    url = av + ("&" if "?" in av else "?") + "s=%d" % (self.size * 2)
            except ValueError:
                pass
            with self.lock:
                self.lookup[key] = url
        elif status == 404:                       # commit unknown to GitHub: remember
            with self.lock:
                self.lookup[key] = ""
        return url or None

    def _local(self, person):
        d = self.cfg.get("local_avatar_dir") or ""
        cands = [person.display] + list(person.names) + list(person.logins) + list(person.emails)
        for c in cands:
            for ext in (".png", ".jpg", ".jpeg", ".gif"):
                pth = os.path.join(d, c + ext)
                if c and os.path.isfile(pth):
                    with open(pth, "rb") as fh:
                        return fh.read()
        dflt = os.path.join(d, self.cfg.get("local_avatar_default") or "default.png")
        if os.path.isfile(dflt):
            with open(dflt, "rb") as fh:
                return fh.read()
        return None

    def _bytes_for(self, person):
        if self.mode == "none":
            return None
        if self.mode == "local":
            data = self._local(person)
            if data:
                with self.lock:
                    self.stats["local"] += 1
            return data
        email = person.best_email()
        if self.mode == "github":
            url = self._github_url(person)
            if url:
                data = self._cached_download(url)
                if data:
                    return data
        if self.fallback == "none" and self.mode == "github":
            return None
        if not email and self.fallback == "none":
            return None
        return self._cached_download(self._gravatar_url(email, self.fallback if self.fallback != "none" else "404"))

    # ------------------------------------------------------------ processing
    @staticmethod
    def _to_rgba_surface(surf, size):
        """Any pygame surface (paletted GIF, RGB JPEG, RGBA PNG) -> 32-bit RGBA, size x size."""
        import pygame
        full = pygame.Surface(surf.get_size(), pygame.SRCALPHA, 32)
        full.blit(surf, (0, 0))
        return pygame.transform.smoothscale(full, (size, size))

    def _mask_alpha(self):
        if self._mask is None:
            import pygame
            m = self._to_rgba_surface(pygame.image.load(os.path.join(ASSETS, "mask.png")), self.size)
            px = np.frombuffer(pygame.image.tobytes(m, "RGBA"), np.uint8).reshape(self.size, self.size, 4)
            self._mask = px[..., 2].astype(np.float32) / 255.0     # blue channel, like PImage.mask
        return self._mask

    def decode(self, data):
        """Image bytes -> (size, size, 4) uint8 RGBA, circular if configured."""
        import pygame
        try:
            surf = self._to_rgba_surface(pygame.image.load(io.BytesIO(data)), self.size)
        except Exception:
            return None
        px = np.frombuffer(pygame.image.tobytes(surf, "RGBA"), np.uint8).reshape(self.size, self.size, 4).copy()
        if self.circular:
            px[..., 3] = (px[..., 3].astype(np.float32) * self._mask_alpha()).round().astype(np.uint8)
        return px

    # ------------------------------------------------------------------ main
    def prefetch(self, people, workers=8, progress=True):
        """display -> RGBA array (or missing). Blocks until done."""
        if self.mode == "none" or not people:
            return {}
        # most active people first: they get the limited API lookups, so the
        # faces you see most are real pictures; each later run with a fresh
        # budget upgrades the next people (lookups are cached)
        items = sorted(people.values(), key=lambda p: (-p.events, p.display))
        limit = int(self.cfg.get("avatar_limit", 1000) or 0)
        if limit and len(items) > limit:
            # the rest appear briefly: names only (a big history has tens of thousands)
            items = items[:limit]
        self.api_allowed = set()
        if self.mode == "github" and self.slug:
            left = self.budget
            for p in items:
                if left <= 0:
                    break
                if any(github_login(e)[0] for e in p.emails) or not p.commit_sample:
                    continue
                if not self.slug_for(p) or "%s@%s" % (self.slug_for(p), p.commit_sample) in self.lookup:
                    continue
                self.api_allowed.add(p.display)
                left -= 1
        out = {}
        t0 = time.time()
        done = [0]

        def work(p):
            data = self._bytes_for(p)
            with self.lock:
                done[0] += 1
            return p.display, data

        last = 0.0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(work, p) for p in items]
            for f in futs:
                disp, data = f.result()
                if data:
                    img = self.decode(data)
                    if img is not None:
                        out[disp] = img
                if progress and time.time() - last > 1.0:
                    last = time.time()
                    import sys
                    sys.stdout.write("\r  avatars %d/%d   " % (done[0], len(items)))
                    sys.stdout.flush()
        try:
            tmp = self.lookup_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.lookup, fh)
            os.replace(tmp, self.lookup_file)
        except OSError:
            pass
        self.stats["missing"] = len(items) - len(out)
        if progress:
            import sys
            sys.stdout.write("\r")
            s = self.stats
            say("Avatars  : %d of %d people (%s; %d from cache, %d downloaded, %d API calls%s) in %.1f s"
                % (len(out), len(items), self.mode, s["cached"], s["downloaded"], s["api_calls"],
                   ", GitHub rate limit hit - set GITHUB_TOKEN" if s["rate_limited"] else "",
                   time.time() - t0))
            if s.get("gave_up"):
                warn("avatar servers unreachable - continuing without new pictures (cached ones are used)")
            elif s["errors"] and not out:
                warn("avatar downloads failed (%d errors) - offline or blocked?" % s["errors"])
        return out
