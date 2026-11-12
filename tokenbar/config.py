"""Configuração. Tudo vem de variáveis de ambiente com padrões seguros."""

from __future__ import annotations

import os
from pathlib import Path

HOME = Path.home()

# Só aceitamos portas de usuário; o host é sempre loopback (não configurável de propósito).
BIND_HOST = "127.0.0.1"
PORT = int(os.environ.get("TOKENBAR_PORT", "7878"))
if not 1024 <= PORT <= 65535:
    raise SystemExit("TOKENBAR_PORT precisa estar entre 1024 e 65535")

CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or HOME / ".claude")
CODEX_DIR = Path(os.environ.get("CODEX_HOME") or HOME / ".codex")

# Consultar as APIs de uso a cada N segundos no máximo (o painel pede a cada 60 s).
LIMITS_TTL = int(os.environ.get("TOKENBAR_LIMITS_TTL", "60"))
# Intervalo mínimo entre atualizações forçadas pelo botão.
FORCE_MIN_INTERVAL = 15
# Logs locais: quantos dias analisar.
HISTORY_DAYS = 7

# Únicos hosts com os quais o TokenBar conversa. Qualquer outro é recusado.
ALLOWED_HOSTS = frozenset({"api.anthropic.com", "chatgpt.com"})

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
