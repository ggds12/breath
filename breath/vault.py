"""Chaves de API das contas adicionadas pelo usuário.

No Windows ficam no Gerenciador de Credenciais (protegidas pelo sistema, por usuário).
Em outros sistemas, num arquivo só do usuário (permissão 600) na pasta de dados do Breath.
As chaves nunca vão para o navegador, para o log nem para o contas.json.
"""

from __future__ import annotations

import json
import os
import sys

from .config import DATA_DIR

PREFIX = "Breath:"

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _FILETIME(ctypes.Structure):
        _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]

    class _CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR), ("LastWritten", _FILETIME), ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD), ("Attributes", wintypes.LPVOID),
            ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR),
        ]

    _adv = ctypes.WinDLL("advapi32", use_last_error=True)
    _adv.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
    _adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               ctypes.POINTER(ctypes.POINTER(_CREDENTIALW))]
    _adv.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _adv.CredFree.argtypes = [wintypes.LPVOID]
    _GENERIC, _PERSIST_LOCAL = 1, 2

    def set_secret(account_id: str, value: str) -> bool:
        blob = value.encode("utf-16-le")
        buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        cred = _CREDENTIALW()
        cred.Type = _GENERIC
        cred.TargetName = PREFIX + account_id
        cred.Comment = "Chave de API usada pelo Breath (só leitura de uso/saldo)"
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = buf
        cred.Persist = _PERSIST_LOCAL
        cred.UserName = "breath"
        return bool(_adv.CredWriteW(ctypes.byref(cred), 0))

    def get_secret(account_id: str) -> str | None:
        p = ctypes.POINTER(_CREDENTIALW)()
        if not _adv.CredReadW(PREFIX + account_id, _GENERIC, 0, ctypes.byref(p)):
            return None
        try:
            c = p.contents
            raw = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize)
            return raw.decode("utf-16-le")
        finally:
            _adv.CredFree(p)

    def delete_secret(account_id: str) -> None:
        _adv.CredDeleteW(PREFIX + account_id, _GENERIC, 0)

else:
    _FILE = DATA_DIR / "segredos.json"

    def _load() -> dict:
        try:
            return json.loads(_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(data: dict) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        fd = os.open(_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def set_secret(account_id: str, value: str) -> bool:
        data = _load()
        data[account_id] = value
        _save(data)
        return True

    def get_secret(account_id: str) -> str | None:
        return _load().get(account_id)

    def delete_secret(account_id: str) -> None:
        data = _load()
        if data.pop(account_id, None) is not None:
            _save(data)
