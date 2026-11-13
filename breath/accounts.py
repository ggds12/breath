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
from dataclasses import dataclass
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
    path: Path


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
            accounts.append(Account(pid, aid, name, path))
            if len([a for a in accounts if a.provider == pid]) >= MAX_PER_PROVIDER:
                break
    return accounts
