"""What kind of file is this?  Path -> group name, for colours and the legend.

Order matters: the first matching group wins.  Path-based groups come first
(AI agent files, CI, tests, dependency manifests ...), then file names, then
extensions (one group per language).  Everything is matched on the lower-case
path with forward slashes.

Granularity:
  fine    every group below (default)
  coarse  merged into a few families: Code, Tests, Docs, AI agents, Config & build,
          Assets, Data, Other
Users can add their own groups (checked first) with a TOML file, see
load_custom_groups().
"""

import fnmatch
import os
import re

# ---------------------------------------------------------------- path groups
# Each group: names (exact basenames), globs (basename patterns), dirs (a path
# component sequence that must appear), path_globs (whole path patterns).
PATH_GROUPS = [
    ("AI agents", {
        "names": ["agents.md", "agent.md", "claude.md", "claude.local.md", "gemini.md", "copilot-instructions.md",
                  ".cursorrules", ".windsurfrules", ".clinerules", ".roorules", ".aider.conf.yml", ".aiderignore",
                  ".aider.model.settings.yml", "llms.txt", "llms-full.txt", ".mcp.json", "mcp.json",
                  ".cursorignore", ".codeiumignore", "conventions.md"],
        "globs": ["*.mdc", "*.prompt.md", "*.chatmode.md", "*.instructions.md", "*.agent.md"],
        "dirs": [".claude", ".cursor", ".github/prompts", ".github/instructions", ".github/chatmodes",
                 ".continue", ".windsurf", ".codex", ".gemini", ".roo", ".kiro", ".amazonq", ".junie",
                 ".clinerules", ".aider", ".agents", ".agent"],
    }),
    ("CI", {
        "names": [".gitlab-ci.yml", ".travis.yml", "jenkinsfile", "azure-pipelines.yml", "appveyor.yml",
                  ".appveyor.yml", ".drone.yml", "bitbucket-pipelines.yml", "cloudbuild.yaml", "codecov.yml",
                  ".codecov.yml", "tox.ini", "noxfile.py", ".cirrus.yml", "buildkite.yml", ".woodpecker.yml"],
        "dirs": [".github/workflows", ".github/actions", ".circleci", ".buildkite", ".gitlab", ".woodpecker",
                 ".azure-pipelines", "ci"],
    }),
    ("Repo tooling", {
        "names": [".gitignore", ".gitattributes", ".gitmodules", ".mailmap", ".editorconfig", ".pre-commit-config.yaml",
                  ".pre-commit-hooks.yaml", "codeowners", ".git-blame-ignore-revs", ".gitkeep", "renovate.json",
                  ".renovaterc", "dependabot.yml", ".flake8", ".pylintrc", "pylintrc", "ruff.toml", ".ruff.toml",
                  "mypy.ini", ".mypy.ini", ".clang-format", ".clang-tidy", "rustfmt.toml", ".rustfmt.toml",
                  "clippy.toml", ".rubocop.yml", ".isort.cfg", ".coveragerc", ".prettierignore", ".eslintignore",
                  ".npmignore", ".dockerignore", ".nvmrc", ".python-version", ".tool-versions", ".envrc",
                  "pull_request_template.md", "issue_template.md", "funding.yml", ".ds_store", "thumbs.db",
                  "desktop.ini", ".markdownlint.json", ".yamllint", ".shellcheckrc",
                  "biome.json", ".swiftlint.yml", ".golangci.yml", ".golangci.yaml", "deny.toml"],
        "globs": [".prettierrc*", ".eslintrc*", ".stylelintrc*", "eslint.config.*", "prettier.config.*",
                  ".babelrc*", ".browserslistrc"],
        "dirs": [".github/issue_template", ".vscode", ".idea", ".devcontainer", ".husky"],
    }),
    ("Dependencies", {
        "names": ["package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml",
                  "pnpm-workspace.yaml", "bun.lockb", "bun.lock", "deno.lock", "cargo.toml", "cargo.lock",
                  "constraints.txt", "poetry.lock", "pipfile", "pipfile.lock", "uv.lock", "pdm.lock", "go.mod",
                  "go.sum", "go.work", "gemfile", "gemfile.lock", "composer.json", "composer.lock",
                  "pubspec.yaml", "pubspec.lock", "mix.exs", "mix.lock", "packages.config", "vcpkg.json",
                  "conanfile.txt", "conanfile.py", "environment.yml", "environment.yaml", "flake.lock",
                  "package.swift", "package.resolved", "podfile", "podfile.lock", "cartfile", "rebar.config",
                  "stack.yaml", "cabal.project", "directory.packages.props", "paket.dependencies", "gradle.lockfile",
                  "renv.lock", "description"],
        "globs": ["requirements*.txt", "requirements*.in", "*.gemspec", "*.cabal"],
    }),
    ("Build", {
        "names": ["makefile", "gnumakefile", "cmakelists.txt", "cmakepresets.json", "meson.build", "meson_options.txt",
                  "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "gradlew",
                  "gradlew.bat", "pom.xml", "build.xml", "build.sbt", "configure.ac", "configure.in", "configure",
                  "makefile.am", "makefile.in", "sconstruct", "sconscript", "wscript", "build.zig", "build.zig.zon",
                  "build", "build.bazel", "workspace", "workspace.bazel", "module.bazel", ".bazelrc", "justfile",
                  "taskfile.yml", "rakefile", "setup.py", "setup.cfg", "pyproject.toml", "manifest.in",
                  "build.rs", "jakefile", "gulpfile.js", "gruntfile.js", "webpack.config.js", "vite.config.ts",
                  "vite.config.js", "rollup.config.js", "tsconfig.json", "babel.config.js", "nx.json", "turbo.json",
                  "lerna.json", "makefile.win", "premake5.lua", "xmake.lua", "build.ninja", "cargo-make.toml"],
        "globs": ["*.mk", "*.cmake", "*.bzl", "*.mak", "*.vcxproj", "*.vcxproj.filters", "*.sln", "*.csproj",
                  "*.fsproj", "*.vbproj", "*.xcodeproj", "*.pbxproj", "*.ninja", "tsconfig.*.json", "*.props",
                  "*.targets", "*.spec", "*.wxs", "*.wxi", "*.nsi", "*.iss"],
    }),
    ("Infra", {
        "names": ["dockerfile", "containerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml",
                  "compose.yaml", "vagrantfile", "procfile", "fly.toml", "netlify.toml", "vercel.json",
                  "render.yaml", "app.yaml", "app.json", "skaffold.yaml", "tiltfile", "chart.yaml", "values.yaml",
                  "kustomization.yaml", "serverless.yml", "terraform.lock.hcl", ".terraform.lock.hcl", "flake.nix",
                  "shell.nix", "default.nix", "wrangler.toml"],
        "globs": ["dockerfile.*", "*.dockerfile", "docker-compose.*.yml", "docker-compose.*.yaml", "*.tf",
                  "*.tfvars", "*.hcl", "*.nix", "*.service", "*.timer", "*.socket"],
        "dirs": ["k8s", "kubernetes", "helm", "ansible", "terraform", "deploy", "infra", "infrastructure",
                 ".docker", "docker"],
        "dirs_code": False,
    }),
    ("Tests", {
        "names": ["conftest.py", "pytest.ini", "jest.config.js", "jest.config.ts", "karma.conf.js",
                  "vitest.config.ts", "vitest.config.js", "phpunit.xml", "phpunit.xml.dist", ".rspec",
                  "playwright.config.ts", "cypress.config.ts", "cypress.json", ".mocharc.yml", ".mocharc.json"],
        "globs": ["test_*", "*_test.*", "*_tests.*", "*.test.*", "*.spec.js", "*.spec.ts", "*.spec.jsx",
                  "*.spec.tsx", "*.spec.mjs", "*_spec.rb", "*.bats", "*.feature"],
        "dirs": ["test", "tests", "__tests__", "testing", "e2e", "testdata", "test_data", "spec", "specs",
                 "unittests", "unit_tests", "integration_tests", "benches", "benchmarks", "cypress", "playwright"],
    }),
    ("Database", {
        "names": ["schema.prisma", "alembic.ini", "knexfile.js", "ormconfig.json"],
        "globs": ["*.sql", "*.prisma", "*.psql", "*.pgsql", "*.ddl", "*.dml"],
        "dirs": ["migrations", "migration", "alembic", "db/migrate", "flyway", "liquibase"],
    }),
    ("Schemas/API", {
        "globs": ["*.proto", "*.graphql", "*.gql", "*.thrift", "*.avsc", "*.avdl", "openapi*.yaml", "openapi*.yml",
                  "openapi*.json", "swagger*.yaml", "swagger*.yml", "swagger*.json", "*.raml", "*.wsdl", "*.capnp",
                  "*.fbs", "*.smithy", "*.jsonschema", "*.schema.json", "asyncapi*.yaml", "*.xsd", "*.dtd",
                  "*.rnc", "*.rng", "*.wit", "*.idl"],
    }),
    ("Docs", {
        "names": ["readme", "changelog", "changes", "history", "news", "contributing", "authors", "contributors",
                  "license", "licence", "copying", "notice", "code_of_conduct", "security", "support", "governance",
                  "maintainers", "todo", "credits", "thanks", "hacking", "install", "roadmap", "releasing",
                  "citation.cff", "codemeta.json", "unlicense", "patents"],
        "stem_names": True,      # readme.md, license.txt ... (any extension)
        "globs": ["*.md", "*.markdown", "*.rst", "*.txt", "*.adoc", "*.asciidoc", "*.tex", "*.rdoc", "*.org",
                  "*.textile", "*.pod", "*.wiki", "*.mdx", "*.texi", "*.bib", "*.man", "*.[1-9]", "*.sty", "*.cls",
                  "*.bst"],
    }),
    ("Notebooks", {"globs": ["*.ipynb", "*.rmd", "*.qmd"]}),
    ("Localization", {
        "globs": ["*.po", "*.pot", "*.mo", "*.xliff", "*.xlf", "*.resx", "*.strings", "*.stringsdict", "*.arb",
                  "*.ftl", "*.ts.xml"],
        "dirs": ["locale", "locales", "i18n", "l10n", "translations"],
        "dirs_code": False,      # src/i18n/loader.rs is code, not a translation
    }),
]

# ---------------------------------------------------------------- extensions
EXT_GROUPS = {
    # languages
    "Python": "py pyx pyi pxd pxi pyw",
    "JavaScript": "js mjs cjs jsx",
    "TypeScript": "ts tsx mts cts",
    "C": "c h",
    "C++": "cpp cc cxx c++ hpp hh hxx h++ ipp inl tpp ixx cppm",
    "C#": "cs csx razor cshtml",
    "F#": "fs fsi fsx",
    "Visual Basic": "vb vbs bas",
    "Java": "java pde",
    "Kotlin": "kt kts",
    "Scala": "scala sc",
    "Groovy": "groovy gvy",
    "Clojure": "clj cljs cljc edn",
    "Go": "go",
    "Rust": "rs",
    "Zig": "zig",
    "Nim": "nim nims",
    "D": "d di",
    "Odin": "odin",
    "V": "v",
    "Ruby": "rb erb rake ru",
    "Crystal": "cr",
    "PHP": "php phtml blade",
    "Perl": "pl pm t psgi",
    "Raku": "raku rakumod p6",
    "Lua": "lua",
    "Swift": "swift",
    "Objective-C": "m mm",
    "Dart": "dart",
    "Elixir": "ex exs heex eex",
    "Erlang": "erl hrl",
    "Gleam": "gleam",
    "Haskell": "hs lhs",
    "Elm": "elm",
    "OCaml": "ml mli",
    "Lisp/Scheme": "lisp lsp cl el scm ss rkt",
    "R": "r",
    "Julia": "jl",
    "MATLAB/Octave": "mat",
    "Fortran": "f f90 f95 f03 f08 for",
    "COBOL": "cob cbl",
    "Pascal/Delphi": "pas dpr pp lpr",
    "Ada": "ada adb ads",
    "Assembly": "asm s nasm",
    "Solidity": "sol",
    "Verilog/VHDL": "v sv svh vhd vhdl",
    "Mojo": "mojo",
    "Shell": "sh bash zsh fish ksh csh",
    "PowerShell": "ps1 psm1 psd1",
    "Batch": "bat cmd",
    "AutoHotkey": "ahk",
    "Web": "html htm xhtml css css_t scss sass less styl vue svelte astro hbs handlebars mustache ejs pug jinja jinja2 j2 twig liquid njk",
    "Shaders": "glsl hlsl wgsl frag vert comp geom tesc tese metal shader fx cg",
    # non-code
    "Config": "json json5 jsonc yml yaml toml ini cfg conf config xml plist properties env reg desktop rels manifest",
    "Data": "csv tsv parquet arrow feather avro orc sqlite sqlite3 db h5 hdf5 npy npz pkl pickle jsonl ndjson geojson dic aff",
    "Office/PDF": "docx doc dotx xlsx xls xlsm pptx ppt odt ods odp pdf rtf epub",
    "Images": "png jpg jpeg gif svg ico icns bmp webp tif tiff psd ai eps xcf sketch fig avif heic",
    "Fonts": "ttf otf woff woff2 eot pfb",
    "Audio/Video": "mp3 wav ogg flac aac m4a mid midi mp4 webm mov avi mkv",
    "3D": "obj fbx gltf glb blend stl dae 3ds usd usdz ply",
    "Binaries": "egg jar war so dll exe dylib jnilib a o lib class pyc pyd whl zip gz tgz tar bz2 xz 7z rar bin wasm apk dmg iso deb rpm msi",
}
_EXT_TO_GROUP = {}
for _g, _exts in EXT_GROUPS.items():
    for _e in _exts.split():
        _EXT_TO_GROUP.setdefault(_e, _g)   # first wins (e.g. "v" -> V language)

_NON_CODE_EXT_GROUPS = {"Config", "Data", "Office/PDF", "Images", "Fonts", "Audio/Video", "3D", "Binaries"}

COARSE = {
    "AI agents": "AI agents", "Tests": "Tests", "Docs": "Docs", "Notebooks": "Docs",
    "CI": "Config & build", "Repo tooling": "Config & build", "Dependencies": "Config & build",
    "Build": "Config & build", "Infra": "Config & build", "Config": "Config & build",
    "Images": "Assets", "Fonts": "Assets", "Audio/Video": "Assets", "3D": "Assets",
    "Data": "Data", "Database": "Data", "Office/PDF": "Docs", "Localization": "Docs",
    "Binaries": "Other", "Schemas/API": "Code", "Web": "Code", "Shaders": "Code",
}
NON_CODE = set(COARSE) | {"(no extension)"}


def _norm(path):
    return path.replace("\\", "/").lower().lstrip("./") if path.startswith("./") else path.replace("\\", "/").lower()


def _has_dir(parts, seq):
    """True if the directory part sequence `seq` (e.g. ['.github','workflows']) appears in parts."""
    n = len(seq)
    for i in range(len(parts) - n + 1):
        if parts[i:i + n] == seq:
            return True
    return False


_DOC_EXTS = {"", "md", "markdown", "txt", "rst", "adoc", "asciidoc", "org", "textile", "rdoc", "html", "pdf", "mdx"}
# FooTest.java, FooTests.cs, FooSpec.scala, FooIT.java (case-sensitive, so "Latest.java" is not a test)
_CAMEL_TEST = re.compile(r"[a-z0-9_](Test|Tests|Spec|IT)\.(java|kt|kts|cs|fs|vb|swift|php|scala|groovy|m|mm)$")
_REQ_DIR = re.compile(r"(^|/)requirements[^/]*/[^/]+\.(in|txt)$")   # requirements/dev.in
_COMPILED = []
for _name, _spec in PATH_GROUPS:
    _COMPILED.append((_name, set(_spec.get("names", [])), _spec.get("globs", []),
                      [d.split("/") for d in _spec.get("dirs", [])], bool(_spec.get("stem_names")),
                      _spec.get("dirs_code", True)))


class Classifier:
    def __init__(self, custom=None, granularity="fine"):
        self.custom = custom or []           # [(name, [globs])]
        self.granularity = granularity
        self.cache = {}

    def group(self, path):
        g = self.cache.get(path)
        if g is None:
            g = self._group(path)
            if self.granularity == "coarse":
                g = COARSE.get(g, "Other" if g.startswith(".") or g == "(no extension)" else "Code")
            self.cache[path] = g
        return g

    def _group(self, path):
        p = _norm(path)
        # template / backup suffixes: classify by the inner name
        # (app.conf.orig, .env.example, foo.rst~, theme.xml.in, contents.rst.inc)
        while True:
            q = re.sub(r"(~|\.(in|tmpl|template|example|sample|dist|orig|bak|old|inc|j2|jinja))$", "", p)
            qb = q.rsplit("/", 1)[-1]
            if q == p or not ("." in qb.lstrip(".") or (qb.startswith(".") and len(qb) > 1)):
                break
            p = q
        if p.endswith("/py.typed") or p == "py.typed":
            return "Python"
        for name, globs in self.custom:
            for pat in globs:
                if fnmatch.fnmatch(p, pat.lower()) or fnmatch.fnmatch(p.rsplit("/", 1)[-1], pat.lower()):
                    return name
        parts = p.split("/")
        base = parts[-1]
        dirs = parts[:-1]
        stem = base.split(".", 1)[0]
        ext = os.path.splitext(base)[1][1:]
        if not ext and base.startswith(".") and base.count(".") == 1:
            ext = base[1:]                        # .env -> env
        if _REQ_DIR.search(p):
            return "Dependencies"
        orig_base = path.replace("\\", "/").rsplit("/", 1)[-1]
        is_code = _EXT_TO_GROUP.get(ext, "") not in _NON_CODE_EXT_GROUPS and ext in _EXT_TO_GROUP
        for name, names, globs, dir_seqs, stem_names, dirs_code in _COMPILED:
            if base in names or (stem_names and stem in names and ext in _DOC_EXTS):
                return name
            if name == "Tests" and _CAMEL_TEST.search(orig_base):
                return name
            if any(fnmatch.fnmatch(base, g) for g in globs):
                return name
            if (dirs_code or not is_code) and any(_has_dir(dirs, seq) for seq in dir_seqs):
                return name
        if not ext:
            return "(no extension)"
        return _EXT_TO_GROUP.get(ext, "." + ext)


_ACTIVE = [Classifier()]


def set_active(classifier):
    """Classifier used by group_of() (custom groups / granularity from the CLI)."""
    _ACTIVE[0] = classifier


def group_of(path):
    return _ACTIVE[0].group(path)


def load_custom_groups(path):
    """TOML:
        [[group]]
        name  = "Specs"
        match = ["specs/*", "*.spec.md"]       # fnmatch on the path or the file name
        color = [255, 120, 0]                  # optional
    Returns (custom list for Classifier, {name: color})."""
    import tomllib
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    custom, colors = [], {}
    for g in data.get("group", []):
        custom.append((g["name"], list(g["match"])))
        if "color" in g:
            colors[g["name"]] = list(g["color"])
    return custom, colors
