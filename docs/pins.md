# Pins

Pins are the proposed first-class replacement for ad hoc PDF marks. A pin is a
fast, persistent return point in the current document: drop it, continue
reading, and jump back with very little friction.

## User intent

- Dropping a pin should take as few keystrokes as possible.
- Jumping back to the most recent or active pin should be one quick command.
- The same visible pin should keep the same key until the user changes it.
- There should be a nimble overview of all pins in the document.
- The overview should make position recognizable: page number, chapter if
  available, quote/title, and possibly a page thumbnail from the sidebar.
- If no chapter context exists, a selected quote can become the pin title.
- Recency matters: a simple "mark here, go work, jump back" flow is more
  important than a heavyweight bookmark manager.

## Open product questions

- Should pins be keyed by letters, numerical order, recency, or explicit names?
- Should one document support multiple pin sets or "tabs" of pins, or is that
  too much state for the first version?
- Should pins integrate with Vimium marks, replace them, or intentionally avoid
  them because current Vimium marks are unreliable in this viewer?
- Should the first implementation persist pins across sessions, or start with
  in-tab state to prove the interaction model?

## MVP constraints

- Do not add new global keybindings before checking `docs/keybindings.md`.
- Prefer palette commands if a key conflict is likely.
- Pin controls must be semantic buttons or otherwise Vimium-hintable.
- The first implementation should be easy to throw away if the interaction
  model feels wrong.
- Do not couple pins to a future pdf2htmlEX or Vimium fork. Those are later
  architectural tracks.

## Candidate first slice

1. A command drops a pin at the current page and viewport anchor.
2. If text is selected, the selected text becomes the default title.
3. A command jumps back to the most recent pin.
4. A palette/menu lists pins with page number, chapter, and title.
5. The list supports keyboard navigation and selection.

