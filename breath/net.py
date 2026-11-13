"""Cliente HTTP mínimo e restrito.

- Só HTTPS, com verificação de certificado (contexto padrão do sistema).
- Só para hosts da lista em config.ALLOWED_HOSTS, ou os de uma conta que você adicionou
  (passados explicitamente em extra_hosts; sempre HTTPS).
- Não segue redirecionamentos (o cabeçalho Authorization nunca vai parar em outro host).
- Limita o tamanho da resposta.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from . import __version__
from .config import ALLOWED_HOSTS

MAX_BYTES = 1_000_000
USER_AGENT = f"breath/{__version__} (local)"


class HttpError(Exception):
    def __init__(self, status: int, message: str = "", retry_after: float | None = None):
        super().__init__(f"HTTP {status} {message}".strip())
        self.status = status
        self.retry_after = retry_after       # segundos sugeridos pelo servidor (cabeçalho Retry-After)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        raise HttpError(code, "redirecionamento bloqueado")


_opener = urllib.request.build_opener(
    _NoRedirect(),
    urllib.request.HTTPSHandler(context=ssl.create_default_context()),
)


def get_json(url: str, headers: dict[str, str], timeout: float = 12.0, extra_hosts=()) -> dict:
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname not in ALLOWED_HOSTS and parts.hostname not in set(extra_hosts)):
        raise ValueError(f"host não permitido: {parts.hostname}")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json", **headers},
        method="GET",
    )
    try:
        with _opener.open(req, timeout=timeout) as resp:
            body = resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        try:
            retry = float(exc.headers.get("Retry-After")) if exc.headers.get("Retry-After") else None
        except (TypeError, ValueError):
            retry = None
        raise HttpError(exc.code, retry_after=retry) from None
    except urllib.error.URLError as exc:
        raise HttpError(0, f"sem conexão ({exc.reason})") from None
    if len(body) > MAX_BYTES:
        raise HttpError(0, "resposta grande demais")
    data = json.loads(body)
    if not isinstance(data, dict):
        raise HttpError(0, "resposta inesperada")
    return data
