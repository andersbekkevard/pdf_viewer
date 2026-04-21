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

    const addRules = entries.map((entry, i) => ({
        id: DYNAMIC_RULE_ID_BASE + i,
        priority: 3,
        action: {
            type: 'redirect',
            redirect: {
                regexSubstitution: `${DAEMON}/view?url=\\0`
            }
        },
        condition: {
            // Anchor on exact host+path. Accept any query string (signed
            // URLs change the query on every visit but the host+path is
            // stable — that's what the daemon hashes too).
            regexFilter: `^https?://${escapeRegex(entry.host + entry.path)}(?:\\?.*)?$`,
            resourceTypes: ['main_frame'],
            excludedRequestDomains: ['localhost', '127.0.0.1']
        }
    }));

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

// Fire on every plausible re-entry point, so new conversions become
// interceptable without a browser restart.
chrome.runtime.onInstalled.addListener(syncCachedRules);
chrome.runtime.onStartup.addListener(syncCachedRules);

chrome.alarms.create(SYNC_ALARM, { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === SYNC_ALARM) syncCachedRules();
});

// Also sync once on service-worker startup (covers the case where the SW
// was terminated and got woken up by an event other than the ones above).
syncCachedRules();
