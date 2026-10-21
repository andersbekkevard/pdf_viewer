from __future__ import annotations

import pathlib
import sys
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import main  # noqa: E402


def upload(body: bytes = b"", headers: dict[str, str] | None = None) -> Request:
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "PUT", "headers": raw}, receive)


class BrowserFetchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        main._pending_nav_signals.clear()
        main._nav_signal_event = None
        main._fetches.clear()

    async def request_fetch(self, url="https://gated.test/hw.pdf?_pdfvw=passthrough"):
        return (await main.signal_fetch(main.FetchSignal(url=url)))["id"]

    async def test_fetch_signal_reaches_pollers(self):
        fetch_id = await self.request_fetch()
        got = await main.signal_navigate_wait(timeout=0.05, since=0)
        self.assertEqual(
            [(s["type"], s["id"], s["url"]) for s in got],
            [("fetch", fetch_id, "https://gated.test/hw.pdf?_pdfvw=passthrough")],
        )

    async def test_pending_then_bytes_then_gone(self):
        fetch_id = await self.request_fetch()
        self.assertEqual((await main.fetch_get(fetch_id)).status_code, 202)
        await main.fetch_put(fetch_id, upload(b"%PDF-1.7 body", {
            "X-Source-Content-Type": "application/pdf",
            "X-Source-Content-Disposition": 'inline; filename="HW2.pdf"',
        }))
        resp = await main.fetch_get(fetch_id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.body, b"%PDF-1.7 body")
        self.assertEqual(resp.headers["content-disposition"], 'inline; filename="HW2.pdf"')
        with self.assertRaises(HTTPException):
            await main.fetch_get(fetch_id)

    async def test_started_ack_is_visible_to_the_script(self):
        fetch_id = await self.request_fetch()
        await main.fetch_put(fetch_id, upload(headers={"X-Fetch-Started": "1"}))
        resp = await main.fetch_get(fetch_id)
        self.assertEqual(resp.status_code, 202)
        self.assertIn(b'"started"', resp.body)
        await main.fetch_put(fetch_id, upload(b"%PDF late"))
        self.assertEqual((await main.fetch_get(fetch_id)).body, b"%PDF late")

    async def test_extension_error_is_reported(self):
        fetch_id = await self.request_fetch()
        await main.fetch_put(fetch_id, upload(headers={"X-Fetch-Error": "HTTP 403"}))
        resp = await main.fetch_get(fetch_id)
        self.assertEqual(resp.status_code, 502)
        self.assertIn(b"HTTP 403", resp.body)

    async def test_first_answer_wins(self):
        # Two browsers with the same tab open both answer.
        fetch_id = await self.request_fetch()
        await main.fetch_put(fetch_id, upload(b"%PDF first"))
        second = await main.fetch_put(fetch_id, upload(b"%PDF second"))
        self.assertEqual(second, {"accepted": False})
        self.assertEqual((await main.fetch_get(fetch_id)).body, b"%PDF first")

    async def test_unrequested_upload_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            await main.fetch_put(12345, upload(b"%PDF"))
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_non_http_url_rejected(self):
        with self.assertRaises(HTTPException):
            await self.request_fetch("file:///etc/passwd")
        self.assertEqual(main._pending_nav_signals, [])

    async def test_results_expire(self):
        fetch_id = await self.request_fetch()
        await main.fetch_put(fetch_id, upload(b"%PDF"))
        future = main.time.time() + main._FETCH_TTL_SEC + 1
        with patch.object(main.time, "time", return_value=future):
            with self.assertRaises(HTTPException):
                await main.fetch_get(fetch_id)


if __name__ == "__main__":
    unittest.main()
