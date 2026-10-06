from __future__ import annotations

import asyncio
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import main  # noqa: E402


class NavSignalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        main._pending_nav_signals.clear()
        main._nav_signal_event = None

    async def wait(self, since=None, timeout=1.0):
        return await main.signal_navigate_wait(timeout=timeout, since=since)

    async def test_every_cursor_poller_gets_each_signal(self):
        # Two browsers (or profiles) listening: both see the signal, so the one
        # holding the tab can act on it whichever polled first.
        a = asyncio.create_task(self.wait(since=0))
        b = asyncio.create_task(self.wait(since=0))
        await asyncio.sleep(0.05)
        main._queue_navigate_signal("https://x.test/a.pdf", "http://localhost/a.html")
        got_a, got_b = await asyncio.gather(a, b)
        self.assertEqual([s["from_url"] for s in got_a], ["https://x.test/a.pdf"])
        self.assertEqual(got_a, got_b)
        self.assertEqual(len(main._pending_nav_signals), 1)  # not consumed

    async def test_cursor_returns_only_newer_signals(self):
        main._queue_navigate_signal("https://x.test/1.pdf", "http://localhost/1.html")
        first = await self.wait(since=0)
        main._queue_navigate_signal("https://x.test/2.pdf", "http://localhost/2.html")
        second = await self.wait(since=first[-1]["id"])
        self.assertEqual([s["from_url"] for s in second], ["https://x.test/2.pdf"])
        self.assertEqual(await self.wait(since=second[-1]["id"], timeout=0.05), [])

    async def test_ids_strictly_increase(self):
        for i in range(50):
            main._queue_navigate_signal(f"https://x.test/{i}.pdf", "http://localhost/x.html")
        ids = [s["id"] for s in main._pending_nav_signals]
        self.assertEqual(ids, sorted(set(ids)))
        self.assertLess(ids[-1], 2**53)  # exact in the extension's JavaScript

    async def test_legacy_poller_without_cursor_consumes(self):
        main._queue_navigate_signal("https://x.test/a.pdf", "http://localhost/a.html")
        self.assertEqual(len(await self.wait()), 1)
        self.assertEqual(await self.wait(timeout=0.05), [])

    async def test_legacy_poller_does_not_take_signals_from_cursor_pollers(self):
        # An old extension build polling without a cursor must not delete the
        # signal before an updated one (in another browser) has seen it.
        legacy = asyncio.create_task(self.wait())
        await asyncio.sleep(0.05)
        main._queue_navigate_signal("https://x.test/a.pdf", "http://localhost/a.html")
        self.assertEqual(len(await legacy), 1)
        got = await self.wait(since=0, timeout=0.05)
        self.assertEqual([s["from_url"] for s in got], ["https://x.test/a.pdf"])
        self.assertNotIn("legacy_taken", got[0])

    async def test_waiter_times_out_empty(self):
        self.assertEqual(await self.wait(since=0, timeout=0.05), [])

    async def test_expired_signals_are_not_delivered(self):
        main._queue_navigate_signal("https://x.test/old.pdf", "http://localhost/old.html")
        future = main.time.time() + main._NAV_SIGNAL_TTL_SEC + 1
        with patch.object(main.time, "time", return_value=future):
            self.assertEqual(await self.wait(since=0, timeout=0.05), [])

    async def test_sync_rules_signals_also_broadcast(self):
        a = asyncio.create_task(self.wait(since=0))
        b = asyncio.create_task(self.wait(since=0))
        await asyncio.sleep(0.05)
        main._queue_extension_sync_signal("998117f977edf08f", "converted")
        got_a, got_b = await asyncio.gather(a, b)
        self.assertEqual([s["type"] for s in got_a], ["sync_rules"])
        self.assertEqual(got_a, got_b)


if __name__ == "__main__":
    unittest.main()
