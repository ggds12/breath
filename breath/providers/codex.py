"""Limites do Codex (assinatura ChatGPT).

1) Tenta o endpoint de uso do ChatGPT com o token que o Codex guarda em
   ~/.codex/auth.json (somente leitura, sem renovar).
2) Se falhar, usa o último `rate_limits` gravado nos logs de sessão locais
   (~/.codex/sessions/**/rollout-*.jsonl), que funciona 100% offline.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .. import net
from ..config import CODEX_DIR
from . import epoch_to_iso, result, window

USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
NAME = "Codex"


def _label(seconds: int | None, fallback: str) -> str:
    if seconds == 5 * 3600:
        return "Sessão · 5h"
    if seconds == 7 * 86400:
        return "Semana"
    if seconds:
        hours = seconds / 3600
        return f"Janela · {hours:g}h" if hours < 48 else f"Janela · {hours / 24:g}d"
    return fallback


def parse_api(data: dict) -> dict:
    rl = data.get("rate_limit") or {}
    wins = []
    for key, fallback in (("primary_window", "Sessão · 5h"), ("secondary_window", "Semana")):
        w = rl.get(key)
        if not isinstance(w, dict):
            continue
        secs = w.get("limit_window_seconds")
        wid = "session" if key == "primary_window" else "weekly"
        wins.append(window(wid, _label(secs, fallback), w.get("used_percent"),
                           epoch_to_iso(w.get("reset_at")), secs))
    plan = data.get("plan_type")
    msg = "Limite atingido." if rl.get("limit_reached") else None
    return result("codex", NAME, status="ok", plan=plan.capitalize() if plan else None,
                  windows=wins, source="api", message=msg)


def _recent_rollouts(home: Path = CODEX_DIR, limit: int = 20) -> list[Path]:
    root = home / "sessions"
    if not root.is_dir():
        return []
    cutoff = time.time() - 8 * 86400
    files = [p for p in root.rglob("rollout-*.jsonl") if p.stat().st_mtime >= cutoff]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def latest_from_logs(home: Path = CODEX_DIR) -> dict | None:
    """Último snapshot de rate_limits (limit_id 'codex') nos logs locais."""
    for path in _recent_rollouts(home):
        best = None
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"rate_limits"' not in line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    payload = ev.get("payload") or {}
                    rl = payload.get("rate_limits") or {}
                    if rl.get("limit_id") not in (None, "codex") or not rl.get("primary"):
                        continue
                    best = (ev.get("timestamp"), rl)
        except OSError:
            continue
        if best:
            return {"timestamp": best[0], "rate_limits": best[1]}
    return None


def parse_logs(snap: dict, reason: str | None) -> dict:
    rl = snap["rate_limits"]
    now = time.time()
    wins = []
    for key, wid, fallback in (("primary", "session", "Sessão · 5h"), ("secondary", "weekly", "Semana")):
        w = rl.get(key)
        if not isinstance(w, dict):
            continue
        secs = int(w["window_minutes"]) * 60 if w.get("window_minutes") else None
        reset = w.get("resets_at")
        used = w.get("used_percent")
        # Se a janela já reiniciou desde o log, o uso real é 0.
        if reset and float(reset) < now:
            used = 0.0
            reset = None
        wins.append(window(wid, _label(secs, fallback), used, epoch_to_iso(reset), secs))
    plan = rl.get("plan_type")
    note = "Dados dos logs locais do Codex (atualizam quando você usa o Codex)."
    if reason:
        note = f"{reason} {note}"
    return result("codex", NAME, status="stale", plan=plan.capitalize() if plan else None,
                  windows=wins, source="logs", message=note, as_of=snap.get("timestamp"))


def _read_auth(home: Path) -> tuple[str | None, str | None]:
    try:
        data = json.loads((home / "auth.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None, None
    tokens = data.get("tokens") or {}
    return tokens.get("access_token"), tokens.get("account_id")


def collect(home: Path = CODEX_DIR) -> dict:
    token, account = _read_auth(home)
    reason = None
    if token:
        headers = {"Authorization": f"Bearer {token}"}
        if account:
            headers["ChatGPT-Account-Id"] = account
        try:
            return parse_api(net.get_json(USAGE_URL, headers))
        except net.HttpError as exc:
            reason = ("Login do Codex expirado; abra o Codex para renovar."
                      if exc.status in (401, 403) else f"API indisponível ({exc}).")
        except (ValueError, json.JSONDecodeError):
            reason = "Resposta inesperada da API."
    else:
        reason = "Login do Codex não encontrado."

    snap = latest_from_logs(home)
    if snap:
        return parse_logs(snap, reason)
    status = "missing" if not token else "error"
    return result("codex", NAME, status=status, message=reason)


