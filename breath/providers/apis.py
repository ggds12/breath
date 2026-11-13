"""Conectores por chave de API: DeepSeek, OpenRouter, Kimi (Moonshot) e "Outra IA" (personalizado).

Cada conector lê só números de uso/saldo, com a chave do próprio serviço:
- DeepSeek:   GET https://api.deepseek.com/user/balance               (saldo)
- OpenRouter: GET https://openrouter.ai/api/v1/key                    (crédito usado / limite da chave)
- Kimi:       GET https://api.moonshot.ai/v1/users/me/balance         (saldo; .cn para contas da China)
- Outra IA:   GET <url informada>  + caminhos no JSON para usado/limite ou saldo

Saldo sem limite natural vira porcentagem só se o usuário informar um orçamento.
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from .. import net
from . import result, window

TYPES = {
    # tipo: (nome padrão, hosts usados)
    "deepseek": ("DeepSeek", ("api.deepseek.com",)),
    "openrouter": ("OpenRouter", ("openrouter.ai",)),
    "kimi": ("Kimi", ("api.moonshot.ai", "api.moonshot.cn")),
    "custom": ("Outra IA", ()),
}

SYMBOLS = {"USD": "US$", "CNY": "¥", "BRL": "R$", "EUR": "€"}


def money(value: float, currency: str | None) -> str:
    cur = (currency or "").upper()
    txt = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    sym = SYMBOLS.get(cur)
    return f"{sym} {txt}" if sym else (f"{txt} {cur}".strip())


def get_path(data, path: str):
    """'balance_infos.0.total_balance' -> valor. Devolve None se não existir."""
    cur = data
    for part in [p for p in (path or "").split(".") if p]:
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def balance_window(balance: float | None, currency: str | None, budget: float | None) -> dict:
    """Saldo: com orçamento vira barra (quanto do orçamento já foi gasto); sem orçamento, só o valor."""
    used = None
    if balance is not None and budget and budget > 0:
        used = max(0.0, min(100.0, (1 - balance / budget) * 100))
    w = window("balance", "Saldo", used, None, None)
    w["detail"] = money(balance, currency) if balance is not None else "—"
    if used is None:
        w["hint"] = "sem orçamento"
    return w


def _parse(cfg: dict, data: dict) -> tuple[list[dict], str | None]:
    tipo = cfg.get("tipo")
    budget = _num(cfg.get("orcamento"))
    if tipo == "deepseek":
        infos = data.get("balance_infos") or []
        info = next((i for i in infos if i.get("currency") == "USD"), infos[0] if infos else {})
        w = balance_window(_num(info.get("total_balance")), info.get("currency"), budget)
        msg = None if data.get("is_available", True) else "Saldo insuficiente para novas chamadas."
        return [w], msg
    if tipo == "kimi":
        d = data.get("data") or {}
        return [balance_window(_num(d.get("available_balance")), cfg.get("moeda") or "USD", budget)], None
    if tipo == "openrouter":
        d = data.get("data") or {}
        limit, remaining, usage = _num(d.get("limit")), _num(d.get("limit_remaining")), _num(d.get("usage"))
        if limit and remaining is not None:
            used = (limit - remaining) / limit * 100
            reset = d.get("limit_reset")
            label = {"daily": "Crédito · dia", "weekly": "Crédito · semana", "monthly": "Crédito · mês"}.get(reset, "Crédito")
            w = window("credit", label, used, None, None)
            w["detail"] = f"{money(limit - remaining, 'USD')} de {money(limit, 'USD')}"
            return [w], None
        w = window("credit", "Crédito usado", None, None, None)
        w["detail"] = money(usage or 0, "USD")
        if budget:
            w["used_percent"] = max(0.0, min(100.0, (usage or 0) / budget * 100))
        else:
            w["hint"] = "chave sem limite"
        return [w], None
    if tipo == "custom":
        used_v, limit_v = _num(get_path(data, cfg.get("campo_usado", ""))), _num(get_path(data, cfg.get("campo_limite", "")))
        if used_v is not None and limit_v:
            w = window("custom", cfg.get("rotulo") or "Uso", used_v / limit_v * 100, None, None)
            w["detail"] = f"{used_v:g} de {limit_v:g}"
            return [w], None
        saldo = _num(get_path(data, cfg.get("campo_saldo", "")))
        if saldo is not None:
            return [balance_window(saldo, cfg.get("moeda"), budget)], None
        return [], "Não encontrei os campos informados na resposta."
    return [], "Tipo de conta desconhecido."


def endpoint(cfg: dict) -> tuple[str, list[str]]:
    tipo = cfg.get("tipo")
    if tipo == "deepseek":
        return "https://api.deepseek.com/user/balance", ["api.deepseek.com"]
    if tipo == "openrouter":
        return "https://openrouter.ai/api/v1/key", ["openrouter.ai"]
    if tipo == "kimi":
        host = "api.moonshot.cn" if cfg.get("regiao") == "cn" else "api.moonshot.ai"
        return f"https://{host}/v1/users/me/balance", [host]
    url = cfg.get("url") or ""
    host = urlsplit(url).hostname or ""
    return url, [host] if host else []


def collect(cfg: dict, key: str | None) -> dict:
    tipo = cfg.get("tipo", "custom")
    name = TYPES.get(tipo, ("IA", ()))[0]
    if not key:
        return result(tipo, name, status="missing", message="Chave de API não encontrada. Remova e adicione a conta de novo.")
    url, hosts = endpoint(cfg)
    if not url.startswith("https://") or not hosts:
        return result(tipo, name, status="error", message="Endereço inválido (precisa ser https).")
    header = (cfg.get("cabecalho") or "Authorization").strip()
    prefix = cfg.get("prefixo", "Bearer ") if tipo == "custom" else "Bearer "
    try:
        data = net.get_json(url, {header: f"{prefix}{key}"}, extra_hosts=hosts)
    except net.HttpError as exc:
        if exc.status in (401, 403):
            return result(tipo, name, status="expired", message="A chave foi recusada. Confira ou gere outra.")
        return result(tipo, name, status="error", message=f"Falha na consulta ({exc}).")
    except (ValueError, json.JSONDecodeError):
        return result(tipo, name, status="error", message="Resposta inesperada.")
    wins, msg = _parse(cfg, data)
    status = "ok" if wins else "error"
    return result(tipo, name, status=status, windows=wins, source="api", message=msg)
