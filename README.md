# codeswarm

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/44348bd8-2c15-432a-a6f2-6b8566b09973" />

Animated history of a git repository: people and the files they change swirl around each other as the project unfolds. A Python rewrite of Michael Ogawa's [code_swarm](http://vis.cs.ucdavis.edu/~ogawa/codeswarm/) (2008) that runs straight from a repository: no log export, no XML, no Java, with a few bells & whistles I added (with the help of Claude Opus 5.5).

```sh
codeswarm owner/repo                            # watch it in a window
codeswarm owner/repo --duration 120 -o out.mp4  # or make a two-minute video
codeswarm owner/repo --preset original          # like in the original software
codeswarm owner/repo --preset classic           # like rictic's fork, with the SE config (basically the starting point for this port)
```

I want to thank the original authors for sharing this. These are the repositories and configurations I used:
```
https://github.com/itkang/codeswarm [YKK/itkang]
https://github.com/rictic/code_swarm [Peter Burns/rictic]
https://unix.stackexchange.com/q/108158 [StackExchange U&L, user44370 for the config]
```

## Install

Needs Python 3.11+, Git, and a graphics driver with OpenGL 3.3. Video export also needs ffmpeg (`sudo pacman -S ffmpeg` or `sudo apt install ffmpeg`).

Recommended, with [pipx](https://pipx.pypa.io), which gives codeswarm its own isolated environment and puts `codeswarm` on your PATH:

```sh
sudo pacman -S python-pipx                     # or: sudo apt install pipx
pipx install git+https://github.com/knuckle-Joe/codeswarm
```

Or from a downloaded copy, in a virtual environment inside the project folder:

```sh
cd codeswarm
python -m venv .venv
.venv/bin/pip install -e .
```

## Uninstall

```sh
codeswarm --clear-cache        # cached clones, histories and avatars (see --cache-info)
pipx uninstall codeswarm       # or delete the .venv folder
```

Nothing else is written outside the cache folder and the outputs you ask for. Cache folder: `~/.cache/codeswarm` on Linux, `%LOCALAPPDATA%\codeswarm` on Windows, or `--cache-dir`.

## Run Codeswarm

```sh
codeswarm owner/repo                            # a GitHub repository
codeswarm https://gitlab.com/group/project.git  # any git URL
codeswarm ~/code/myproject                      # a local repository
codeswarm owner/repo --since 2020-01-01 --until 2021-12-31
.venv/bin/codeswarm owner/repo                  # installed in a virtual environment, not activated
```

A URL is cloned once with its history and file names only (no file contents), so even big projects load in seconds; later runs fetch only the new commits. `--offline` uses the cached copy as it is.

### Keys

Every key press is also echoed in the terminal.

| key | toggles | key | toggles |
|---|---|---|---|
| space | pause / resume | q, Esc | quit |
| a | name halos (glow) | s | names |
| f | fuzzy files (glow) | j | jelly files (rings) |
| S | sharp files (dots) | e | edges (person-file lines) |
| l | legend | p | most active files |
| h | histogram | d | date |
| b | debug numbers | E | physics engine name |
| r | commit ripples | i | repository panel |
| c | commit messages | t | release tags |
| n | spread overlapping names | ?, F1 | help panel (shows what is on and off) |

## What you see

- **People**: names with their avatar; people who have not committed lately fade.
- **Files**: glowing dots that gather around whoever changes them and fade when left alone. Colour = kind of file, see the legend (with each kind's share of all changes).
- **Lines** join people to the files of their latest commits; a **ripple** spreads from a person at each commit.
- **Most active files** (top left): the 20 files changed most in the last 30 days. The top 10 are numbered in the swarm too, with a thin gold ring that flashes on each change (green added, white changed, red deleted, blue moved) and one small tick per person who changed the file.
- **Repository panel** (top right): commits, people and files so far; for the last 30 days, the activity, the change mix, newcomers and the most active people.
- **Commit messages**: the subject line under the committer's name for a few seconds, and the latest ones in a ticker just above the date.
- **Releases**: the tag name top centre for a few seconds, and a gold mark over the histogram.
- **Histogram** (bottom left): changes per frame, by kind of file.
- **Caption** (top left): the repository name.

Every element has a key (above) and flags (see the reference at the end).

## Make a video

```sh
codeswarm owner/repo -o swarm.mp4                       # also .mkv .mov .webm
codeswarm owner/repo --size 1280x720 --fps 30 --linger 3 -o swarm.mp4
codeswarm owner/repo --frames shots --every 100         # PNG frames instead
```

Existing files are never overwritten (`swarm.mp4` becomes `swarm_1.mp4`). A progress line shows the speed and the time left; `--crf` (default 18) trades quality for size. One day of history lasts `--frames-per-day` frames.

## Telling the story

```sh
codeswarm owner/repo --max-gap 14 --duration 120 --title "My project" --credits 6 -o story.mp4
codeswarm org/backend org/frontend --colors repo --title "The platform" -o platform.mp4
```

- `--max-gap DAYS` shortens quiet periods to DAYS; the date shown stays real and "... 10 months later" appears at each jump.
- `--duration SECONDS` picks the speed so the whole video lasts that long.
- `--title`, `--subtitle`, `--intro SECONDS`: an intro card (date range, people, commits, files, legend). `--credits SECONDS`: a closing card with the most active people and their avatars.
- Several sources make one swarm; paths get the repository name as a prefix (`--no-prefix` to turn that off) and a person in both repositories is one person.

## People and avatars

Names and emails of one person are merged (shared email, same name ignoring case and accents, GitHub login from noreply emails), after `.mailmap`. Bots are hidden. `--people people.csv` shows who was merged, `--alias "old=New"` fixes a case by hand, `--exclude-author GLOB` hides people, and `--keep-bots` and `--no-merge-identities` give the original behaviour.

Avatars (`--avatars auto|github|gravatar|local|none`): GitHub pictures for GitHub repositories (most active people first; without a token GitHub allows 60 lookups an hour, set `GITHUB_TOKEN` to lift that), Gravatar or an identicon otherwise, and `--avatar-dir` for your own pictures. Only the 1,000 most active people get a picture (`--avatar-limit`, 0 for everyone): a very large history has tens of thousands of contributors, most of them on screen for a few seconds. Everything is cached, and `--offline` never touches the network.

## Kinds of files

About 60 groups, first match wins:

| group | examples |
|---|---|
| AI agents | AGENTS.md, CLAUDE.md, GEMINI.md, .cursorrules, .cursor/rules/\*.mdc, .github/copilot-instructions.md, \*.prompt.md, .claude/, .codex/, .gemini/, .windsurf/, llms.txt, .mcp.json |
| CI | .github/workflows/, .gitlab-ci.yml, Jenkinsfile, .circleci/, tox.ini, noxfile.py |
| Repo tooling | .gitignore, .pre-commit-config.yaml, CODEOWNERS, linter and formatter config, .vscode/, .devcontainer/ |
| Dependencies | package.json and locks, Cargo.toml/lock, requirements\*.txt, uv.lock, go.mod/sum, Gemfile, composer.json ... |
| Build | Makefile, CMakeLists.txt, pyproject.toml, setup.py, build.gradle, pom.xml, tsconfig.json, \*.csproj, \*.sln ... |
| Infra | Dockerfile, docker-compose.yml, \*.tf, \*.nix, k8s/, helm/, ansible/ (code in those folders stays code) |
| Tests | tests/, test_\*.py, \*\_test.go, \*.test.ts, \*.spec.js, FooTest.java, \*.feature, conftest.py |
| Database | migrations/, \*.sql, \*.prisma |
| Schemas/API | \*.proto, \*.graphql, OpenAPI/Swagger, \*.xsd, \*.rnc, \*.thrift |
| Docs | README, CHANGELOG, LICENSE ..., \*.md, \*.rst, \*.txt, \*.tex |
| Notebooks, Localization | \*.ipynb; \*.po, locale/, i18n/ (code in those folders stays code) |
| one per language | Python, Rust, TypeScript, Go, C, C++, Java, Kotlin, Swift, Zig, Elixir ... (45+) |
| Web, Shaders | html/css/scss/vue/svelte/templates; glsl/hlsl/wgsl |
| Config, Data | json/yaml/toml/xml/ini; csv/parquet/sqlite ... |
| Images, Fonts, Audio/Video, 3D, Office/PDF, Binaries | by extension |

Template and backup suffixes are looked through (`.env.example`, `app.conf.orig`, `x.xml.in`, `doc.rst~`). The busiest groups get the colours; **AI agents** is always listed when present and is always white.

```sh
codeswarm owner/repo --file-types          # how a repository is grouped, and what is left unclassified
```

Add or override groups with a TOML file (`--file-groups mygroups.toml`):

```toml
[[group]]
name  = "Specs"
match = ["specs/*", "*.spec.md"]     # path or file name patterns
color = [255, 120, 0]                # optional
```

`--granularity coarse` merges everything into 8 families (Code, Tests, Docs, AI agents, Config & build, Assets, Data, Other). `--colors repo` colours by repository instead; `--preset classic` uses fixed rules from a config file.

## Size

The default frame is 1920x1080. Everything in it (text, dots, rings, lines, avatars, the histogram) grows with the frame height (`--ui-scale auto`: 1.5x at 1080, 2x at 1440, 3x at 4K), while the layout of the swarm stays the same as at 720 lines. Use `--ui-scale 1.2` for smaller content and `--ui-scale 2` for bigger; `--font-size` sets the text size before scaling (default 11).

## Presets

- no preset: the classic look with automatic colours and everything described above
- `--preset classic`: the look of the well-known Stack Exchange code_swarm setup, with its fixed colour rules and the original popular-node counts, motion and sizes
- `--preset original`: code_swarm's own defaults
- `--config file.toml` (write one with `--print-config`), or an old code_swarm `.config` file

## What changed from the source material

The simulation was checked frame by frame against the original Java program, compiled from source: same dates, events, living files, people and edges on every frame. Everything below is a deliberate change, and each one can be turned off.

**Reading the history**

- No log export or XML: the history is read straight from git, from a clone with history only (no file contents), with exact renames, the author date (not the date a commit was applied), `.mailmap`, merged identities and hidden bots.
- Dates given to `--since` and `--until` filter on the author date.
- Impossible author dates are corrected: a few patches in large histories come from a machine with a broken clock (1970, or decades in the future), which would stretch the animation over a century. When an author date is more than a day after the commit date, or more than ten years before it, the commit date is used instead, and the run says how many were corrected.
- Bots are recognised per identity, before people are merged, so a robot that sends mail from a real developer's address hides only the robot.

**Motion**

- *Tracked files land and stick* (`--hubs`, `--hubs 0` for the original): the original moves a file to the ring of the person who changed it last like a spring (1% of the way each frame, keeping 90% of its speed), so it overshoots, swings back and circles its place; on a busy history the most changed files spend most of their time away from it. The 10 busiest files changed by at least 2 people lately (`--hub-min-people`) now move with no momentum: each frame they cover 30% of the distance left (`--hub-rate`), at most 20 px (`--hub-speed`), then lock onto their place and ride along with the person. They arrive sooner and stay put; people move exactly as before. `--hub-follow` below 1 aims between the last editor and everyone who changed the file lately; `--hub-gather` also pulls people toward those files.
- *The swarm keeps out of the panels* (`--no-keep-clear` for the original): people, and the files around them, are nudged out of the rectangles the caption and legend, the file list, the repository panel and the ticker actually take, so the open space between and below them is still used. The video, the PNG frames and the live window show the same swarm.
- *Rings stay on screen* (`--bounds legacy` for the original): people are kept far enough from the edge for their whole ring of files to be visible.

**Look**

- *Busy files stay modest* (`--file-size original` for the original): the original grows a file's glow with the square root of all its changes, so on a long history the busiest files become many times larger than everything else. A file now grows as before for its first few changes, then only slowly (the busiest is about 2.5x a new one).
- *Names do not pile up* (`--name-layout off` for the original): when two names (or a name and an avatar or a panel) would overlap, the less active one moves a little down or a short step aside, so it always stays with its avatar; a name with no free place nearby is drawn fainter. A commit subject hangs under its name and never moves it; where it would cover another name it is drawn faint.
- *Readable text*: names and numbers have a dark rim (`--no-text-shadow`), idle names and avatars fade (`--no-dim-idle-names`, `--no-dim-idle-avatars`). DejaVu Sans (the font Java used on Linux) is bundled, so accented names always have their letters; characters it lacks (Chinese, Japanese, Korean, Indic ...) come from an installed font that has them, and characters no font has (often emoji) are left out instead of showing as boxes.
- *Larger frame and content*: 1920x1080 by default, with everything scaled to the frame (see Size).
- *Histogram*: twice the original width and height (`--histogram-scale`), capped at 22% of the height so it never covers the panels (`--histogram-max`); the last colour run of each bar is drawn (the original skipped it).
- *No flashing*: alpha is clamped; the original wrapped it around at 256, which made fresh files flash (`--legacy-alpha-wrap` brings it back).
- Colour rules from old config files are read as written (`--java-escapes` for Java's escaping).

**Added**

- Ranked files with rings, status flashes and author ticks (`--popular-count`, `--popular-marks`, `--no-status-flash`, `--no-author-ticks`), commit ripples (`--no-ripples`), the repository panel (`--no-stats-panel`, `--stats-window`, `--people-count`), commit messages (`--commit-text`, `--ticker-lines`), releases (`--release-tags`, `--release-gap`), the caption (`--caption`, `--caption-font`, `--caption-style`), intro and closing cards, quiet-period compression, several repositories in one swarm, avatars from GitHub and Gravatar, and video export.

## For developers

`tools/` holds the scripts used to verify each part; they run on your machine against any repository:

```sh
python tools/p0_check.py ~/code/repo owner/repo      # history extraction vs git
python tools/p2_check.py owner/repo                  # video export
python tools/p3_check.py owner/repo --real           # people, colours, avatars
python tools/p4_check.py owner/repoA owner/repoB     # gaps, duration, cards, several repositories
python tools/p5_check.py owner/repo                  # file groups, accents, caption, packaging
python tools/p6_check.py owner/repo                  # 1920x1080 default and ui scale
python tools/p7_check.py owner/repo                  # histogram, panel numbers, caption, flag table
python tools/p8_check.py owner/repo                  # messages, rings, releases, name overlap, fonts
python tools/p9_check.py owner/repo                  # tracked files land and stick, ticker
python tools/p10_check.py owner/repo                 # swarm out of the panels, names stay put
python tools/p11_check.py                            # broken-clock dates, robots, avatar limit (builds its own test repository)
python tools/edge_check.py owner/repo                # share of files off screen
```

Reports are ASCII and never overwrite earlier ones. The flag reference below is generated from the program: `python tools/flags_table.py --update-readme` rewrites it, and `--check` tells whether it is out of date.

## Credits

code_swarm by Michael Ogawa; the rictic/code_swarm fork by Peter Burns and contributors. Orbitron font by Matt McInerney (SIL OFL); DejaVu Sans (Bitstream Vera licence). Licence: GPL-3.0 or later, see LICENSE and NOTICE.md.

## Reference: all flags

Defaults are those of the default look (no `--preset`) at 1920x1080; sizes are before the ui scale.

<!-- FLAGS:BEGIN -->
### Sources

| flag | value | default | what it does |
|---|---|---|---|
| `SOURCE` | SOURCE |  | repository URL, owner/repo, local path or .xml; several = one combined swarm |

### General

| flag | value | default | what it does |
|---|---|---|---|
| `-h` `--help` |  |  | show this help message and exit |
| `--version` |  |  | show program's version number and exit |

### Configuration

| flag | value | default | what it does |
|---|---|---|---|
| `--preset` | classic \| default \| original | default | named look: default (classic look, automatic colours, panels), classic (the code_swarm Stack Exchange setup), original (code_swarm's own defaults) |
| `--config` | CONFIG |  | TOML file, or a legacy code_swarm .config file |
| `--java-escapes` |  | off | read legacy .config backslashes exactly like Java did |
| `--print-config` |  | off | print the final config as TOML and exit |

### History selection

| flag | value | default | what it does |
|---|---|---|---|
| `--since` | SINCE |  | only commits after this date (git syntax, e.g. 2020-01-01) |
| `--until` | UNTIL |  | only commits before this date |
| `--branch` | BRANCH |  | branch, tag or commit to read (default HEAD) |
| `--include` | GLOB |  | keep only matching paths (repeatable) |
| `--exclude` | GLOB |  | drop matching paths (repeatable) |
| `--author-key` | name \| email | name | identify people by name or email |
| `--renames` | new \| both \| legacy | new | rename handling: new path only, both paths, or none (add+delete) |
| `--no-prefix` |  | off | with several repositories: do not prefix paths with the repository name |
| `--max-gap` | DAYS |  | shorten quiet periods longer than DAYS to DAYS (dates on screen stay real) |
| `--duration` | SECONDS |  | choose frames-per-day so the animation lasts about SECONDS |

### People

| flag | value | default | what it does |
|---|---|---|---|
| `--merge-identities` / `--no-merge-identities` |  | on | treat names/emails/GitHub logins of one person as one (default on) |
| `--keep-bots` |  | on | show dependabot, pre-commit-ci and other bots (hidden by default) |
| `--alias` | 'OLD=NEW' |  | show OLD as NEW (repeatable) |
| `--exclude-author` | GLOB |  | hide matching people (repeatable) |

### Look

| flag | value | default | what it does |
|---|---|---|---|
| `--file-groups` | FILE.toml |  | your own file groups, checked before the built-in ones (see README) |
| `--granularity` | fine \| coarse | fine | fine = ~60 groups (languages, tests, CI, AI agents...); coarse = 8 families |
| `--colors` | auto \| rules \| repo | auto | auto = by language/kind; rules = ColorAssign rules; repo = one colour per repository |
| `--avatar-size` | PX | 40 | avatar size before ui scale |
| `--avatar-fallback` | identicon \| retro \| robohash \| monsterid \| wavatar \| mp \| none | identicon | picture for people without one (default identicon) |
| `--avatar-dir` | DIR |  | folder for --avatars local |
| `--github-token` | GITHUB_TOKEN |  | GitHub token for avatar lookups (or set GITHUB_TOKEN) |
| `--avatar-limit` | N | 1000 | pictures for the N most active people only, the others show their name (default 1000, 0 = everyone) |
| `--github-api-budget` | GITHUB_API_BUDGET | 50 | max GitHub API calls without a token (default 50) |
| `--size` | SIZE | 1920x1080 | frame size, e.g. 1280x720 |
| `--fps` | FPS | 24 | frames per second of the window / video |
| `--ui-scale` | X | auto | size of text, dots, avatars and lines: 'auto' (height/720) or a number |
| `--font-size` | FONT_SIZE | 11 | names and panels, before ui scale (default 11) |
| `--frames-per-day` | N | 25.0 | animation frames per day of history (speed); see also --duration |
| `--background` | R,G,B | 0,0,0 | background colour |
| `--font-color` | R,G,B | 245,245,245 | colour of names and panel text |
| `--avatars` | auto \| github \| gravatar \| local \| none | auto | where pictures come from (auto: GitHub for GitHub repos, else Gravatar) |
| `--seed` | SEED |  | random seed for reproducible renders |
| `--bounds` | auto \| legacy | auto | auto keeps whole file rings on screen; legacy = original edge clamp |
| `--show-legend` / `--no-show-legend` |  | on | colour legend (key l) |
| `--show-history` / `--no-show-history` |  | on | histogram, bottom left (key h) |
| `--show-date` / `--no-show-date` |  | on | date, bottom right (key d) |
| `--show-edges` / `--no-show-edges` |  | on | lines between people and files (key e) |
| `--show-popular` / `--no-show-popular` |  | on | ranked file list + markers (key p) |
| `--show-user-name` / `--no-show-user-name` |  | on | names of people |
| `--draw-names-sharp` / `--no-draw-names-sharp` |  | on | draw names (key s) |
| `--draw-names-halos` / `--no-draw-names-halos` |  | off | blurred glow behind names (key a) |
| `--draw-files-sharp` / `--no-draw-files-sharp` |  | off | files as dots (key S) |
| `--draw-files-fuzzy` / `--no-draw-files-fuzzy` |  | on | files as glowing sprites (key f) |
| `--draw-files-jelly` / `--no-draw-files-jelly` |  | on | files as rings (key j) |
| `--circular-avatars` / `--no-circular-avatars` |  | on | round avatars |
| `--legacy-alpha-wrap` / `--no-legacy-alpha-wrap` |  | off | reproduce the original's flashing (alpha = life mod 256) |
| `--ripples` / `--no-ripples` |  | on | expanding ring at each commit (key r) |
| `--text-shadow` / `--no-text-shadow` |  | on | dark rim around names and numbers |
| `--dim-idle-names` / `--no-dim-idle-names` |  | on | dim the names of people who have not committed lately |
| `--show-engine` / `--no-show-engine` |  | off | physics engine name, bottom right (key E) |
| `--keep-clear` / `--no-keep-clear` |  | on | people and their files stay out of the panels (legend, file list, repository panel, ticker) instead of passing under them |
| `--linger` | SECONDS |  | keep animating after the last event so things fade out (default 0) |
| `--utc-dates` |  | off | show the date overlay in UTC instead of local time |

### Titles

| flag | value | default | what it does |
|---|---|---|---|
| `--title` | TITLE |  | intro card title (default: repository name(s)) |
| `--subtitle` | SUBTITLE |  | intro card line under the title (repeatable) |
| `--intro` | SECONDS |  | show an intro card for SECONDS (default 3 when --title is given, else 0) |
| `--credits` | SECONDS |  | closing card with the most active people for SECONDS |
| `--credits-count` | CREDITS_COUNT | 24 | people on the closing card (default 24) |
| `--caption` | CAPTION |  | permanent title in the top-left corner (default: the repository name) |
| `--no-caption` |  | off | no caption |
| `--caption-font` | CAPTION_FONT | orbitron | 'orbitron' (bundled, default) or a .ttf/.otf path |
| `--caption-style` | outline \| solid \| plain | outline | caption letters: outline + glow, solid + glow, or plain |
| `--legend-font` | LEGEND_FONT | orbitron | font of the colour legend: sans (default), orbitron, or a .ttf path |
| `--caption-color` | R,G,B | 110,230,255 | caption colour |
| `--popular-style` | ranked \| classic | ranked | ranked = numbered list + matching markers in the swarm; classic = original counts |
| `--popular-window` | DAYS | 30 | rank files by changes in the last DAYS (0 = all time) |
| `--accent` | R,G,B | 255,196,64 | colour of rank numbers and markers |
| `--popular-count` | N | 20 | files in the ranked list (default 20) |
| `--popular-marks` | N | 10 | how many of the listed files are marked in the swarm (default 10, 0 = none) |
| `--stats-panel` / `--no-stats-panel` |  | on | repository panel at the top right (key i) |
| `--stats-window` | DAYS | 30 | window of the 'last N days' numbers when files are ranked all-time (default 30) |
| `--people-count` | N | 5 | most active people in the panel (default 5, 0 = none) |
| `--histogram-scale` | X | 2 | histogram bar width and height (default 2) |
| `--histogram-max` | FRACTION | 0.22 | cap the histogram at this share of the height (default 0.22, 0 = no cap) |

### Commit details

| flag | value | default | what it does |
|---|---|---|---|
| `--commit-text` | off \| names \| ticker \| both | both | commit subjects: under the committer's name, in a ticker bottom right, or both (key c) |
| `--commit-text-seconds` | SECONDS | 3.0 | how long a subject stays under a name (default 3) |
| `--commit-text-max` | N | 3 | subjects under names at the same time, newest first (default 3) |
| `--ticker-lines` | N | 8 | lines in the commit ticker, just above the date (default 8) |
| `--subject-length` | CHARS | 64 | cut longer subjects with '...' (default 64) |
| `--status-flash` / `--no-status-flash` |  | on | ranked-file rings flash on each change: green added, white changed, red deleted, blue moved |
| `--author-ticks` / `--no-author-ticks` |  | on | ticks around ranked-file rings, one per person who changed the file in the window |
| `--releases` / `--no-releases` |  | on | release tags: short banner and markers on the histogram (key t) |
| `--release-tags` | auto \| all \| none \| PATTERNS | auto | which tags are releases: auto (version-like, else build numbers), all, none, or shell patterns such as 'v*,release-*' |
| `--release-gap` | SECONDS | 4.0 | at most one release banner per this many seconds (default 4) |
| `--hubs` | N | 10 | the N busiest shared files go to each new editor quickly and stick to them, instead of the original springy flight that overshoots and orbits (default 10, 0 = original motion) |
| `--file-size` | gentle \| original | gentle | gentle = busy files only a little bigger (about 2.5x a new file at most); original = grows with the square root of all changes (20x and more on long histories) |
| `--hub-follow` | 0..1 | 1.0 | where a hub goes: 1 = the ring of the person who changed it last, as the original (default); lower = between that person and everyone who changed it lately |
| `--hub-rate` | 0..1 | 0.3 | share of the remaining distance a hub covers each frame: higher = arrives sooner (default 0.3; it never overshoots and locks on when it arrives) |
| `--hub-speed` | PX | 20.0 | top speed of a hub in px per frame before ui scale (default 20; original files peak around 35 and then bounce) |
| `--hub-gather` / `--no-hub-gather` |  | off | also pull people toward their hubs (the 0.10 look; people move more) |
| `--hub-min-people` | N | 2 | a hub was changed by at least N people in the window (default 2) |
| `--dim-idle-avatars` / `--no-dim-idle-avatars` |  | on | avatars of people not committing lately fade like their names |
| `--name-layout` | spread \| off | spread | spread = move overlapping names apart (default); off = original placement (key n) |

### Output

| flag | value | default | what it does |
|---|---|---|---|
| `--output` `-o` | FILE |  | render a video without a window: .mp4 (default codec H.264), .mkv, .mov, .webm |
| `--crf` | CRF | 18 | video quality, lower = better/bigger (default 18) |
| `--encoder-preset` | ENCODER_PRESET | medium | x264 speed/size trade-off: ultrafast ... medium ... veryslow |
| `--frames` | DIR |  | render without a window and save each frame as PNG in DIR |
| `--start-frame` | START_FRAME | 1 | first frame to save |
| `--every` | EVERY | 1 | save every Nth frame |
| `--max-frames` | MAX_FRAMES |  | stop after this frame number |

### Data / diagnostics

| flag | value | default | what it does |
|---|---|---|---|
| `--stats` |  | off | print history statistics and exit |
| `--dump-events` | FILE.csv |  | write the events to CSV and exit |
| `--file-types` |  | off | print how the files are grouped (share, files, example) and what is unclassified, then exit |
| `--people` | FILE.csv |  | write who is who after merging (names, emails, logins) to CSV and exit |
| `--export-xml` | FILE.xml |  | write a legacy code_swarm event XML (for the old Java tool) and exit |
| `--cache-dir` | DIR | ~/.cache/codeswarm | where clones, parsed histories and avatars are kept |
| `--cache-info` |  | off | show where the cache is and how big, then exit |
| `--clear-cache` | all \| repos \| events \| avatars |  | delete cached clones / parsed histories / avatars (default all), then exit |
| `--no-cache` |  | off | re-read history even if cached |
| `--offline` |  | off | do not fetch updates for a cached clone |
<!-- FLAGS:END -->
