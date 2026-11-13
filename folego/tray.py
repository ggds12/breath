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
import time
import webbrowser
from ctypes import wintypes
from pathlib import Path

from .config import PORT, WEB_DIR

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
shcore = ctypes.WinDLL("shcore", use_last_error=True)

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

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_POPUP, WS_CHILD, WS_CLIPCHILDREN, WS_CAPTION = 0x80000000, 0x40000000, 0x02000000, 0x00C00000
WM_ACTIVATE, WA_INACTIVE = 0x0006, 0
WM_APP_SHOWHOST, WM_APP_HIDEHOST = 0x0400 + 3, 0x0400 + 4
EVENT_OBJECT_CREATE, EVENT_OBJECT_SHOW, WINEVENT_OUTOFCONTEXT = 0x8000, 0x8002, 0
BLACK_BRUSH = 4
SWP_SHOWWINDOW = 0x0040
TIMER_PRELOAD = 2
WS_EX_TOOLWINDOW, WS_EX_APPWINDOW, WS_EX_TOPMOST = 0x00000080, 0x00040000, 0x00000008
# barra de título, borda redimensionável, menu do sistema, minimizar/maximizar
FRAME_STYLES = 0x00C00000 | 0x00040000 | 0x00080000 | 0x00020000 | 0x00010000
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER = 0x0001, 0x0002, 0x0004
SW_HIDE, SW_SHOW = 0, 5
HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x0010, 0x0020
MONITOR_DEFAULTTOPRIMARY, MONITOR_DEFAULTTONEAREST = 1, 2

CMD_OPEN, CMD_FULL, CMD_REFRESH, CMD_QUIT = 1, 2, 3, 9
# Tamanho da área da página, em DIPs (o mesmo que o CSS usa).
POPUP_W, POPUP_H = 340, 462
# O Edge desenha 1 px da barra de título sobre o topo da página: essa faixa fica fora do recorte.
TOP_GUARD = 4   # 4 px dá pixel inteiro em 100/125/150/175% (o CSS usa o mesmo valor)
RIGHT_INSET = 1  # px CSS: o contorno fica 1 px para dentro à direita (o CSS usa o mesmo valor)
BOTTOM_INSET = 1  # idem embaixo: o Edge às vezes não pinta a última linha da página


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
class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
WINEVENTPROC = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND, wintypes.LONG,
                                  wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
user32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, WINEVENTPROC,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
user32.SetWinEventHook.restype = wintypes.HANDLE
user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
user32.SetParent.restype = wintypes.HWND
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.SetFocus.argtypes = [wintypes.HWND]
user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
gdi32.GetStockObject.argtypes = [ctypes.c_int]
gdi32.GetStockObject.restype = wintypes.HANDLE
user32.EnumWindows.argtypes = [ENUMPROC, wintypes.LPARAM]
user32.EnumChildWindows.argtypes = [wintypes.HWND, ENUMPROC, wintypes.LPARAM]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
user32.GetWindowRgnBox.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HANDLE
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
gdi32.CreateRoundRectRgn.restype = wintypes.HANDLE
shcore.GetDpiForMonitor.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                    ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT)]
user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_ssize_t]
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


ole32 = ctypes.WinDLL("ole32")
HRESULT = ctypes.c_long
ole32.CoInitialize.argtypes = [wintypes.LPVOID]
ole32.CLSIDFromString.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(GUID)]
ole32.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), wintypes.LPVOID, wintypes.DWORD,
                                   ctypes.POINTER(GUID), ctypes.POINTER(wintypes.LPVOID)]


dwmapi = ctypes.WinDLL("dwmapi")
dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD]


def _host_dwm(hwnd) -> None:
    """Cantos arredondados (com suavização) do Windows 11 e sem borda do sistema."""
    for attr, value in (
        (33, 2),           # DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND
        (34, 0xFFFFFFFE),  # DWMWA_BORDER_COLOR = DWMWA_COLOR_NONE (o contorno é do CSS)
    ):
        v = wintypes.DWORD(value)
        dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), 4)


class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", wintypes.LPWSTR)]


ntdll = ctypes.WinDLL("ntdll")
ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.ULONG,
                                            ctypes.POINTER(wintypes.ULONG)]
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def _cmdline(pid: int) -> str:
    """Linha de comando de um processo (só leitura), para reconhecer o Edge do Fôlego pelo perfil."""
    h = kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        size = wintypes.ULONG(0)
        buf = ctypes.create_string_buffer(8192)
        if ntdll.NtQueryInformationProcess(h, 60, buf, len(buf), ctypes.byref(size)) != 0:
            return ""
        us = _UNICODE_STRING.from_buffer(buf)
        return ctypes.wstring_at(us.Buffer, us.Length // 2) if us.Buffer else ""
    finally:
        kernel32.CloseHandle(h)


def _taskbar_delete_tab(hwnd) -> None:
    """Remove o botão da janela na barra de tarefas (ITaskbarList::DeleteTab)."""
    ole32.CoInitialize(None)
    clsid, iid, ptr = GUID(), GUID(), wintypes.LPVOID()
    ole32.CLSIDFromString("{56FDF344-FD6D-11d0-958A-006097C9A090}", ctypes.byref(clsid))
    ole32.CLSIDFromString("{56FDF342-FD6D-11d0-958A-006097C9A090}", ctypes.byref(iid))
    if ole32.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(ptr)) or not ptr:
        return
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    release = ctypes.WINFUNCTYPE(wintypes.ULONG, wintypes.LPVOID)(vtbl[2])
    hr_init = ctypes.WINFUNCTYPE(HRESULT, wintypes.LPVOID)(vtbl[3])
    delete_tab = ctypes.WINFUNCTYPE(HRESULT, wintypes.LPVOID, wintypes.HWND)(vtbl[5])
    if hr_init(ptr) == 0:
        delete_tab(ptr, hwnd)
    release(ptr)


def message_box(text: str, title: str = "Fôlego") -> None:
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
    return "Fôlego · " + " · ".join(parts)


class Tray:
    def __init__(self, get_limits, on_quit, control=None):
        self.get_limits = get_limits          # função(force: bool) -> list[dict]
        self.on_quit = on_quit
        self.control = control                # pedidos da página: fixar, fechar
        self.edge: int | None = None          # janela do Edge embutida na hospedeira
        self.awaiting_until = 0.0
        self.child: int | None = None
        self.show_when_ready = False
        self.rejected: set[int] = set()       # janelas de outros Edge já verificadas
        self.last_autoclose = 0.0
        self.geom = (1.0, 0, 0, POPUP_W, POPUP_H)
        self.profile = Path(os.environ.get("LOCALAPPDATA", Path.home()), "Folego", "janela")
        self.tip = "Fôlego"
        self.alerted: dict[str, int] = {}      # chave da janela -> último nível avisado (80/100)
        self.pending_balloon: tuple[str, str, int] | None = None
        self.lock = threading.Lock()
        # Coordenadas reais de tela (sem a "virtualização" de DPI do Windows).
        try:
            user32.SetProcessDpiAwarenessContext(-4)   # PER_MONITOR_AWARE_V2
        except (OSError, AttributeError):
            pass
        # Moldura do Edge (barra de título e bordas) em pixels; é remedida a cada abertura.
        self.frame = (8, 36, 7, 8)
        self.at_cursor = True
        self._wndproc = WNDPROC(self._proc)   # manter referência viva
        self.hinst = kernel32.GetModuleHandleW(None)
        self.taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        ico = WEB_DIR / "assets" / "folego.ico"
        self.hicon = user32.LoadImageW(None, str(ico), IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)

        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = self.hinst
        wc.lpszClassName = "FolegoTrayWindow"
        user32.RegisterClassExW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "Fôlego", 0,
                                           0, 0, 0, 0, None, None, self.hinst, None)

        # Hospedeira da janelinha (invisível até abrir).
        self._host_wndproc = WNDPROC(self._host_proc)
        hc = WNDCLASSEXW()
        hc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        hc.lpfnWndProc = self._host_wndproc
        hc.hInstance = self.hinst
        hc.hbrBackground = gdi32.GetStockObject(BLACK_BRUSH)
        hc.lpszClassName = "FolegoHost"
        user32.RegisterClassExW(ctypes.byref(hc))
        self.host = user32.CreateWindowExW(WS_EX_TOOLWINDOW | WS_EX_TOPMOST, hc.lpszClassName, "Fôlego",
                                           WS_POPUP | WS_CLIPCHILDREN, 0, 0, 10, 10,
                                           None, None, self.hinst, None)
        _host_dwm(self.host)

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
    # A janelinha é uma janela do próprio Fôlego (a "hospedeira"): sem moldura, fora da barra de
    # tarefas (estilo ferramenta) e com os cantos arredondados (suavizados) do Windows 11.
    # Dentro dela fica a janela de app do Edge, capturada no instante em que é criada — antes de
    # aparecer — e posicionada de modo que a barra de título do Edge fique fora da área visível.

    @staticmethod
    def _find_popup() -> int | None:
        """Janela solta do painel (de versões antigas ou de uma execução anterior)."""
        found: list[int] = []

        @ENUMPROC
        def cb(hwnd, _):
            if not user32.IsWindowVisible(hwnd) or user32.GetParent(hwnd):
                return True
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls, 64)
            if cls.value != "Chrome_WidgetWin_1":
                return True
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            t = buf.value
            if t.endswith(("— Fôlego", "— TokenBar")) or t in ("Fôlego · GGDS", "TokenBar · GGDS"):
                found.append(hwnd)
                return False
            return True

        user32.EnumWindows(cb, 0)
        return found[0] if found else None

    def _popup_open(self) -> bool:
        return bool(self.host and user32.IsWindowVisible(self.host))

    def on_mouse_down(self):
        # Clicar no ícone tira o foco da janelinha, que se fecha sozinha nesse instante.
        # Lembramos que ela estava aberta para o clique não reabri-la logo em seguida.
        self.was_open = self._popup_open() or (time.time() - self.last_autoclose < 0.6)

    def toggle_popup(self):
        if getattr(self, "was_open", False) or self._popup_open():
            self._close_popup()
        else:
            self._open_popup()
        self.was_open = False

    # Geometria em pixels físicos. O processo é "per-monitor DPI aware".
    def _target(self) -> tuple[float, int, int, int, int]:
        """Escala e retângulo visível (x, y, w, h) da janelinha, no canto do relógio."""
        # Num clique no ícone, o monitor é o do mouse (onde está a barra de tarefas clicada).
        # Abrindo sozinha (início do Windows), usa o monitor principal.
        pt = wintypes.POINT()
        if self.at_cursor:
            user32.GetCursorPos(ctypes.byref(pt))
        flag = MONITOR_DEFAULTTONEAREST if self.at_cursor else MONITOR_DEFAULTTOPRIMARY
        mon = user32.MonitorFromPoint(pt, flag)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(mon, ctypes.byref(info))
        dpi_x, dpi_y = wintypes.UINT(96), wintypes.UINT(96)
        try:
            shcore.GetDpiForMonitor(mon, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
        except OSError:
            pass
        s = dpi_x.value / 96
        w, h, m = round((POPUP_W - RIGHT_INSET) * s), round((POPUP_H - BOTTOM_INSET) * s), round(12 * s)
        work = info.rcWork
        return s, work.right - m - w, work.bottom - m - h, w, h

    def _open_popup(self, at_cursor: bool = True):
        """Mostra a janelinha. O Edge fica pronto (escondido) desde o início do Fôlego, então
        abrir é só exibir a hospedeira: instantâneo e sem nenhuma janela nova aparecendo."""
        self.at_cursor = at_cursor
        self.geom = self._target()
        s, x, y, w, h = self.geom
        user32.SetWindowPos(self.host, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE)
        _host_dwm(self.host)
        if self.control:
            self.control.reset()
        if self.edge and user32.IsWindow(self.edge):
            if self.child and user32.IsWindow(self.child):
                self._place_edge(self.edge, self.child)     # outro monitor/escala? reencaixa
            user32.PostMessageW(self.host, WM_APP_SHOWHOST, 0, 0)
        else:
            self._launch_edge(show=True)

    def _launch_edge(self, show: bool):
        """Abre a janela de app do Edge FORA DA TELA; o gancho a captura e embute na hospedeira."""
        url = f"http://127.0.0.1:{PORT}/?mini=1"
        edge = _edge_path()
        if not edge:
            if show:
                webbrowser.open(url)
            return
        if time.time() < self.awaiting_until:     # já está abrindo
            self.show_when_ready = self.show_when_ready or show
            return
        if not show:
            self.geom = self._target()
            s, x, y, w, h = self.geom
            user32.SetWindowPos(self.host, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE)
        self.show_when_ready = show
        self.profile.mkdir(parents=True, exist_ok=True)
        self.awaiting_until = time.time() + 15
        subprocess.Popen([
            edge, f"--app={url}", f"--user-data-dir={self.profile}",
            f"--window-size={POPUP_W + 20},{POPUP_H + 60}", "--window-position=-32000,-32000",
            "--no-first-run", "--no-default-browser-check", "--disable-sync",
            "--disable-extensions", "--disable-features=Translate,msEdgeSidebarV2",
        ], creationflags=CREATE_NO_WINDOW)

    def on_winevent(self, hwnd, event=0):
        """Gancho: uma janela foi criada/exibida em algum processo. É a nossa do Edge?

        A confirmação (linha de comando do processo) leva ~100 ms num Edge recém-aberto, tempo em
        que ele já mostraria a janela. Por isso, assim que a janela nasce, ela sai da barra de
        tarefas e vai para fora da tela (instantâneo); depois confirmamos e embutimos — ou, se for
        de outro Edge, devolvemos tudo como estava."""
        if self.edge or time.time() > self.awaiting_until or not hwnd or user32.GetParent(hwnd):
            return
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value != "Chrome_WidgetWin_1":
            return
        if not (user32.GetWindowLongPtrW(hwnd, GWL_STYLE) & WS_CAPTION):
            return   # menus, dicas e janelas auxiliares do Edge não têm barra de título
        if hwnd in self.rejected:
            return
        # 1) esconde já (sem botão na barra de tarefas e fora da tela)
        ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
        user32.SetWindowPos(hwnd, None, -32000, -32000, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
        # 2) confirma pelo perfil exclusivo do Fôlego na linha de comando do processo
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if str(self.profile).lower() not in _cmdline(pid.value).lower():
            # é de outro Edge (o seu navegador normal, por exemplo): devolve como estava
            self.rejected.add(hwnd)
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex)
            user32.SetWindowPos(hwnd, None, rect.left, rect.top, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
            return
        self.awaiting_until = 0
        # 3) vira janela filha da hospedeira: some da barra de tarefas e perde a moldura própria
        st = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        user32.SetWindowLongPtrW(hwnd, GWL_STYLE, (st & ~(WS_POPUP | FRAME_STYLES)) | WS_CHILD)
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex & ~(WS_EX_APPWINDOW | WS_EX_TOPMOST | WS_EX_TOOLWINDOW))
        user32.SetParent(hwnd, self.host)
        self.edge = hwnd
        threading.Thread(target=self._settle, args=(hwnd,), daemon=True).start()

    @staticmethod
    def _render_child(hwnd) -> int | None:
        found: list[int] = []

        @ENUMPROC
        def cb(child, _):
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(child, cls, 64)
            if cls.value == "Chrome_RenderWidgetHostHWND":
                found.append(child)
                return False
            return True

        user32.EnumChildWindows(hwnd, cb, 0)
        return found[0] if found else None

    def _place_edge(self, hwnd, child) -> None:
        """Encaixa a página no (0,0) da hospedeira; a barra de título do Edge fica acima, fora da vista.
        O topo da página tem uma faixa de TOP_GUARD px (o Edge desenha ali 1 px da barra dele)."""
        s = self.geom[0]
        win, page = wintypes.RECT(), wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(win))
        user32.GetWindowRect(child, ctypes.byref(page))
        frame = (page.left - win.left, page.top - win.top, win.right - page.right, win.bottom - page.bottom)
        if all(0 <= v < 200 for v in frame):
            self.frame = frame
        left, top, right, bottom = self.frame
        g = round(TOP_GUARD * s)
        pw, ph = round(POPUP_W * s), round((POPUP_H + TOP_GUARD) * s)
        user32.SetWindowPos(hwnd, None, -left, -(top + g), pw + left + right, ph + top + bottom,
                            SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW)

    def _settle(self, hwnd):
        """Espera a página existir, encaixa e vigia enquanto o Edge embutido existir."""
        deadline = time.time() + 15
        child = None
        while time.time() < deadline and user32.IsWindow(hwnd):
            child = self._render_child(hwnd)
            if child:
                break
            time.sleep(0.01)
        if child:
            self.child = child
            self._place_edge(hwnd, child)
            time.sleep(0.15)                      # deixa a página pintar
            self._place_edge(hwnd, child)         # a moldura pode mudar depois do 1º encaixe
            if self.show_when_ready:
                self.show_when_ready = False
                user32.PostMessageW(self.host, WM_APP_SHOWHOST, 0, 0)
            while user32.IsWindow(hwnd):
                if self.control and self.control.take_close():
                    user32.PostMessageW(self.host, WM_APP_HIDEHOST, 0, 0)
                if self.control and self.control.take_open_full():
                    user32.PostMessageW(self.host, WM_APP_HIDEHOST, 0, 0)
                    webbrowser.open(f"http://127.0.0.1:{PORT}/")
                if user32.IsWindowVisible(self.host) and user32.IsWindow(child):
                    g = round(TOP_GUARD * self.geom[0])
                    page, hr = wintypes.RECT(), wintypes.RECT()
                    user32.GetWindowRect(child, ctypes.byref(page))
                    user32.GetWindowRect(self.host, ctypes.byref(hr))
                    if (page.left, page.top + g) != (hr.left, hr.top):
                        self._place_edge(hwnd, child)   # o Edge mexeu em si mesmo: reencaixa
                time.sleep(0.1)
        # O Edge fechou (ou caiu): esconde a hospedeira; a próxima abertura recria.
        if self.edge == hwnd:
            self.edge = self.child = None
            user32.PostMessageW(self.host, WM_APP_HIDEHOST, 0, 0)

    def _close_popup(self):
        """Esconde a janelinha (o Edge continua pronto, escondido, para a próxima abertura)."""
        if self.host:
            user32.ShowWindow(self.host, SW_HIDE)

    def _shutdown_edge(self):
        if self.edge and user32.IsWindow(self.edge):
            user32.PostMessageW(self.edge, WM_CLOSE, 0, 0)
        orphan = self._find_popup()
        if orphan:
            user32.PostMessageW(orphan, WM_CLOSE, 0, 0)

    def _host_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_ACTIVATE and (wparam & 0xFFFF) == WA_INACTIVE and user32.IsWindowVisible(hwnd):
            pinned = bool(self.control and self.control.pinned)
            if not pinned:                     # clicou fora: fecha, como um menu do Windows
                self.last_autoclose = time.time()
                self._close_popup()
            return 0
        if msg == WM_APP_SHOWHOST:
            user32.ShowWindow(hwnd, SW_SHOW)
            user32.SetForegroundWindow(hwnd)
            if self.edge:
                user32.SetFocus(self.edge)
            return 0
        if msg == WM_APP_HIDEHOST:
            user32.ShowWindow(hwnd, SW_HIDE)
            return 0
        if msg == WM_CLOSE:
            self._close_popup()
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # ----- menu -----
    def _menu(self):
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING, CMD_OPEN, "Abrir")
        user32.AppendMenuW(menu, MF_STRING, CMD_FULL, "Painel completo no navegador")
        user32.AppendMenuW(menu, MF_STRING, CMD_REFRESH, "Atualizar agora")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, CMD_QUIT, "Sair do Fôlego")
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)
        cmd = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                                    pt.x, pt.y, 0, self.hwnd, None)
        user32.DestroyMenu(menu)
        if cmd == CMD_OPEN:
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
            if wparam == TIMER_PRELOAD:
                user32.KillTimer(self.hwnd, TIMER_PRELOAD)
                if not self.edge:
                    self._launch_edge(show=False)
            else:
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
            self._shutdown_edge()
            if getattr(self, "_hook", None):
                user32.UnhookWinEvent(self._hook)
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def run(self, show: bool = False):
        self._shutdown_edge()   # janelinha órfã de uma execução anterior
        # Gancho de eventos de janela (criação/exibição), entregue a esta thread.
        self._winevent = WINEVENTPROC(
            lambda hook, ev, hwnd, obj, child, th, t: self.on_winevent(hwnd, ev) if obj == 0 else None)
        self._hook = user32.SetWinEventHook(EVENT_OBJECT_CREATE, EVENT_OBJECT_SHOW, None,
                                            self._winevent, 0, 0, WINEVENT_OUTOFCONTEXT)
        self._add_icon()
        user32.SetTimer(self.hwnd, 1, 60_000, None)
        self.refresh_async()
        if show:
            self._open_popup(at_cursor=False)
        else:
            user32.SetTimer(self.hwnd, TIMER_PRELOAD, 1500, None)   # prepara o Edge escondido
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        self.on_quit()
