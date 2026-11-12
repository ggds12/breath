"""Limites do Claude (assinatura Pro/Max) via endpoint de uso da própria Anthropic.

Lê o token OAuth que o Claude Code já guarda em ~/.claude/.credentials.json,
apenas para leitura. O TokenBar nunca renova nem grava esse arquivo: renovar
o token giraria o refresh token e poderia deslogar o Claude Code.
"""

from __future__ import annotations

import json
import time

from .. import net
from ..config import CLAUDE_DIR
from . import result, window

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
NAME = "Claude"


def _read_token() -> tuple[str | None, float | None, str | None]:
    path = CLAUDE_DIR / ".credentials.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, None, None
    oauth = data.get("claudeAiOauth") or {}
    token = oauth.get("accessToken")
    expires = oauth.get("expiresAt")
    plan = oauth.get("subscriptionType")
    return token, (float(expires) / 1000 if expires else None), plan


def parse(data: dict, plan: str | None) -> dict:
    wins = []
    fh = data.get("five_hour") or {}
    if fh:
        wins.append(window("session", "Sessão · 5h", fh.get("utilization"), fh.get("resets_at"), 5 * 3600))
    sd = data.get("seven_day") or {}
    if sd:
        wins.append(window("weekly", "Semana", sd.get("utilization"), sd.get("resets_at"), 7 * 86400))

    # Limites semanais por modelo (ex.: "Semana · Opus"), quando existirem.
    for item in data.get("limits") or []:
        if not isinstance(item, dict) or item.get("kind") != "weekly_scoped":
            continue
        model = ((item.get("scope") or {}).get("model") or {}).get("display_name")
        if not model:
            continue
        wins.append(window(f"weekly_{model.lower()}", f"Semana · {model}",
                           item.get("percent"), item.get("resets_at"), 7 * 86400))
    if not wins:
        for key, label in (("seven_day_opus", "Opus"), ("seven_day_sonnet", "Sonnet")):
            v = data.get(key)
            if isinstance(v, dict):
                wins.append(window(f"weekly_{label.lower()}", f"Semana · {label}",
                                   v.get("utilization"), v.get("resets_at"), 7 * 86400))
    return result("claude", NAME, status="ok", plan=(plan or "").capitalize() or None,
                  windows=wins, source="api")


_backoff_until = 0.0   # depois de um 429, espera antes de consultar de novo


def collect() -> dict:
    global _backoff_until
    if time.time() < _backoff_until:
        return result("claude", NAME, status="error",
                      message="A Anthropic pediu uma pausa nas consultas; tentando de novo em instantes.")
    token, expires, plan = _read_token()
    if not token:
        return result("claude", NAME, status="missing",
                      message="Não encontrei o login do Claude Code. Rode `claude` e faça login.")
    if expires and expires < time.time():
        return result("claude", NAME, status="expired", plan=plan,
                      message="Token expirado. Abra o Claude Code uma vez para renovar.")
    try:
        data = net.get_json(USAGE_URL, {
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
        })
    except net.HttpError as exc:
        if exc.status == 429:
            _backoff_until = time.time() + 300
            return result("claude", NAME, status="error", plan=plan,
                          message="A Anthropic pediu uma pausa nas consultas; tentando de novo em 5 min.")
        if exc.status in (401, 403):
            return result("claude", NAME, status="expired", plan=plan,
                          message="A Anthropic recusou o token. Abra o Claude Code para renovar.")
        return result("claude", NAME, status="error", plan=plan,
                      message=f"Falha ao consultar a Anthropic ({exc}).")
    except (ValueError, json.JSONDecodeError):
        return result("claude", NAME, status="error", plan=plan,
                      message="Resposta inesperada da Anthropic.")
    return parse(data, plan)
