# Native arm64 pdf2htmlEX — proposals

**Status**: Proposed, not chosen
**Date**: 2026-04-22

Two candidate paths for getting pdf2htmlEX to run natively on Apple
Silicon, bypassing Rosetta. Written up because (a) this is the single
biggest conversion-speed lever and (b) no off-the-shelf solution
exists, so we have to pick one and build it ourselves.

## Why we want this

Every cache-miss conversion today goes through `docker run
--platform linux/amd64 …` against an x86_64 pdf2htmlEX image
(`scripts/pdf2html-convert.sh:182`). On an Apple Silicon laptop that
means the entire pdf2htmlEX C++ pipeline runs under Rosetta 2.
Rosetta's overhead on compute-heavy C++ is roughly **2–2.5×** — it is
the dominant cost for any non-trivial document.

Measured from `~/.cache/pdf_viewer/log` (a spread of recent conversions):

| PDF | Pages (approx.) | Convert wall-time |
|---|---|---|
| arxiv 2604.19742 | 3 | 5 s |
| MOWI report | ~30 | 14 s |
| Hoffets årsrapport | ~80 | 36 s |
| Læring pensumbok | ~250 | 51 s |
| Datamaskiner pensumbok | ~400 | 101 s |
| KTN pensumbok | ~800 | 110 s |

For the textbooks the user reads most often, a Rosetta-free build
would realistically drop the 100 s conversion phase to ~40 s, and
free up lever #2 (parallel chunked conversion) to compound on top of
that. For small PDFs the win is proportionally bigger because Docker
+ Rosetta startup becomes a larger fraction of total wall-time.

This is the only lever in the perf analysis that multiplies by >2×
on its own.

## Where the cost lives

Docker Desktop on Apple Silicon runs containers inside an arm64
Linux VM. That VM is native to the host CPU; its costs (boot,
background RAM, ~1–2 s per `docker run`) are fixed regardless of
image architecture. What *varies* is what happens inside the VM:
our current `linux/amd64` image has every instruction translated
x86 → arm64 by Rosetta before executing. A `linux/arm64` image
skips that translation entirely — the binary runs on the VM's arm64
kernel directly. Option 1 targets only that inner translation
layer; the outer VM stays as-is.

## Why nothing off the shelf works

Surveyed 2026-04-22:

- **Homebrew tap `pdf2htmlEX/homebrew-brewTap`** — last commit
  December 2019. Open issue from 2023 reporting the cmake build is
  broken against modern toolchains. Effectively abandoned.
- **MacPorts `pdf2htmlex` port** — every arm64 build from macOS 11
  through 26 reports `failed install-port`. Nobody has successfully
  built this on darwin-arm64 in public.
- **Upstream `pdf2htmlEX/pdf2htmlEX`** — repo itself saw merges as
  recent as July 2025, so it is not dead, but the last release
  artifacts (`.deb`, `.AppImage`, Alpine tarball) were published
  August 2020 and are all `x86_64` only. No arm64 binaries anywhere.
- **Community "M1/M2/M3" Docker images** (`mirpo/pdf2htmlEX-docker`,
  `bwits/pdf2htmlex`, `sergiomtzlosa/pdf2htmlex`, official
  `pdf2htmlex/pdf2htmlex`) — all ship amd64 manifests and rely on
  Docker Desktop's Rosetta layer. Zero perf win over our current
  setup.

The only path to native arm64 is to build it. The question is just
how much of the stack we rebuild.

## Option 1 — linux/arm64 Docker image (recommended)

Fork the upstream Dockerfile, target `--platform linux/arm64`,
iterate on poppler/cairo/fontforge versions until the build passes on
arm64 Linux. Publish the resulting image to a personal Docker Hub
namespace (or just keep it local). Swap `$IMAGE` in
`scripts/pdf2html-convert.sh` and `scripts/extract-pdf-thumbs.sh` to
point at it.

**Win**: kills Rosetta, which is where the 2–2.5× lives.
**Cost retained**: Docker-container startup (~1–2 s per run) and
Docker Desktop's background RAM footprint — see ADR 0004. That
trade-off is already accepted.

### Why this is probably doable

- Upstream CI already builds on Linux. The build recipe exists and
  works for x86_64 Linux; we are asking it to target a different
  Linux arch, not a different OS.
- See *Where the cost lives* above — we only need to flip the image
  arch; the VM already runs arm64 natively.
- Fallback is trivial. Keep the amd64 image tag alongside. If the
  arm64 image misbehaves on a particular PDF, flip `$IMAGE` back to
  the known-good tag.
- Everything downstream (`inject-overlay.py`, overlay assets, daemon,
  extension) is arch-agnostic. Only the `$IMAGE` constant changes.

### Effort

**Half day to one day.** Risk concentrated in the cmake / poppler
version dance on arm64. Low overall because the x86_64 build is a
known-good reference point.

### Preserved constraints

- ADR 0001 (pdf2htmlEX remains the engine).
- ADR 0004 (Docker stays on-demand; daemon never touches Docker).
- `--platform linux/amd64` gets removed from scripts — flag its
  absence in code review so we don't accidentally silently fall back
  to emulation later.

## Option 2 — native macOS arm64 binary (no Docker at all)

Resurrect the 2019 Homebrew formula (or write a fresh build recipe)
so pdf2htmlEX runs directly as a darwin-arm64 executable. Invoke it
from the convert script the same way `extract-pdf-thumbs.sh` already
falls back to a local `pdftocairo` when one is on PATH.

**Win**: everything Option 1 gives us, *plus* the ~1–2 s Docker
container-startup per invocation, *plus* no Docker Desktop dependency
for conversion at all. On small PDFs this is the difference between
~2 s total and ~5 s total — a bigger proportional win than on large
docs. Could also unlock removing ADR 0004's "Docker must be running"
precondition for conversion entirely, simplifying the UX.

### Why this is risky

- The Homebrew formula has been rotting since 2019. cmake, poppler,
  fontforge, and cairo have all moved multiple major versions since.
  The open 2023 "cmake tool has been deleted" issue is a symptom.
- MacPorts has tried and failed across *every* macOS arm64 version
  from 11 to 26. Whatever breaks there will break for us too.
- pdf2htmlEX vendors its own patched poppler at a pinned version.
  Keeping that vendored copy building against modern clang/libc++
  on Apple Silicon is where most of the pain lives.
- No known-good reference exists on darwin-arm64 — we would be the
  first public success.

### Effort

**Weekend minimum, realistically several days, with real risk of
rabbit-holing into unfixable-without-upstream-patches territory.**

## Recommendation

**Do Option 1.** It captures the entire Rosetta speedup — which is
the only reason we are doing this — at a fraction of the effort and
with a safe fallback. The extra wins from Option 2 (no Docker
startup, no Docker Desktop dependency for conversions) are real but
small in absolute terms and come at much higher cost + risk.

Revisit Option 2 only if:

1. Option 1 turns out to be harder than estimated (unlikely given
   upstream arm64 Linux support in adjacent projects), or
2. We decide we want to eliminate the Docker dependency entirely —
   which would be a separate, larger architectural change that
   supersedes ADR 0004.

If we go with Option 1 and it works, promote this doc to an accepted
ADR (`0007-linux-arm64-pdf2htmlex-image.md`) and retire this file.

## Related

- [ADR 0001 — pdf2htmlEX as rendering engine](adr/0001-pdf-to-html-engine-pdf2htmlex.md)
- [ADR 0004 — On-demand Docker, always-on daemon](adr/0004-on-demand-docker-and-daemon-split.md)
- `scripts/pdf2html-convert.sh:28` — the `$IMAGE` constant that flips
- `scripts/extract-pdf-thumbs.sh` — already has a local-binary
  fast-path worth mirroring if Option 2 is ever revisited
