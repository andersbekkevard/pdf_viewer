# ADR 0003 — Keyboard shortcut design under Vimium

**Status**: Accepted
**Date**: 2026-04-21

## Context

Vimium is the reason this project exists (see ADR 0001). It's also a
massive keybinding surface in its own right — find, marks, history
navigation, tab management, link hints, visual mode, zoom, scroll,
vomnibar, etc. Every single-letter and `g`/`y`/`z`-prefix key is claimed
for something.

Our HTML viewer needs shortcuts too: sidebar toggle, render-all toggle,
page counter toggle, command palette, cheatsheet, page jumps, outline
navigation. If we naïvely claim keys, two failure modes appear:

1. **Direct collisions.** We bind `?` → cheatsheet; Vimium also handles
   `?` → its help. Both listeners fire; outcome depends on capture-phase
   ordering and is fragile across Vimium versions.
2. **Prefix swallowing.** Vimium treats `g`, `y`, `z` as prefix keys.
   Press `g`, then a non-bound follow-up, and Vimium silently drops the
   sequence. Our `gn` / `gp` handlers in page JS never fire because the
   keystroke is consumed before reaching us.

We also can't cleanly "beat Vimium" in capture phase: Vimium installs
its listeners before our DOMContentLoaded runs, and any arms race with
`stopPropagation`/`preventDefault` is brittle and user-hostile (breaks
when Vimium updates).

## Decision

Design the shortcut layer to **coexist** with Vimium, not compete.
Specifically:

### (1) Defer to Vimium for anything it already does well

We do **not** reimplement:

| Feature | Vimium's key | Why not reimplement |
|---|---|---|
| Bookmarks | `m{a-z}`, `'{a-z}` | Vimium's marks persist across pages/reloads, URL-scoped. Better than anything we'd build. |
| Find | `/`, `n`, `N`, `*`, `#` | Native DOM scan, works on anything. Scope is shaped by render-window (ADR 0002). |
| Zoom | `zi`, `zo`, `z0` | Exactly what we need. |
| Top/bottom | `gg`, `G` | Scrolls `#page-container` correctly after our runtime kill. |
| Half/full page | `d`, `u` | Same. |
| History | `H`, `L` | Standard. |

### (2) Only claim keys Vimium demonstrably doesn't bind

Full Vimium binding list was cataloged (see plan.md §7 "Permanently
rejected"). Claimed keys chosen from the complement:

| Key      | Action                       | Verified free in Vimium |
|----------|------------------------------|-------------------------|
| `s`      | Toggle sidebar               | Yes |
| `⌘.`     | Toggle sidebar               | Yes |
| `A`      | Toggle render-all            | Yes (uppercase; `a` also free) |
| `⌘⇧.`    | Toggle page counter          | Yes |
| `:`      | Open command palette         | Yes |
| `?`      | Toggle cheatsheet            | **Conflicts** — requires Vimium exclusion rule for `localhost:7435` |
| `Esc`    | Close overlays / clear selection | Yes (Vimium also uses it; our capture-phase listener runs first, chain priority palette → cheatsheet → selection) |

### (3) Command palette `:` as the universal numeric-arg interface

Instead of picking vim-style `[N]<letter>` bindings (which require a
count-prefix state machine AND acceptable letters — we have few), we
route every parameterized command through the palette:

- `:42` → goto page 42
- `:pin 30` → pin cursor at 30%
- `:buffer 20` → render ±20 pages
- `:all` → toggle render-all
- `:yank` → copy "Chapter · p. N"
- `:counter` → toggle page counter
- `:help` → cheatsheet

Single entry point. No vimgolf over what `gp` could mean. Zero count-prefix
parsing. The cost is ~4 extra keystrokes for goto-page vs a hypothetical
`97gp` — trivially small, and avoids all Vimium conflicts.

### (4) Guard every listener against focus inside inputs

Every keydown handler starts with `if (isInputTarget(e.target)) return`.
Prevents our shortcuts from firing while the user is typing in our own
palette input, Vimium's find input, or any `<input>` in the page.

### (5) Accept user-side Vimium config as part of the install

For `?` to toggle our cheatsheet, the user has to add `localhost:7435`
to Vimium's "Keys to pass through" exclusion list with key `?`. This
is explicit and documented. We don't try to hide the requirement.

## Rationale

**Coexistence beats competition.** Vimium is load-bearing for the
user's whole browser workflow, not just this tool. Breaking Vimium
behavior on our page — even narrowly — degrades the whole experience.
The opposite failure mode (a missing shortcut on our page) is
recoverable via the palette.

**`:` palette eliminates the binding problem.** Every parameterized
command has a natural home in the palette. We don't have to pick
between `[N]gp` vs `[N]go` vs `[N]gz` — none of them. The palette is
keyboard-fast (`:42<CR>`) and discoverable (`:help`).

**Respect the prefix semantics.** When we considered `g`-prefixed
toggles (like `gr` for render-all), the user's reaction was "weird
letter for a toggle." `g` means "go" in vim tradition — navigation and
set-value verbs. We use it only for those (none currently in scope,
the palette covers them all). Toggles get uppercase letters or modifier
chords.

**Capture phase sparingly.** The Escape handler genuinely needs capture
phase (Vimium listens in capture too, and our priority chain —
palette → cheatsheet → selection — must win). Everywhere else we use
bubble phase and trust the target/input guard.

## Consequences

### Accepted downsides

- **Minor Vimium config required.** `?` exclusion for `localhost:7435`
  is a one-time setting. Documented in plan.md §8 "Known gotchas".
- **No count-prefix vim-style jumps.** `97go` doesn't exist; users type
  `:97<CR>` instead. Small ergonomic cost, large implementation saving.
- **Sidebar toggle duplicated (`s` AND `⌘.`).** Both exist because `s`
  is fast but `⌘.` is mouse-kb-swap-proof. Trivial duplication.

### Wins

- No fragile capture-phase arms race with Vimium.
- Palette is self-documenting (`:help` opens the cheatsheet).
- Adding new commands = one line in `runCommand()` dispatcher. No new
  keybinding to vet against Vimium's map.
- The pattern "shortcuts for toggles, palette for values" maps cleanly
  to future additions (dark mode toggle, export selection, etc.).

### Implicit guarantees

- We will never bind `m`, `'`, `` ` ``, `?`, `n`, `p`, `o`, `[[`, `]]`,
  `gs`, `ge`, `gg`, `G`, `H`, `L`, or any character Vimium's full map
  claims, at the top level. If we ever feel tempted, this ADR is the
  gate.

## Related

- ADR 0001 (why Vimium matters to us at all)
- ADR 0002 (render window — the thing the palette's `:buffer` controls)
- plan.md §7 "Shortcut registry" (current + rejected + proposed)
- `assets/overlay.js` — `register*Handler` and `openPalette` /
  `runCommand` implementations
