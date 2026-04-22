// pdf_viewer extension — dynamic rule sync.
//
// The static rules.json handles `.pdf$` URLs. This service worker handles
// everything else: it fetches /cache-urls from the daemon and installs one
// dynamic declarativeNetRequest rule per cached entry so that any URL whose
// host+path matches a cached doc gets intercepted — even signed URLs like
// Blackboard's that don't end in `.pdf`.
//
// Ordering: dynamic rules use priority 3, the static redirect uses 1, and
// the passthrough allow uses 2. Highest priority wins, so:
//   - cached URL click → dynamic (p3) → /view serves HTML
//   - unknown `.pdf$` URL → static (p1) → /view 307s with marker
//   - 307-target with marker → allow (p2) → native viewer
//   - cache miss on non-.pdf URL → no rule → browser opens natively
//
// Service workers in MV3 can be terminated, so we use chrome.alarms (survives
// suspension) rather than setInterval.

const DAEMON = 'http://127.0.0.1:7435';
const DYNAMIC_RULE_ID_BASE = 1000;
const SYNC_ALARM = 'pdfviewer-sync';

// Escape a string for inclusion inside a regex character class / pattern.
// RE2 (what Chrome's declarativeNetRequest uses) honors the same special
// characters as ECMAScript regex for escaping.
function escapeRegex(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Serialize syncs — multiple listeners (onInstalled, onStartup, top-level
// call, alarm) can fire within milliseconds of each other on extension load.
// Without this, two concurrent calls both read getDynamicRules() → [], both
// try to add id 1000, second one fails with "Rule with id 1000 does not have
// a unique ID." The mutex collapses concurrent calls into one.
let _syncInFlight = null;

function syncCachedRules() {
    if (_syncInFlight) return _syncInFlight;
    _syncInFlight = _runSync().finally(() => { _syncInFlight = null; });
    return _syncInFlight;
}

async function _runSync() {
    let entries;
    try {
        const resp = await fetch(`${DAEMON}/cache-urls`, { cache: 'no-store' });
        if (!resp.ok) {
            console.warn(`pdf_viewer: /cache-urls returned ${resp.status}`);
            return;
        }
        entries = await resp.json();
    } catch (e) {
        // Daemon down, or CORS / network error. Leave any previously-installed
        // rules in place — stale is better than an empty ruleset.
        console.warn('pdf_viewer: /cache-urls fetch failed —', e.message);
        return;
    }

    if (!Array.isArray(entries)) {
        console.warn('pdf_viewer: /cache-urls returned non-array', entries);
        return;
    }

    // Chrome's declarativeNetRequest requires regexFilter to be pure ASCII.
    // If the encoded path somehow still contains non-ASCII (macOS NFD vs
    // NFC unicode forms between Python's JSON and JS can bite here), skip
    // that rule with a warning rather than failing the whole sync.
    const isAscii = (s) => /^[\x00-\x7f]*$/.test(s);

    const addRules = [];
    let ruleIdCounter = DYNAMIC_RULE_ID_BASE;

    for (const entry of entries) {
        let rule;
        if (entry.kind === 'file') {
            // Chromium percent-encodes file:// paths segment-by-segment
            // (spaces → %20, non-ASCII → UTF-8 %XX). Mirror that so the
            // regex filter matches the encoded URL the browser sends.
            const encodedPath = entry.path
                .split('/')
                .map(encodeURIComponent)
                .join('/');
            const regexFilter = `^file://${escapeRegex(encodedPath)}(?:\\?.*)?$`;

            if (!isAscii(regexFilter)) {
                console.warn(
                    'pdf_viewer: non-ASCII in regex — skipping rule for',
                    entry.path,
                    'encodedPath:', JSON.stringify(encodedPath),
                    'first non-ASCII code point:',
                    regexFilter.split('').find(c => c.charCodeAt(0) > 127)?.charCodeAt(0)?.toString(16)
                );
                continue;
            }
            rule = {
                id: ruleIdCounter++,
                priority: 3,
                action: {
                    type: 'redirect',
                    redirect: {
                        url: `${DAEMON}/view?path=${encodeURIComponent(entry.path)}`
                    }
                },
                condition: {
                    regexFilter,
                    resourceTypes: ['main_frame']
                }
            };
        } else {
            // URL kind.
            const regexFilter = `^https?://${escapeRegex(entry.host + entry.path)}(?:\\?.*)?$`;
            if (!isAscii(regexFilter)) {
                console.warn(
                    'pdf_viewer: non-ASCII in regex — skipping rule for',
                    entry.host + entry.path
                );
                continue;
            }
            rule = {
                id: ruleIdCounter++,
                priority: 3,
                action: {
                    type: 'redirect',
                    redirect: {
                        regexSubstitution: `${DAEMON}/view?url=\\0`
                    }
                },
                condition: {
                    regexFilter,
                    resourceTypes: ['main_frame'],
                    excludedRequestDomains: ['localhost', '127.0.0.1']
                }
            };
        }
        addRules.push(rule);
    }

    // We only touch IDs >= DYNAMIC_RULE_ID_BASE so static rule IDs (1, 2)
    // are never disturbed.
    let existing;
    try {
        existing = await chrome.declarativeNetRequest.getDynamicRules();
    } catch (e) {
        console.error('pdf_viewer: getDynamicRules failed —', e.message);
        return;
    }
    if (!Array.isArray(existing)) {
        console.warn('pdf_viewer: getDynamicRules returned non-array:', existing);
        existing = [];
    }

    const removeRuleIds = existing
        .filter(r => r && typeof r.id === 'number' && r.id >= DYNAMIC_RULE_ID_BASE)
        .map(r => r.id);

    console.log(
        `pdf_viewer: existing dynamic ids`,
        existing.map(r => r && r.id),
        `→ removing`, removeRuleIds
    );

    // Two-step update instead of one atomic call. Chromium has historically
    // had a bug where an update that both removes id N and adds id N in the
    // same call can fail with "Rule with id N does not have a unique ID" —
    // the uniqueness check runs against the pre-removal state. Splitting into
    // a remove call followed by an add call sidesteps this entirely.
    if (removeRuleIds.length > 0) {
        try {
            await chrome.declarativeNetRequest.updateDynamicRules({
                removeRuleIds
            });
        } catch (e) {
            console.error('pdf_viewer: remove stage failed —', e.message);
            return;
        }
    }
    if (addRules.length > 0) {
        try {
            await chrome.declarativeNetRequest.updateDynamicRules({
                addRules
            });
        } catch (e) {
            console.error('pdf_viewer: add stage failed —', e.message);
            return;
        }
    }
    console.log(
        `pdf_viewer: synced ${addRules.length} cache entries ` +
        `(${removeRuleIds.length} stale rules removed)`
    );
}

// -----------------------------------------------------------------------------
// Navigation signals — extension-mediated tab navigation.
//
// The convert script POSTs {from_url, to_url} to the daemon after a cache-miss
// conversion finishes. This long-poll loop picks up those signals and calls
// chrome.tabs.update(tabId, {url}) on matching tabs.
//
// Why not AppleScript from the convert script itself: Chromium's Apple Event
// handler pulls the browser to the front on *any* tab mutation, causing a
// visible focus flash even with snapshot-and-restore tricks. chrome.tabs.update
// has no such side effect.
//
// MV3 service workers die after ~30s of inactivity, but an in-flight fetch
// counts as activity — so while the long-poll holds, the SW stays alive.
// If the SW *does* die between fetches, the periodic alarm (0.5min) wakes
// it up and startNavPollLoop() restarts the loop.
// -----------------------------------------------------------------------------

const NAV_POLL_TIMEOUT_SEC = 25;
const NAV_POLL_ERROR_BACKOFF_MS = 2000;

let _navPollRunning = false;

async function navigateTab({ from_url, to_url }) {
    try {
        // `chrome.tabs.query({url: matchPattern})` ignores query strings, so
        // we query all tabs and filter by exact-URL match (the from_url the
        // convert script captured includes the `_pdfvw=passthrough` marker
        // and must match byte-for-byte).
        const allTabs = await chrome.tabs.query({});
        const matches = allTabs.filter(t => t.url === from_url);
        if (matches.length === 0) {
            console.log(`pdf_viewer: nav signal — no tab with URL ${from_url}`);
            return;
        }
        for (const tab of matches) {
            await chrome.tabs.update(tab.id, { url: to_url });
            console.log(
                `pdf_viewer: navigated tab ${tab.id}: ${from_url} → ${to_url}`
            );
        }
    } catch (e) {
        console.warn('pdf_viewer: navigateTab failed —', e.message);
    }
}

async function startNavPollLoop() {
    if (_navPollRunning) return;
    _navPollRunning = true;
    console.log('pdf_viewer: nav poll loop starting');
    try {
        while (true) {
            try {
                const resp = await fetch(
                    `${DAEMON}/signal/navigate/wait?timeout=${NAV_POLL_TIMEOUT_SEC}`,
                    { cache: 'no-store' }
                );
                if (!resp.ok) {
                    console.warn(
                        `pdf_viewer: /signal/navigate/wait → ${resp.status}`
                    );
                    await new Promise(r => setTimeout(r, NAV_POLL_ERROR_BACKOFF_MS));
                    continue;
                }
                const signals = await resp.json();
                for (const sig of signals) {
                    await navigateTab(sig);
                }
            } catch (e) {
                // Daemon down / network hiccup. Back off before retry so we
                // don't pin CPU if the daemon is hard-down.
                console.warn('pdf_viewer: nav poll fetch failed —', e.message);
                await new Promise(r => setTimeout(r, NAV_POLL_ERROR_BACKOFF_MS));
            }
        }
    } finally {
        _navPollRunning = false;
    }
}

// Fire on every plausible re-entry point, so new conversions become
// interceptable without a browser restart.
chrome.runtime.onInstalled.addListener(() => {
    syncCachedRules();
    startNavPollLoop();
});
chrome.runtime.onStartup.addListener(() => {
    syncCachedRules();
    startNavPollLoop();
});

chrome.alarms.create(SYNC_ALARM, { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === SYNC_ALARM) {
        syncCachedRules();
        // Restart the nav loop if it died (SW was suspended and fetch got
        // cancelled). The flag prevents doubling up when it's still alive.
        startNavPollLoop();
    }
});

// Also fire once on service-worker startup (covers the case where the SW
// was terminated and got woken up by an event other than the ones above).
syncCachedRules();
startNavPollLoop();
