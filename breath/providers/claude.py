"""Limites do Claude (assinatura Pro/Max) via endpoint de uso da própria Anthropic.

Lê o token OAuth que o Claude Code já guarda em ~/.claude/.credentials.json,
apenas para leitura. O Breath nunca renova nem grava esse arquivo: renovar
o token giraria o refresh token e poderia deslogar o Claude Code.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import net
from ..config import CLAUDE_DIR, DATA_DIR
from . import result, window

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
NAME = "Claude"


def _read_token(home: Path) -> tuple[str | None, float | None, str | None]:
    path = home / ".credentials.json"
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


# ---------------------------------------------------------------- ritmo das consultas
# O endpoint de uso da Anthropic limita quantas vezes o mesmo login pode consultá-lo, e o próprio
# Claude Code também o consulta. Por isso:
#   - no máximo 1 consulta a cada MIN_INTERVAL por conta;
#   - depois de um 429, espera crescente (5, 10, 20, 40, 60 min) ou o Retry-After, o que for maior;
#   - a espera e a última leitura boa ficam em disco (reiniciar o Breath não "fura a fila");
#   - durante a espera, o cartão mostra a última leitura boa, com o horário dela.
MIN_INTERVAL = 300
BACKOFF_STEPS = (300, 600, 1200, 2400, 3600)
STATE_FILE = DATA_DIR / "claude-ritmo.json"
_lock = threading.Lock()


def _load_state() -> dict:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except OSError:
        pass


def _hhmm(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def _from_last(last: dict, message: str, as_of: float, status: str = "stale") -> dict:
    """Reaproveita a última leitura boa; janelas que já reiniciaram desde então aparecem zeradas."""
    now = time.time()
    wins = []
    for w in last.get("windows", []):
        w = dict(w)
        try:
            reset = datetime.fromisoformat(w["resets_at"]).timestamp() if w.get("resets_at") else None
        except (TypeError, ValueError):
            reset = None
        if reset and reset < now:
            w["used_percent"], w["resets_at"] = 0.0, None
        wins.append(w)
    out = dict(last, windows=wins, status=status, message=message)
    out["as_of"] = datetime.fromtimestamp(as_of, tz=timezone.utc).isoformat(timespec="seconds")
    return out


def collect(home: Path = CLAUDE_DIR) -> dict:
    key = str(home)
    now = time.time()
    with _lock:
        st = _load_state()
        acc = st.get(key) or {}
    last, last_at, next_at = acc.get("last"), acc.get("last_at", 0), acc.get("next_at", 0)

    if now < next_at:
        if acc.get("fails"):
            msg = f"A Anthropic limita as consultas de uso. Nova tentativa às {_hhmm(next_at)}."
            if last:
                return _from_last(last, f"Leitura de {_hhmm(last_at)}. {msg}", last_at)
            return result("claude", NAME, status="error", message=msg)
        if last:                                   # dentro do intervalo normal: a leitura ainda vale
            return _from_last(last, None, last_at, status="ok")

    token, expires, plan = _read_token(home)
    if not token:
        return result("claude", NAME, status="missing",
                      message="Não encontrei o login do Claude Code. Rode `claude` e faça login.")
    if expires and expires < now:
        return result("claude", NAME, status="expired", plan=plan,
                      message="Token expirado. Abra o Claude Code uma vez para renovar.")
    try:
        data = net.get_json(USAGE_URL, {
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
        })
    except net.HttpError as exc:
        if exc.status == 429:
            fails = int(acc.get("fails", 0)) + 1
            wait = max(BACKOFF_STEPS[min(fails, len(BACKOFF_STEPS)) - 1], exc.retry_after or 0)
            with _lock:
                st = _load_state()
                st[key] = dict(st.get(key) or {}, fails=fails, next_at=now + wait)
                _save_state(st)
            msg = f"A Anthropic limita as consultas de uso. Nova tentativa às {_hhmm(now + wait)}."
            if last:
                return _from_last(last, f"Leitura de {_hhmm(last_at)}. {msg}", last_at)
            return result("claude", NAME, status="error", plan=plan, message=msg)
        if exc.status in (401, 403):
            return result("claude", NAME, status="expired", plan=plan,
                          message="A Anthropic recusou o token. Abra o Claude Code para renovar.")
        if last:
            return _from_last(last, f"Leitura de {_hhmm(last_at)}. Falha ao consultar a Anthropic ({exc}).", last_at)
        return result("claude", NAME, status="error", plan=plan,
                      message=f"Falha ao consultar a Anthropic ({exc}).")
    except (ValueError, json.JSONDecodeError):
        return result("claude", NAME, status="error", plan=plan,
                      message="Resposta inesperada da Anthropic.")
    res = parse(data, plan)
    with _lock:
        st = _load_state()
        st[key] = {"last": res, "last_at": now, "next_at": now + MIN_INTERVAL, "fails": 0}
        _save_state(st)
    return res
