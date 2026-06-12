# Non-goals

Explicitly out of scope. Revisit carefully before adding any of these.

- **Auth-gated PDF fetching** (SharePoint, paywalls, corporate SSO).
  Let the browser handle the download; user drops into Raycast to
  convert the local copy.
- **Smart auto-detection of PDFs without a `.pdf` extension.** Manual
  Raycast trigger is the escape hatch. The extension deliberately does
  not try to sniff Content-Type.
- **In-viewer annotations or notes.** Use Obsidian or Preview.
- **Real-time collaboration / multi-user.**
- **Mobile-native app.** Tailscale-to-laptop-daemon is the fallback
  (phase 8, unbuilt).
- **Public URLs.** Daemon always binds to `127.0.0.1`.
- **Auto-installing the conversion toolchain.** Conversion uses a native
  arm64 pdf2htmlEX binary (ADR 0011); scripts fail fast with "native
  pdf2htmlEX not installed" rather than building or fetching it. (Docker
  is no longer involved in conversion at all.)
- **`file://` interception at the extension level.**
  `declarativeNetRequest` can't match `file://`; a content script
  would be needed. Deferred until it actually bites.
- **Integrating `marker` into the daemon.** Kept as a standalone
  parallel tool until a compelling in-viewer use case appears.
