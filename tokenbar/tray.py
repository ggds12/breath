"""Ícone na área de notificação do Windows (os "ícones ocultos" da barra de tarefas).

- Clique esquerdo: abre/fecha uma janelinha com os limites, junto do relógio.
- Clique direito: menu com Abrir, Painel completo, Atualizar e Sair.
- A dica do ícone mostra o uso atual (ex.: "Claude 22% · Codex 100%").
- Avisa com uma notificação quando uma janela passa de 80% ou chega a 100%.

Usa só ctypes (API Win32), sem dependências externas.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import threading
import webbrowser
from ctypes import wintypes
from pathlib import Path

from .config import PORT, WEB_DIR

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WM_DESTROY, WM_CLOSE, WM_COMMAND, WM_TIMER = 0x0002, 0x0010, 0x0111, 0x0113
WM_USER = 0x0400
WM_TRAY = WM_USER + 1
WM_APP_REFRESHED = WM_USER + 2
WM_LBUTTONDOWN, WM_LBUTTONUP, WM_RBUTTONUP = 0x0201, 0x0202, 0x0205
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_INFO, NIIF_WARNING = 0x1, 0x2
IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x10, 0x40
MF_STRING, MF_SEPARATOR = 0x0, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
SPI_GETWORKAREA = 0x30
CREATE_NO_WINDOW = 0x08000000
ASFW_ANY = wintypes.DWORD(0xFFFFFFFF)

CMD_OPEN, CMD_FULL, CMD_REFRESH, CMD_QUIT = 1, 2, 3, 9
POPUP_W, POPUP_H = 400, 680


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON),
    ]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON),
    ]


# Tipos explícitos: evitam truncar ponteiros em Python 64 bits.
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.LoadImageW.restype = wintypes.HANDLE
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.LPVOID]
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, wintypes.LPVOID]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [ENUMPROC, wintypes.LPARAM]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.LPVOID, wintypes.UINT]
user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
user32.RegisterWindowMessageW.restype = wintypes.UINT
user32.MessageBoxW.argtypes =[wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def message_box(text: str, title: str = "TokenBar") -> None:
    user32.MessageBoxW(None, text, title, 0x40)


def _edge_path() -> str | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            p = Path(base, "Microsoft", "Edge", "Application", "msedge.exe")
            if p.is_file():
                return str(p)
    return None


def summarize(providers: list[dict]) -> str:
    parts = []
    for p in providers:
        s = next((w for w in p.get("windows", []) if w["id"] == "session"), None)
        wk = next((w for w in p.get("windows", []) if w["id"] == "weekly"), None)
        if s and s.get("used_percent") is not None:
            txt = f"{p['name']} {round(s['used_percent'])}%"
            if wk and wk.get("used_percent") is not None:
                txt += f" (sem. {round(wk['used_percent'])}%)"
            parts.append(txt)
        else:
            parts.append(f"{p['name']} —")
    return "TokenBar · " + " · ".join(parts)


class Tray:
    def __init__(self, get_limits, on_quit):
        self.get_limits = get_limits          # função(force: bool) -> list[dict]
        self.on_quit = on_quit
        self.popup: subprocess.Popen | None = None
        self.tip = "TokenBar"
        self.alerted: dict[str, int] = {}      # chave da janela -> último nível avisado (80/100)
        self.pending_balloon: tuple[str, str, int] | None = None
        self.lock = threading.Lock()
        self._wndproc = WNDPROC(self._proc)   # manter referência viva
        self.hinst = kernel32.GetModuleHandleW(None)
        self.taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        ico = WEB_DIR / "assets" / "tokenbar.ico"
        self.hicon = user32.LoadImageW(None, str(ico), IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)

        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = self.hinst
        wc.lpszClassName = "TokenBarTrayWindow"
        user32.RegisterClassExW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "TokenBar", 0,
                                           0, 0, 0, 0, None, None, self.hinst, None)

    # ----- ícone -----
    def _nid(self, flags: int) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = flags
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self.hicon
        nid.szTip = self.tip[:127]
        return nid

    def _add_icon(self):
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._nid(NIF_MESSAGE | NIF_ICON | NIF_TIP)))

    def _balloon(self, title: str, text: str, warn: bool):
        nid = self._nid(NIF_INFO)
        nid.szInfoTitle = title[:63]
        nid.szInfo = text[:255]
        nid.dwInfoFlags = NIIF_WARNING if warn else NIIF_INFO
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    # ----- dados (em thread separada para não travar o ícone) -----
    def refresh_async(self, force: bool = False):
        threading.Thread(target=self._refresh, args=(force,), daemon=True).start()

    def _refresh(self, force: bool):
        try:
            providers = self.get_limits(force)
        except Exception:
            return
        with self.lock:
            self.tip = summarize(providers)
            self.pending_balloon = self._check_alerts(providers)
        user32.PostMessageW(self.hwnd, WM_APP_REFRESHED, 0, 0)

    def _check_alerts(self, providers):
        msg = None
        for p in providers:
            for w in p.get("windows", []):
                pct = w.get("used_percent")
                if pct is None:
                    continue
                key = f"{p['id']}:{w['id']}"
                lvl = 100 if pct >= 100 else 80 if pct >= 80 else 0
                prev = self.alerted.get(key)
                self.alerted[key] = lvl
                if prev is None or lvl <= prev:   # 1ª leitura não avisa; só avisa ao subir
                    continue
                if lvl == 100:
                    msg = (f"{p['name']}: limite atingido", f"{w['label']} chegou a 100%.", 1)
                elif msg is None:
                    msg = (f"{p['name']}: {round(pct)}%", f"{w['label']} passou de 80%.", 1)
        return msg

    # ----- janela suspensa -----
    @staticmethod
    def _find_popup() -> int | None:
        """Janela de app do Edge com o painel (título termina em 'TokenBar' ou 'TokenBar · GGDS').

        Janelas normais do Edge têm o sufixo do navegador no título, então não são confundidas.
        """
        found: list[int] = []

        @ENUMPROC
        def cb(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls, 64)
            if cls.value != "Chrome_WidgetWin_1":
                return True
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value.endswith("— TokenBar") or buf.value == "TokenBar · GGDS":
                found.append(hwnd)
                return False
            return True

        user32.EnumWindows(cb, 0)
        return found[0] if found else None

    def on_mouse_down(self):
        # Ao clicar no ícone a janelinha perde o foco e se fecha sozinha ~250 ms depois.
        # Por isso decidimos no "mouse down", quando ela ainda existe.
        self.was_open = self._find_popup() is not None

    def toggle_popup(self):
        hwnd = self._find_popup()
        if getattr(self, "was_open", False) or hwnd:
            if hwnd:
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        else:
            self._open_popup()
        self.was_open = False

    def _open_popup(self):
        url = f"http://127.0.0.1:{PORT}/?mini=1"
        edge = _edge_path()
        if not edge:
            webbrowser.open(url)
            return
        rect = wintypes.RECT()
        user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
        x = max(0, rect.right - POPUP_W - 12)
        y = max(0, rect.bottom - POPUP_H - 12)
        profile = Path(os.environ.get("LOCALAPPDATA", Path.home()), "TokenBar", "janela")
        profile.mkdir(parents=True, exist_ok=True)
        # Deixa o Edge vir para a frente com foco (necessário para "clicou fora, fecha").
        user32.AllowSetForegroundWindow(ASFW_ANY)
        self.popup = subprocess.Popen([
            edge, f"--app={url}", f"--user-data-dir={profile}",
            f"--window-size={POPUP_W},{POPUP_H}", f"--window-position={x},{y}",
            "--no-first-run", "--no-default-browser-check", "--disable-sync",
            "--disable-extensions", "--disable-features=Translate,msEdgeSidebarV2",
        ], creationflags=CREATE_NO_WINDOW)

    def _close_popup(self):
        hwnd = self._find_popup()
        if hwnd:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)

    # ----- menu -----
    def _menu(self):
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING, CMD_OPEN, "Abrir")
        user32.AppendMenuW(menu, MF_STRING, CMD_FULL, "Painel completo no navegador")
        user32.AppendMenuW(menu, MF_STRING, CMD_REFRESH, "Atualizar agora")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, CMD_QUIT, "Sair do TokenBar")
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)
        cmd = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                                    pt.x, pt.y, 0, self.hwnd, None)
        user32.DestroyMenu(menu)
        if cmd == CMD_OPEN:
            hwnd = self._find_popup()
            if hwnd:
                user32.SetForegroundWindow(hwnd)
            else:
                self._open_popup()
        elif cmd == CMD_FULL:
            webbrowser.open(f"http://127.0.0.1:{PORT}/")
        elif cmd == CMD_REFRESH:
            self.refresh_async(force=True)
        elif cmd == CMD_QUIT:
            user32.DestroyWindow(self.hwnd)

    # ----- laço de mensagens -----
    def _proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            if lparam == WM_LBUTTONDOWN:
                self.on_mouse_down()
            elif lparam == WM_LBUTTONUP:
                self.toggle_popup()
            elif lparam == WM_RBUTTONUP:
                self._menu()
            return 0
        if msg == WM_TIMER:
            self.refresh_async()
            return 0
        if msg == WM_APP_REFRESHED:
            with self.lock:
                shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid(NIF_TIP)))
                pending, self.pending_balloon = self.pending_balloon, None
            if pending:
                self._balloon(pending[0], pending[1], bool(pending[2]))
            return 0
        if msg == self.taskbar_created:      # Explorer reiniciou: recoloca o ícone
            self._add_icon()
            return 0
        if msg == WM_DESTROY:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid(0)))
            self._close_popup()
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def run(self, show: bool = False):
        self._add_icon()
        user32.SetTimer(self.hwnd, 1, 60_000, None)
        self.refresh_async()
        if show:
            self._open_popup()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        self.on_quit()
