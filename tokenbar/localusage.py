"""Tokens consumidos por dia, lidos dos logs locais (nada sai da máquina).

Claude Code: ~/.claude/projects/**/*.jsonl, mensagens do assistente com `usage`.
             A mesma resposta pode aparecer em várias linhas; deduplicamos por
             (message.id, requestId).
Codex:       ~/.codex/sessions/**/rollout-*.jsonl, eventos `token_count`.
             Usamos a diferença do `total_token_usage` acumulado de cada sessão.

Os resultados por arquivo ficam em cache pela dupla (mtime, tamanho).
"""

from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import CLAUDE_DIR, CODEX_DIR, HISTORY_DAYS

_cache: dict[str, tuple[float, int, object]] = {}
_lock = threading.Lock()


def _local_day(ts: str | None) -> date | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().date()
    except ValueError:
        return None


def _recent(root: Path, pattern: str, days: int) -> list[Path]:
    if not root.is_dir():
        return []
    cutoff = time.time() - (days + 1) * 86400
    out = []
    for p in root.rglob(pattern):
        try:
            if p.stat().st_mtime >= cutoff:
                out.append(p)
        except OSError:
            pass
    return out


def _cached(path: Path, parser):
    try:
        st = path.stat()
    except OSError:
        return None
    key = str(path)
    hit = _cache.get(key)
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]
    value = parser(path)
    _cache[key] = (st.st_mtime, st.st_size, value)
    return value


# ---------- Claude ----------

def _parse_claude_file(path: Path) -> dict:
    """{(msg_id, req_id): (day_iso, model, usage)}"""
    out: dict = {}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"usage"' not in line or '"assistant"' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") != "assistant":
                    continue
                msg = ev.get("message") or {}
                usage = msg.get("usage")
                if not isinstance(usage, dict):
                    continue
                day = _local_day(ev.get("timestamp"))
                if not day:
                    continue
                key = (msg.get("id") or ev.get("uuid"), ev.get("requestId"))
                out[key] = (day.isoformat(), msg.get("model") or "?", {
                    "input": int(usage.get("input_tokens") or 0),
                    "output": int(usage.get("output_tokens") or 0),
                    "cache_write": int(usage.get("cache_creation_input_tokens") or 0),
                    "cache_read": int(usage.get("cache_read_input_tokens") or 0),
                })
    except OSError:
        pass
    return out


def _empty_claude():
    return {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0, "total": 0}


def claude_days(days: int) -> dict[str, dict]:
    merged: dict = {}
    for f in _recent(CLAUDE_DIR / "projects", "*.jsonl", days):
        part = _cached(f, _parse_claude_file)
        if part:
            merged.update(part)
    per_day: dict[str, dict] = {}
    for day, _model, u in merged.values():
        d = per_day.setdefault(day, _empty_claude())
        for k, v in u.items():
            d[k] += v
        d["total"] += sum(u.values())
    return per_day


# ---------- Codex ----------

def _parse_codex_file(path: Path) -> dict[str, dict]:
    per_day: dict[str, dict] = {}
    prev = {"input": 0, "cached": 0, "output": 0, "total": 0}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"token_count"' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = ev.get("payload") or {}
                if payload.get("type") != "token_count":
                    continue
                tot = ((payload.get("info") or {}).get("total_token_usage")) or {}
                if not tot:
                    continue
                cur = {
                    "input": int(tot.get("input_tokens") or 0),
                    "cached": int(tot.get("cached_input_tokens") or 0),
                    "output": int(tot.get("output_tokens") or 0),
                    "total": int(tot.get("total_tokens") or 0),
                }
                if cur["total"] < prev["total"]:   # contador reiniciou
                    prev = {k: 0 for k in prev}
                delta = {k: max(0, cur[k] - prev[k]) for k in cur}
                prev = cur
                if not delta["total"]:
                    continue
                day = _local_day(ev.get("timestamp"))
                if not day:
                    continue
                d = per_day.setdefault(day.isoformat(), {k: 0 for k in cur})
                for k, v in delta.items():
                    d[k] += v
    except OSError:
        pass
    return per_day


def codex_days(days: int) -> dict[str, dict]:
    per_day: dict[str, dict] = {}
    for f in _recent(CODEX_DIR / "sessions", "rollout-*.jsonl", days):
        part = _cached(f, _parse_codex_file) or {}
        for day, u in part.items():
            d = per_day.setdefault(day, {"input": 0, "cached": 0, "output": 0, "total": 0})
            for k, v in u.items():
                d[k] += v
    return per_day


# ---------- Resumo ----------

def summary(days: int = HISTORY_DAYS) -> dict:
    with _lock:
        c = claude_days(days)
        x = codex_days(days)
    today = date.today()
    series = []
    for i in range(days - 1, -1, -1):
        day = (today - timedelta(days=i)).isoformat()
        series.append({
            "date": day,
            "claude": c.get(day, _empty_claude()),
            "codex": x.get(day, {"input": 0, "cached": 0, "output": 0, "total": 0}),
        })
    return {"days": series, "today": series[-1]["date"]}
