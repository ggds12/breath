"""Servidor HTTP local (somente 127.0.0.1) que entrega o painel e a API /api/status.

Defesas:
- Escuta apenas em 127.0.0.1.
- Confere o cabeçalho Host (bloqueia DNS rebinding).
- A API exige o cabeçalho `X-Breath: 1`. Sites externos não conseguem enviá-lo
  sem um preflight CORS, que este servidor nunca aprova.
- Somente GET/HEAD. Arquivos estáticos só de web/, com extensões permitidas.
- CSP restrita, sem frames, sem cache, sem referrer.
- Nenhum token sai do servidor para o navegador ou para os logs.
"""

from __future__ import annotations

import json
import mimetypes
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .config import BIND_HOST, CACHE_FILE, FORCE_MIN_INTERVAL, LIMITS_TTL, PORT, WEB_DIR
from . import accounts as accounts_mod, vault
from .accounts import discover
from .providers import apis
from .providers import claude, codex, now_iso

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ttf": "font/ttf",
    ".png": "image/png",
    ".webmanifest": "application/manifest+json",
}

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "font-src 'self'; connect-src 'self'; manifest-src 'self'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
    "Cache-Control": "no-store",
}


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.limits: list[dict] = self._load_cache()
        self.fetched = 0.0
        self.pool = ThreadPoolExecutor(max_workers=6)

    # Última leitura boa em disco: só porcentagens, horários e rótulos (nenhum segredo).
    # Serve para mostrar dados logo ao abrir e quando o provedor recusar uma consulta.
    @staticmethod
    def _load_cache() -> list[dict]:
        try:
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        out = []
        for p in data:
            pid = p.get("id") if isinstance(p, dict) else None
            if isinstance(pid, str) and isinstance(p.get("windows"), list):
                out.append(dict(p, status="stale", message="Última leitura salva; atualizando…"))
        return out

    @staticmethod
    def _save_cache(providers: list[dict]) -> None:
        keep = [p for p in providers if p.get("status") == "ok" and p.get("windows")]
        if not keep:
            return
        try:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = CACHE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(keep, ensure_ascii=False), encoding="utf-8")
            tmp.replace(CACHE_FILE)
        except OSError:
            pass

    def get_limits(self, force: bool) -> list[dict]:
        with self.lock:
            age = time.time() - self.fetched
            if self.limits and (age < LIMITS_TTL and not (force and age >= FORCE_MIN_INTERVAL)):
                return self.limits
            # Uma consulta por conta (várias contas do Claude e/ou do Codex), em paralelo.
            accounts = discover()
            collectors = {"claude": claude.collect, "codex": codex.collect}

            def run(acc):
                if acc.kind == "api":
                    return apis.collect(acc.cfg, vault.get_secret(acc.id))
                return collectors[acc.provider](acc.path)

            futures = [(acc, self.pool.submit(run, acc)) for acc in accounts]
            fresh = []
            for acc, fut in futures:
                try:
                    res = fut.result(timeout=20)
                except Exception as exc:  # nunca derruba o painel
                    res = {"status": "error", "message": type(exc).__name__, "windows": [], "as_of": now_iso()}
                res = dict(res, id=acc.id, name=acc.name, provider=acc.provider, kind=acc.kind)
                fresh.append(res)
            # Se a consulta falhou mas tínhamos dados bons, mostra os anteriores como "stale".
            previous = {p["id"]: p for p in self.limits}
            merged = []
            for p in fresh:
                old = previous.get(p["id"])
                if p["status"] == "error" and old and old.get("windows"):
                    old = dict(old, status="stale", message=p.get("message"))
                    merged.append(old)
                else:
                    merged.append(p)
            self.limits = merged
            self.fetched = time.time()
            self._save_cache(merged)
            return self.limits


STATE = State()


class Control:
    """Pedidos da página da janelinha ao ícone: manter aberta (fixar) e fechar."""

    def __init__(self):
        self._lock = threading.Lock()
        self.pinned = False
        self._close = False
        self._open_full = False
        self.height: float | None = None   # altura natural do conteúdo, informada pela página

    def set_pinned(self, value: bool) -> None:
        with self._lock:
            self.pinned = value

    def request_close(self) -> None:
        with self._lock:
            self._close = True

    def set_height(self, h: float) -> None:
        with self._lock:
            self.height = h

    def request_open_full(self) -> None:
        with self._lock:
            self._open_full = True

    def take_open_full(self) -> bool:
        with self._lock:
            requested, self._open_full = self._open_full, False
            return requested

    def take_close(self) -> bool:
        with self._lock:
            requested, self._close = self._close, False
            return requested

    def reset(self) -> None:
        with self._lock:
            self._close = False


CONTROL = Control()



class Handler(BaseHTTPRequestHandler):
    server_version = f"Breath/{__version__}"
    sys_version = ""

    # ----- utilidades -----
    def log_message(self, fmt, *args):  # registra só método e caminho, nunca query/cabeçalhos
        if sys.stderr is None:  # pythonw (sem console)
            return
        sys.stderr.write(f"[breath] {self.command} {urlsplit(self.path).path} -> {args[1] if len(args) > 1 else ''}\n")

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(status)
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, obj) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        return host in {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}

    # ----- métodos -----
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._host_ok():
            return self._send(421, b"host invalido", "text/plain; charset=utf-8")
        url = urlsplit(self.path)
        if url.path.startswith("/api/"):
            return self._api(url)
        return self._static(url.path)

    def _refuse(self):
        self._send(405, b"metodo nao permitido", "text/plain; charset=utf-8", {"Allow": "GET, HEAD"})

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _refuse

    def do_POST(self):
        """Únicas escritas: adicionar e remover contas (contas.json e cofre de chaves).
        Mesmas defesas da API (Host, cabeçalho X-Breath, origem) + JSON pequeno."""
        if not self._host_ok():
            return self._send(421, b"host invalido", "text/plain; charset=utf-8")
        url = urlsplit(self.path)
        if url.path not in ("/api/accounts/add", "/api/accounts/remove"):
            return self._refuse()
        if self.headers.get("X-Breath") != "1":
            return self._json(403, {"error": "cabeçalho X-Breath ausente"})
        if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            return self._json(403, {"error": "origem não permitida"})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._json(415, {"error": "envie JSON"})
        try:
            size = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            size = -1
        if not 0 < size <= 16_384:
            return self._json(413, {"error": "corpo inválido"})
        try:
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self._json(400, {"error": "JSON inválido"})
        try:
            if url.path == "/api/accounts/add":
                tipo = body.get("tipo")
                if tipo in ("claude", "codex"):
                    aid = accounts_mod.add_folder(tipo, body.get("nome"), body.get("pasta"))
                else:
                    key = body.get("chave")
                    if not (isinstance(key, str) and 8 <= len(key.strip()) <= 512):
                        return self._json(400, {"error": "informe a chave de API"})
                    aid = accounts_mod.add_api(body)
                    if not vault.set_secret(aid, key.strip()):
                        accounts_mod.remove(aid)
                        return self._json(500, {"error": "não consegui guardar a chave no cofre do Windows"})
            else:
                aid = body.get("id")
                if not (isinstance(aid, str) and accounts_mod.remove(aid)):
                    return self._json(404, {"error": "conta não encontrada"})
                vault.delete_secret(aid)
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        STATE.fetched = 0      # próxima leitura já considera a mudança
        return self._json(200, {"ok": True, "id": aid})

    # ----- API -----
    def _api(self, url):
        if self.headers.get("X-Breath") != "1":
            return self._json(403, {"error": "cabeçalho X-Breath ausente"})
        if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            return self._json(403, {"error": "origem não permitida"})
        if url.path == "/api/status":
            force = parse_qs(url.query).get("refresh") == ["1"]
            limits = STATE.get_limits(force)
            return self._json(200, {
                "version": __version__,
                "generated_at": now_iso(),
                "providers": limits,
            })
        if url.path == "/api/pin":
            CONTROL.set_pinned(parse_qs(url.query).get("on") == ["1"])
            return self._json(200, {"ok": True})
        if url.path == "/api/size":
            try:
                h = float(parse_qs(url.query)["h"][0])
            except (KeyError, ValueError, IndexError):
                return self._json(400, {"error": "parâmetro inválido"})
            if 200 <= h <= 3000:
                CONTROL.set_height(h)
            return self._json(200, {"ok": True})
        if url.path == "/api/open-full":
            CONTROL.request_open_full()
            return self._json(200, {"ok": True})
        if url.path == "/api/close":
            CONTROL.request_close()
            return self._json(200, {"ok": True})
        if url.path == "/api/health":
            return self._json(200, {"ok": True, "version": __version__})
        return self._json(404, {"error": "não encontrado"})

    # ----- estáticos -----
    def _static(self, path: str):
        if path in ("", "/"):
            path = "/index.html"
        try:
            target = (WEB_DIR / path.lstrip("/")).resolve()
            target.relative_to(WEB_DIR)          # impede ../
        except (ValueError, OSError):
            return self._send(404, b"nao encontrado", "text/plain; charset=utf-8")
        ctype = STATIC_TYPES.get(target.suffix.lower())
        if not ctype or not target.is_file():
            return self._send(404, b"nao encontrado", "text/plain; charset=utf-8")
        self._send(200, target.read_bytes(), ctype)


def main(argv: list[str] | None = None) -> None:
    import argparse

    ap = argparse.ArgumentParser(prog="breath", description="Painel local de limites do Claude e do Codex")
    ap.add_argument("--no-tray", action="store_true", help="só o servidor, sem ícone na bandeja")
    ap.add_argument("--show", action="store_true", help="abre a janelinha ao iniciar")
    args = ap.parse_args(argv)
    use_tray = sys.platform == "win32" and not args.no_tray

    mimetypes.init()
    try:
        httpd = ThreadingHTTPServer((BIND_HOST, PORT), Handler)
    except OSError:
        msg = f"A porta {PORT} já está em uso. O Breath provavelmente já está aberto (veja os ícones ocultos)."
        if use_tray:
            from .tray import message_box
            message_box(msg)
        raise SystemExit(msg)
    httpd.daemon_threads = True
    print(f"Breath {__version__} em http://127.0.0.1:{PORT}  (Ctrl+C para sair)", flush=True)

    if not use_tray:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()
        return

    from .tray import Tray

    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        Tray(STATE.get_limits, on_quit=httpd.shutdown, control=CONTROL).run(show=args.show)
    finally:
        httpd.server_close()
