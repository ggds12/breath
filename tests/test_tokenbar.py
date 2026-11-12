"""Testes sem rede: parsers com dados de exemplo e as defesas do servidor HTTP.

Rodar:  python -m unittest discover -s tests -v
"""

import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

os.environ["TOKENBAR_PORT"] = "17878"
_tmp = tempfile.mkdtemp(prefix="tokenbar-test-")
os.environ["CLAUDE_CONFIG_DIR"] = str(Path(_tmp, "claude"))
os.environ["CODEX_HOME"] = str(Path(_tmp, "codex"))

from tokenbar import localusage, net, server  # noqa: E402
from tokenbar.providers import claude, codex  # noqa: E402


class ParserTests(unittest.TestCase):
    def test_claude_parse(self):
        data = {
            "five_hour": {"utilization": 18.0, "resets_at": "2026-11-12T23:19:59+00:00"},
            "seven_day": {"utilization": 77.0, "resets_at": "2026-11-13T06:59:59+00:00"},
            "limits": [{"kind": "weekly_scoped", "percent": 47,
                        "resets_at": "2026-11-13T06:59:59+00:00",
                        "scope": {"model": {"display_name": "Opus"}}}],
        }
        r = claude.parse(data, "pro")
        self.assertEqual(r["plan"], "Pro")
        self.assertEqual([w["id"] for w in r["windows"]], ["session", "weekly", "weekly_opus"])
        self.assertEqual(r["windows"][1]["used_percent"], 77.0)

    def test_codex_parse_api_drops_personal_fields(self):
        data = {"email": "x@example.com", "user_id": "u", "plan_type": "plus",
                "rate_limit": {"limit_reached": True,
                               "primary_window": {"used_percent": 100, "limit_window_seconds": 18000, "reset_at": 1794520072},
                               "secondary_window": {"used_percent": 16, "limit_window_seconds": 604800, "reset_at": 1795106872}}}
        r = codex.parse_api(data)
        self.assertNotIn("x@example.com", json.dumps(r))
        self.assertEqual(r["windows"][0]["label"], "Sessão · 5h")
        self.assertEqual(r["windows"][1]["used_percent"], 16)

    def test_codex_logs_expired_window_resets_to_zero(self):
        past = time.time() - 60
        snap = {"timestamp": "2026-11-12T10:00:00Z", "rate_limits": {
            "primary": {"used_percent": 90, "window_minutes": 300, "resets_at": past},
            "secondary": {"used_percent": 40, "window_minutes": 10080, "resets_at": time.time() + 3600}}}
        r = codex.parse_logs(snap, None)
        self.assertEqual(r["windows"][0]["used_percent"], 0.0)
        self.assertEqual(r["windows"][1]["used_percent"], 40)
        self.assertEqual(r["status"], "stale")

    def test_percent_is_clamped(self):
        r = claude.parse({"five_hour": {"utilization": 140}}, None)
        self.assertEqual(r["windows"][0]["used_percent"], 100.0)


class LocalUsageTests(unittest.TestCase):
    def test_claude_dedupes_and_codex_uses_deltas(self):
        today = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"
        proj = Path(_tmp, "claude", "projects", "p")
        proj.mkdir(parents=True, exist_ok=True)
        line = {"type": "assistant", "timestamp": today, "requestId": "r1",
                "message": {"id": "m1", "model": "x", "usage": {
                    "input_tokens": 10, "output_tokens": 5,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 100}}}
        (proj / "s.jsonl").write_text("\n".join([json.dumps(line)] * 3), encoding="utf-8")

        sess = Path(_tmp, "codex", "sessions", "2026")
        sess.mkdir(parents=True, exist_ok=True)
        evs = [{"timestamp": today, "payload": {"type": "token_count", "info": {"total_token_usage": {
            "input_tokens": i * 100, "cached_input_tokens": i * 50, "output_tokens": i * 10, "total_tokens": i * 110}}}}
            for i in (1, 2, 2, 3)]
        (sess / "rollout-x.jsonl").write_text("\n".join(json.dumps(e) for e in evs), encoding="utf-8")

        s = localusage.summary(2)
        t = s["days"][-1]
        self.assertEqual(t["claude"]["input"], 10)          # 3 linhas iguais contam 1 vez
        self.assertEqual(t["claude"]["cache_read"], 100)
        self.assertEqual(t["codex"]["total"], 330)          # 110 + 110 + 0 + 110
        self.assertEqual(t["codex"]["output"], 30)


class NetTests(unittest.TestCase):
    def test_rejects_unknown_host_and_http(self):
        with self.assertRaises(ValueError):
            net.get_json("https://evil.example.com/x", {})
        with self.assertRaises(ValueError):
            net.get_json("http://api.anthropic.com/x", {})


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.STATE.limits = [{"id": "claude", "name": "Claude", "status": "ok", "windows": []}]
        server.STATE.fetched = time.time() + 3600   # evita qualquer chamada de rede
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 17878), server.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def req(self, method, path, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", 17878, timeout=5)
        c.request(method, path, headers=headers or {})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, dict(r.getheaders()), body

    def test_index_has_security_headers(self):
        st, h, _ = self.req("GET", "/")
        self.assertEqual(st, 200)
        self.assertIn("default-src 'none'", h["Content-Security-Policy"])
        self.assertEqual(h["X-Frame-Options"], "DENY")

    def test_api_requires_header(self):
        self.assertEqual(self.req("GET", "/api/status")[0], 403)
        st, _, body = self.req("GET", "/api/status", {"X-TokenBar": "1"})
        self.assertEqual(st, 200)
        self.assertIn("providers", json.loads(body))

    def test_foreign_origin_blocked(self):
        st = self.req("GET", "/api/status", {"X-TokenBar": "1", "Origin": "https://evil.com"})[0]
        self.assertEqual(st, 403)

    def test_dns_rebinding_blocked(self):
        self.assertEqual(self.req("GET", "/", {"Host": "evil.com:17878"})[0], 421)

    def test_write_methods_refused(self):
        for m in ("POST", "PUT", "DELETE", "OPTIONS"):
            self.assertEqual(self.req(m, "/api/status")[0], 405, m)

    def test_path_traversal(self):
        for p in ("/../tokenbar/config.py", "/%2e%2e/README.md", "/assets/../../tokenbar/net.py"):
            self.assertEqual(self.req("GET", p)[0], 404, p)


if __name__ == "__main__":
    unittest.main()
