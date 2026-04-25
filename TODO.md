- [ ] Make :open be a bit more picky on what files to show, using a zoxide based algo from the "open" db
- [ ] Maybe UI for eviction in :open
- [ ] Fix overview navigation / selection polish: clicking an outline entry should immediately move the highlighted active chapter in the outline, and in the overview/pages surface `j` / `k` should move between entries with `Enter` selecting the focused one.
- [ ] Make fingers select more things and make the UI pretty.
- [ ] Explore native `Cmd+F` over the whole document via a per-page shadow text layer; start with V1, likely continue to V2 after validating Chromium behavior. See [docs/native-browser-find-shadow-layer.md](docs/native-browser-find-shadow-layer.md).
- [ ] Acutually integrate with/fork pdf2htmlEX. There is obviously a lot of additional value in integrating with pdf2htmlEX.
- [ ] Make it so the text is ordered correctly on the page from vertical spacing, so scrolling in mark mode with j, k etc doesnt jump up and down if e.g. the pdf text of figures is in a different text layer.
- [ ] Could also rewrite it to work on arm64 (only 18k LOC, potentially)
- [ ] Customize some of the rendering for our liking
- [ ] In addition, if all of this happens, we could make it a monoloth and ship as a single MacOS menu bar app for example
- [ ] A MacOs menu bar that shows the progress of our current conversion etc, lightweight
- [ ] Integrate/fork vimium. This allows me to make a way better, and way more logical context selection tool (being able to scroll off pages, chapters easily). Maybe the easiest solution: Ignore all vimium keys except for o, p etc, in pdfs, and fork the vimium source code, and make a single browser extension, vimium + the loclahost redirect
- [ ] Follow up native selection expansion viewport behavior. Current state: native browser selection + `e` extends pagewise and native browser selection + `c` selects the whole outline chapter, with touched pages force-rendered so the selection survives the render window. Acceptable landing for now: chapter selection works even when the viewport does not move, so I can trust that the full chapter is marked. Unresolved part: trying to synthetically scroll the viewport to the end of the promoted chapter selection has been unreliable and appears to double up with another selection-driven smooth scroll path. Plausible fixes to revisit: wait for the browser's own post-selection scroll and only correct if the tail still sits outside the scrolloff band; derive the target from the actual final painted selection rect rather than a text-node boundary; or own the whole flow via overlay-native visual mode / Vimium fork if exact visual-mode semantics become important.
- [ ] Improve documentation and README and profile README framing. This is a structurally useful tool, because:

In a transition phase, the world is still operating in .pdf file format. This is an insight from KTN: Old protocols die slowly. Need backward compatibility.

The old UI surfaces like powerpoint etc are dying. Why use powerpoint when claude design does the trick, or even a simpler, natural language ingterface.

Why even use code when images with detailed NL descriptions can recreate the same functionality (think Image 2 for slidedeck).

Either way: these workflows still have to boil down to the .pdf format for the forseable future, as that is the format of our world. And interactive ui is less important. What is important is easily being able to use as context, select elements, mark text and feed to llms, and pinpoint exactly where I, the human, see room for improvement. And then having this with an open, programmatic API so it can integrate across all of my llm tools.

Hence: Building an ergonomic pdf viewer like this is structurally important in this day and age.

This is a power user tool and UI. Of course not the only group to target, but: Targeting power users is strategically sound as they will be driving the progress the next 5 years. We are dropping red-bull cans in bins at Harvard.
https://info.arxiv.org/about/accessible_HTML.html This exists. Further epmhasis

Fun mention: I am now tackling the pdf space in the AI era, analogue to how Steipete did it in the old times.

- [ ] Links perlexity and the command f search text overlay. How can we make that overlay in a way that it integrates with the perplexity assistant sidebar
- [ ] 1063 vs 1073 "Internet" in KTN pensumbok: Why
