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

os.environ["BREATH_PORT"] = "17878"
_tmp = tempfile.mkdtemp(prefix="breath-test-")
os.environ["CLAUDE_CONFIG_DIR"] = str(Path(_tmp, "claude"))
os.environ["CODEX_HOME"] = str(Path(_tmp, "codex"))

from breath import net, server  # noqa: E402
from breath.providers import claude, codex  # noqa: E402


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


class TraySummaryTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "só Windows")
    def test_summary_text(self):
        from breath.tray import summarize
        txt = summarize([
            {"id": "claude", "name": "Claude", "windows": [
                {"id": "session", "used_percent": 22.4}, {"id": "weekly", "used_percent": 78}]},
            {"id": "codex", "name": "Codex", "windows": []},
        ])
        self.assertEqual(txt, "Breath · Claude 22% (sem. 78%) · Codex —")
        self.assertLess(len(txt), 128)   # limite da dica do ícone



class AccountsTests(unittest.TestCase):
    """Descoberta de várias contas por pastas de login."""

    def setUp(self):
        from breath import accounts
        self.acc = accounts
        self.home = Path(tempfile.mkdtemp(prefix="breath-home-"))
        self._old = (accounts.HOME, accounts.ACCOUNTS_FILE, os.environ.pop("CLAUDE_CONFIG_DIR", None),
                     os.environ.pop("CODEX_HOME", None))
        accounts.HOME = self.home
        accounts.ACCOUNTS_FILE = self.home / "contas.json"

    def tearDown(self):
        self.acc.HOME, self.acc.ACCOUNTS_FILE = self._old[0], self._old[1]
        os.environ["CLAUDE_CONFIG_DIR"] = str(Path(_tmp, "claude"))
        os.environ["CODEX_HOME"] = str(Path(_tmp, "codex"))

    def _login(self, folder, marker):
        d = self.home / folder
        d.mkdir(parents=True, exist_ok=True)
        (d / marker).write_text("{}", encoding="utf-8")
        return d

    def test_default_accounts_always_listed(self):
        ids = [a.id for a in self.acc.discover()]
        self.assertEqual(ids, ["claude", "codex"])

    def test_extra_folders_become_accounts(self):
        self._login(".claude", ".credentials.json")
        self._login(".claude-trabalho", ".credentials.json")
        (self.home / ".claude-vazia").mkdir()            # sem login: ignorada
        self._login(".codex_pessoal", "auth.json")
        found = {a.id: a.name for a in self.acc.discover()}
        self.assertEqual(found["claude:trabalho"], "Claude · Trabalho")
        self.assertEqual(found["codex:pessoal"], "Codex · Pessoal")
        self.assertNotIn("claude:vazia", found)
        self.assertIn("claude", found)

    def test_config_file_overrides_provider(self):
        far = self._login("logins/claude-b", ".credentials.json")
        (self.home / "contas.json").write_text(json.dumps({
            "claude": [{"nome": "Pessoal", "pasta": str(self.home / ".claude")},
                       {"nome": "Empresa", "pasta": str(far)}]}), encoding="utf-8")
        accs = self.acc.discover()
        claude = [a for a in accs if a.provider == "claude"]
        self.assertEqual([a.name for a in claude], ["Claude · Pessoal", "Claude · Empresa"])
        self.assertEqual(claude[1].path, far)
        self.assertTrue(any(a.id == "codex" for a in accs))   # codex segue a descoberta automática

    def test_same_folder_is_not_duplicated(self):
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.home / ".claude")
        self._login(".claude", ".credentials.json")
        self.assertEqual([a.id for a in self.acc.discover() if a.provider == "claude"], ["claude"])

    def test_bad_config_is_ignored(self):
        (self.home / "contas.json").write_text("{ isso não é json", encoding="utf-8")
        self.assertEqual([a.id for a in self.acc.discover()], ["claude", "codex"])


class ApiConnectorTests(unittest.TestCase):
    """Conectores por chave de API (respostas de exemplo, sem rede)."""

    def setUp(self):
        from breath.providers import apis
        self.apis = apis

    def test_deepseek_balance_with_budget(self):
        data = {"is_available": True, "balance_infos": [{"currency": "USD", "total_balance": "15.00"}]}
        wins, msg = self.apis._parse({"tipo": "deepseek", "orcamento": 20}, data)
        self.assertEqual(wins[0]["used_percent"], 25.0)
        self.assertEqual(wins[0]["detail"], "US$ 15,00")
        self.assertIsNone(msg)

    def test_deepseek_without_budget_shows_value_only(self):
        data = {"is_available": False, "balance_infos": [{"currency": "CNY", "total_balance": "3.5"}]}
        wins, msg = self.apis._parse({"tipo": "deepseek"}, data)
        self.assertIsNone(wins[0]["used_percent"])
        self.assertEqual(wins[0]["detail"], "¥ 3,50")
        self.assertIn("insuficiente", msg)

    def test_openrouter_key_limit(self):
        data = {"data": {"limit": 100, "limit_remaining": 74.5, "usage": 25.5, "limit_reset": "monthly"}}
        wins, _ = self.apis._parse({"tipo": "openrouter"}, data)
        self.assertAlmostEqual(wins[0]["used_percent"], 25.5)
        self.assertEqual(wins[0]["label"], "Crédito · mês")

    def test_kimi_balance(self):
        wins, _ = self.apis._parse({"tipo": "kimi", "orcamento": 10}, {"data": {"available_balance": 2.5}})
        self.assertEqual(wins[0]["used_percent"], 75.0)

    def test_custom_paths(self):
        cfg = {"tipo": "custom", "campo_usado": "items.0.used", "campo_limite": "items.0.max"}
        wins, _ = self.apis._parse(cfg, {"items": [{"used": 30, "max": 120}]})
        self.assertEqual(wins[0]["used_percent"], 25.0)
        wins, msg = self.apis._parse({"tipo": "custom", "campo_saldo": "nada"}, {"x": 1})
        self.assertEqual(wins, [])
        self.assertIn("campos", msg)

    def test_custom_rejects_plain_http(self):
        r = self.apis.collect({"tipo": "custom", "url": "http://exemplo.com/x", "campo_saldo": "a"}, "k" * 10)
        self.assertEqual(r["status"], "error")

    def test_missing_key(self):
        self.assertEqual(self.apis.collect({"tipo": "deepseek"}, None)["status"], "missing")


class AccountEditTests(unittest.TestCase):
    """Adicionar/remover contas no contas.json."""

    def setUp(self):
        from breath import accounts
        self.acc = accounts
        self.home = Path(tempfile.mkdtemp(prefix="breath-edit-"))
        self._old = (accounts.HOME, accounts.ACCOUNTS_FILE)
        os.environ.pop("CLAUDE_CONFIG_DIR", None); os.environ.pop("CODEX_HOME", None)
        accounts.HOME = self.home
        accounts.ACCOUNTS_FILE = self.home / "contas.json"

    def tearDown(self):
        self.acc.HOME, self.acc.ACCOUNTS_FILE = self._old
        os.environ["CLAUDE_CONFIG_DIR"] = str(Path(_tmp, "claude"))
        os.environ["CODEX_HOME"] = str(Path(_tmp, "codex"))

    def test_add_and_remove_api(self):
        aid = self.acc.add_api({"tipo": "deepseek", "nome": "Meu DeepSeek", "orcamento": "20", "chave": "nao-salva"})
        self.assertEqual(aid, "deepseek:meu-deepseek")
        raw = (self.home / "contas.json").read_text(encoding="utf-8")
        self.assertNotIn("nao-salva", raw)                       # a chave nunca vai para o arquivo
        self.assertTrue(any(a.id == aid and a.kind == "api" for a in self.acc.discover()))
        self.assertTrue(self.acc.remove(aid))
        self.assertFalse(any(a.id == aid for a in self.acc.discover()))

    def test_add_folder_keeps_existing_and_remove_returns_to_auto(self):
        (self.home / ".claude").mkdir()
        self.acc.add_folder("claude", "Trabalho", str(self.home / "outra"))
        ids = [a.id for a in self.acc.discover() if a.provider == "claude"]
        self.assertEqual(ids, ["claude:principal", "claude:trabalho"])
        self.assertTrue(self.acc.remove("claude:trabalho"))
        self.assertEqual([a.id for a in self.acc.discover() if a.provider == "claude"], ["claude"])

    def test_hide_auto_discovered(self):
        self.assertTrue(self.acc.remove("codex"))
        self.assertFalse(any(a.id == "codex" for a in self.acc.discover()))

    def test_custom_validation(self):
        with self.assertRaises(ValueError):
            self.acc.add_api({"tipo": "custom", "url": "https://x.com/u"})          # sem campos
        with self.assertRaises(ValueError):
            self.acc.add_api({"tipo": "deepseek", "orcamento": "-3"})


class ClaudePacingTests(unittest.TestCase):
    """Ritmo das consultas à Anthropic: intervalo mínimo, espera crescente após 429, última leitura."""

    def setUp(self):
        from breath import net
        from breath.providers import claude
        self.c, self.net = claude, net
        self.home = Path(tempfile.mkdtemp(prefix="breath-cl-"))
        (self.home / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {
            "accessToken": "tok", "expiresAt": (time.time() + 3600) * 1000, "subscriptionType": "pro"}}), encoding="utf-8")
        self._old = (claude.STATE_FILE, net.get_json)
        claude.STATE_FILE = self.home / "ritmo.json"
        self.calls = 0

    def tearDown(self):
        self.c.STATE_FILE, self.net.get_json = self._old

    def _ok(self, *a, **k):
        self.calls += 1
        soon = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + 3600))
        return {"five_hour": {"utilization": 40, "resets_at": soon}, "seven_day": {"utilization": 70, "resets_at": soon}}

    def _limited(self, *a, **k):
        self.calls += 1
        raise self.net.HttpError(429, retry_after=0)

    def test_min_interval_reuses_reading(self):
        self.net.get_json = self._ok
        r1 = self.c.collect(self.home)
        r2 = self.c.collect(self.home)
        self.assertEqual(self.calls, 1)                       # a 2ª não foi à rede
        self.assertEqual(r2["status"], "ok")
        self.assertEqual(r2["windows"][0]["used_percent"], 40)

    def test_rate_limit_shows_last_reading_and_backs_off(self):
        self.net.get_json = self._ok
        self.c.collect(self.home)
        st = json.loads(self.c.STATE_FILE.read_text(encoding="utf-8"))
        st[str(self.home)]["next_at"] = 0                      # libera a próxima consulta
        self.c.STATE_FILE.write_text(json.dumps(st), encoding="utf-8")
        self.net.get_json = self._limited
        r = self.c.collect(self.home)
        self.assertEqual(r["status"], "stale")
        self.assertEqual(r["windows"][1]["used_percent"], 70)  # última leitura boa
        self.assertIn("Nova tentativa", r["message"])
        calls = self.calls
        self.c.collect(self.home)                              # dentro da espera: não consulta
        self.assertEqual(self.calls, calls)
        st = json.loads(self.c.STATE_FILE.read_text(encoding="utf-8"))
        self.assertGreaterEqual(st[str(self.home)]["next_at"] - time.time(), 290)

    def test_backoff_grows(self):
        self.net.get_json = self._limited
        waits = []
        for _ in range(3):
            self.c.collect(self.home)
            st = json.loads(self.c.STATE_FILE.read_text(encoding="utf-8"))
            waits.append(round(st[str(self.home)]["next_at"] - time.time()))
            st[str(self.home)]["next_at"] = 0
            self.c.STATE_FILE.write_text(json.dumps(st), encoding="utf-8")
        self.assertTrue(waits[0] < waits[1] < waits[2])

    def test_expired_window_resets_to_zero(self):
        old = {"windows": [{"id": "session", "label": "Sessão · 5h", "used_percent": 90,
                            "resets_at": "2000-01-01T00:00:00+00:00", "window_seconds": 18000}]}
        r = self.c._from_last(old, None, time.time())
        self.assertEqual(r["windows"][0]["used_percent"], 0.0)


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
        st, _, body = self.req("GET", "/api/status", {"X-Breath": "1"})
        self.assertEqual(st, 200)
        self.assertIn("providers", json.loads(body))

    def test_foreign_origin_blocked(self):
        st = self.req("GET", "/api/status", {"X-Breath": "1", "Origin": "https://evil.com"})[0]
        self.assertEqual(st, 403)

    def test_dns_rebinding_blocked(self):
        self.assertEqual(self.req("GET", "/", {"Host": "evil.com:17878"})[0], 421)

    def test_write_methods_refused(self):
        for m in ("POST", "PUT", "DELETE", "OPTIONS"):
            self.assertEqual(self.req(m, "/api/status")[0], 405, m)

    def test_popup_commands(self):
        self.assertEqual(self.req("GET", "/api/pin?on=1")[0], 403)         # exige o cabeçalho
        self.assertEqual(self.req("GET", "/api/pin?on=1", {"X-Breath": "1"})[0], 200)
        self.assertTrue(server.CONTROL.pinned)
        self.req("GET", "/api/pin?on=0", {"X-Breath": "1"})
        self.assertFalse(server.CONTROL.pinned)
        self.req("GET", "/api/close", {"X-Breath": "1"})
        self.assertTrue(server.CONTROL.take_close())
        self.assertFalse(server.CONTROL.take_close())                       # é consumido uma vez
        self.req("GET", "/api/open-full", {"X-Breath": "1"})
        self.assertTrue(server.CONTROL.take_open_full())

    def _post(self, path, body, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", 17878, timeout=5)
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        h = {"Content-Type": "application/json", "X-Breath": "1"}
        h.update(headers or {})
        c.request("POST", path, body=data, headers=h)
        r = c.getresponse(); out = (r.status, r.read()); c.close()
        return out

    def test_account_write_endpoints_are_guarded(self):
        self.assertEqual(self._post("/api/accounts/add", {}, {"X-Breath": ""})[0], 403)
        self.assertEqual(self._post("/api/accounts/add", {}, {"Origin": "https://evil.com"})[0], 403)
        self.assertEqual(self._post("/api/accounts/add", {}, {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self._post("/api/accounts/add", b"[]")[0], 400)
        self.assertEqual(self._post("/api/accounts/add", b"x" * 20000)[0], 413)
        self.assertEqual(self._post("/api/outra", {})[0], 405)

    def test_add_api_account_stores_key_in_vault(self):
        from breath import accounts
        saved = {}
        old = (server.vault.set_secret, server.vault.delete_secret, accounts.ACCOUNTS_FILE)
        server.vault.set_secret = lambda aid, key: saved.__setitem__(aid, key) or True
        server.vault.delete_secret = lambda aid: saved.pop(aid, None)
        accounts.ACCOUNTS_FILE = Path(tempfile.mkdtemp(prefix="breath-srv-")) / "contas.json"
        try:
            st, body = self._post("/api/accounts/add", {"tipo": "openrouter", "nome": "OR", "chave": "sk-or-12345678"})
            self.assertEqual(st, 200)
            aid = json.loads(body)["id"]
            self.assertEqual(saved[aid], "sk-or-12345678")
            self.assertNotIn("sk-or", accounts.ACCOUNTS_FILE.read_text(encoding="utf-8"))
            self.assertEqual(self._post("/api/accounts/add", {"tipo": "openrouter", "chave": "curta"})[0], 400)
            self.assertEqual(self._post("/api/accounts/remove", {"id": aid})[0], 200)
            self.assertNotIn(aid, saved)
        finally:
            server.vault.set_secret, server.vault.delete_secret, accounts.ACCOUNTS_FILE = old

    def test_path_traversal(self):
        for p in ("/../breath/config.py", "/%2e%2e/README.md", "/assets/../../breath/net.py"):
            self.assertEqual(self.req("GET", p)[0], 404, p)


if __name__ == "__main__":
    unittest.main()
