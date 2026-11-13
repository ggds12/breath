"""Coletores de limites. Cada um devolve um dicionário normalizado, sem segredos."""

from __future__ import annotations

from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def window(wid: str, label: str, used: float | None, resets_at: str | None,
           seconds: int | None) -> dict:
    pct = None if used is None else max(0.0, min(100.0, float(used)))
    return {
        "id": wid,
        "label": label,
        "used_percent": pct,
        "resets_at": resets_at,
        "window_seconds": seconds,
    }


def epoch_to_iso(value) -> str | None:
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        return None


def result(pid: str, name: str, *, status: str, message: str | None = None,
           plan: str | None = None, windows: list | None = None,
           source: str | None = None, as_of: str | None = None) -> dict:
    return {
        "id": pid,
        "name": name,
        "status": status,          # ok | stale | expired | missing | error
        "message": message,
        "plan": plan,
        "windows": windows or [],
        "source": source,          # api | logs
        "as_of": as_of or now_iso(),
    }
