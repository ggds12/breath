"""Contas do Claude e do Codex a acompanhar.

O Claude Code e o Codex guardam cada login numa pasta: por padrão `~/.claude` e `~/.codex`.
Quem tem mais de uma conta costuma usar outras pastas (`CLAUDE_CONFIG_DIR` / `CODEX_HOME`),
por exemplo `~/.claude-trabalho`. O Breath encontra essas pastas sozinho:

- a pasta padrão e a das variáveis de ambiente (sempre aparecem, mesmo sem login);
- qualquer `~/.claude*` com `.credentials.json` e qualquer `~/.codex*` com `auth.json`.

Para dar nomes ou apontar pastas em outro lugar, crie `%LOCALAPPDATA%\\Breath\\contas.json`:

    {
      "claude": [{"nome": "Pessoal", "pasta": "~/.claude"},
                 {"nome": "Trabalho", "pasta": "D:/logins/claude-trabalho"}],
      "codex":  [{"nome": "Pessoal", "pasta": "~/.codex"}]
    }

Se o arquivo listar um provedor, só as contas listadas dele são usadas.
O arquivo é só lido; nenhuma credencial é copiada para fora das pastas originais.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import ACCOUNTS_FILE, HOME

MAX_PER_PROVIDER = 10

PROVIDERS = (
    # id, rótulo, pasta padrão, variável de ambiente, arquivo que indica um login
    ("claude", "Claude", ".claude", "CLAUDE_CONFIG_DIR", ".credentials.json"),
    ("codex", "Codex", ".codex", "CODEX_HOME", "auth.json"),
)


@dataclass(frozen=True)
class Account:
    provider: str      # "claude" | "codex"
    id: str            # único: "claude", "claude:trabalho"…
    name: str          # exibido: "Claude", "Claude · Trabalho"
    path: Path | None = None
    kind: str = "pasta"                     # "pasta" (login local) | "api" (chave de API)
    cfg: dict = field(default_factory=dict, compare=False, hash=False)


def _suffix_from_dir(provider: str, path: Path) -> str:
    """'.claude-trabalho' -> 'trabalho'; '.claude' -> ''; 'claude_pessoal' -> 'pessoal'."""
    name = path.name.lstrip(".")
    low = name.lower()
    if low.startswith(provider):
        name = name[len(provider):]
    return name.strip(" -_.")


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:32] or "conta"


def _load_file() -> dict:
    try:
        data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _same(a: Path, b: Path) -> bool:
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except OSError:
        return False


def discover() -> list[Account]:
    cfg = _load_file()
    hidden = set(x for x in cfg.get("ocultas", []) if isinstance(x, str))
    accounts: list[Account] = []
    for pid, label, default_dir, env, marker in PROVIDERS:
        entries: list[tuple[Path, str | None]] = []
        listed = cfg.get(pid)
        if isinstance(listed, list) and listed:
            for item in listed[:MAX_PER_PROVIDER]:
                if isinstance(item, dict) and isinstance(item.get("pasta"), str):
                    nome = item.get("nome") if isinstance(item.get("nome"), str) else None
                    entries.append((Path(os.path.expanduser(item["pasta"])), nome))
        else:
            env_dir = os.environ.get(env)
            base = [Path(env_dir)] if env_dir else []
            base.append(HOME / default_dir)
            for p in base:
                entries.append((p, None))
            try:
                extra = sorted(p for p in HOME.glob(f".{pid}*")
                               if p.is_dir() and (p / marker).is_file())
            except OSError:
                extra = []
            for p in extra:
                entries.append((p, None))

        seen: list[Path] = []
        used_ids: set[str] = set()
        for path, nome in entries:
            if any(_same(path, s) for s in seen):
                continue
            seen.append(path)
            suffix = (nome or _suffix_from_dir(pid, path)).strip()
            first_plain = not suffix and pid not in used_ids
            if first_plain:
                aid, name = pid, label
            else:
                suffix = suffix or path.name
                aid = f"{pid}:{_slug(suffix)}"
                n = 2
                while aid in used_ids:
                    aid = f"{pid}:{_slug(suffix)}-{n}"
                    n += 1
                name = f"{label} · {suffix[:1].upper()}{suffix[1:]}"
            used_ids.add(aid)
            if aid in hidden:
                continue
            accounts.append(Account(pid, aid, name, path))
            if len([a for a in accounts if a.provider == pid]) >= MAX_PER_PROVIDER:
                break
    # contas por chave de API (DeepSeek, OpenRouter, Kimi, "Outra IA")
    from .providers.apis import TYPES
    for item in (cfg.get("apis") or [])[:20]:
        if not (isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("tipo") in TYPES):
            continue
        nome = item.get("nome") if isinstance(item.get("nome"), str) else TYPES[item["tipo"]][0]
        accounts.append(Account(item["tipo"], item["id"], nome[:40], None, "api", dict(item)))
    return accounts


# ---------------------------------------------------------------- edição do contas.json
API_FIELDS = {"nome", "tipo", "orcamento", "moeda", "regiao", "url", "cabecalho", "prefixo",
              "campo_usado", "campo_limite", "campo_saldo", "rotulo"}


def _save_file(data: dict) -> None:
    ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ACCOUNTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ACCOUNTS_FILE)


def _clean_str(v, limit=300) -> str | None:
    return v.strip()[:limit] if isinstance(v, str) and v.strip() else None


def add_folder(provider: str, nome: str | None, pasta: str) -> str:
    """Acrescenta uma conta por pasta de login (Claude/Codex). Mantém as que já aparecem."""
    if provider not in ("claude", "codex"):
        raise ValueError("provedor inválido")
    pasta = _clean_str(pasta, 500)
    if not pasta:
        raise ValueError("informe a pasta do login")
    data = _load_file()
    lst = data.get(provider)
    if not isinstance(lst, list) or not lst:
        # o arquivo passa a listar este provedor: preserva as contas que já eram encontradas
        lst = [{"nome": (a.name.split(" · ", 1)[1] if " · " in a.name else "Principal"), "pasta": str(a.path)}
               for a in discover() if a.provider == provider and a.kind == "pasta"]
    lst.append({"nome": _clean_str(nome, 40) or Path(pasta).name, "pasta": pasta})
    data[provider] = lst[:MAX_PER_PROVIDER]
    data["ocultas"] = [x for x in data.get("ocultas", []) if not str(x).startswith(provider)]
    _save_file(data)
    return provider


def add_api(fields: dict) -> str:
    """Acrescenta uma conta por chave de API; devolve o id (a chave é guardada à parte, no cofre)."""
    from .providers.apis import TYPES
    tipo = fields.get("tipo")
    if tipo not in TYPES:
        raise ValueError("tipo inválido")
    item = {}
    for k in API_FIELDS:
        v = fields.get(k)
        if k == "orcamento":
            try:
                v = float(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                raise ValueError("orçamento inválido") from None
            if v is not None and not (0 < v < 1e7):
                raise ValueError("orçamento inválido")
        else:
            v = _clean_str(v, 500 if k == "url" else 80)
        if v is not None:
            item[k] = v
    item["tipo"] = tipo
    if tipo == "custom":
        url = item.get("url", "")
        if not url.startswith("https://"):
            raise ValueError("a URL precisa começar com https://")
        if not (item.get("campo_saldo") or (item.get("campo_usado") and item.get("campo_limite"))):
            raise ValueError("informe o campo de saldo ou os campos de usado e limite")
    data = _load_file()
    apis = [a for a in data.get("apis", []) if isinstance(a, dict)]
    base = f"{tipo}:{_slug(item.get('nome') or TYPES[tipo][0])}"
    aid, n = base, 2
    taken = {a.get("id") for a in apis}
    while aid in taken:
        aid, n = f"{base}-{n}", n + 1
    item = {"id": aid, **item}
    apis.append(item)
    data["apis"] = apis[:20]
    _save_file(data)
    return aid


def remove(account_id: str) -> bool:
    """Remove uma conta: as por API saem do arquivo; as por pasta deixam de ser mostradas."""
    data = _load_file()
    apis = [a for a in data.get("apis", []) if isinstance(a, dict)]
    if any(a.get("id") == account_id for a in apis):
        data["apis"] = [a for a in apis if a.get("id") != account_id]
        _save_file(data)
        return True
    provider = account_id.split(":")[0]
    if provider in ("claude", "codex"):
        # conta de pasta listada no arquivo (ex.: adicionada pelo botão +): sai da lista
        match = next((a for a in discover() if a.id == account_id and a.kind == "pasta"), None)
        lst = data.get(provider)
        if match and isinstance(lst, list) and lst:
            keep = [e for e in lst if not (isinstance(e, dict) and isinstance(e.get("pasta"), str)
                                          and _same(Path(os.path.expanduser(e["pasta"])), match.path))]
            if len(keep) < len(lst):
                default = HOME / f".{provider}"
                only_default = (len(keep) == 1 and isinstance(keep[0], dict)
                                and _same(Path(os.path.expanduser(str(keep[0].get("pasta", "")))), default))
                if keep and not only_default:
                    data[provider] = keep
                else:
                    data.pop(provider, None)
                _save_file(data)
                return True
        # encontrada automaticamente: deixa de ser mostrada
        hidden = set(x for x in data.get("ocultas", []) if isinstance(x, str))
        hidden.add(account_id)
        data["ocultas"] = sorted(hidden)
        _save_file(data)
        return True
    return False
