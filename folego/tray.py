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


def _dwm_plain(hwnd) -> None:
    """Tira toda a pintura do Windows em volta da página: sem moldura, borda, fundo (Mica)
    nem cantos do sistema. Sem isso o Windows preenche o retângulo inteiro da janela com um
    fundo escuro, que aparece como uma "sobra" em cima e dos lados do painel."""
    for attr, value in (
        (2, 1),            # DWMWA_NCRENDERING_POLICY = DWMNCRP_DISABLED
        (34, 0xFFFFFFFE),  # DWMWA_BORDER_COLOR = DWMWA_COLOR_NONE
        (33, 1),           # DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_DONOTROUND (o recorte arredonda)
        (38, 1),           # DWMWA_SYSTEMBACKDROP_TYPE = DWMSBT_NONE
    ):
        v = wintypes.DWORD(value)
        dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), 4)


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
    def __init__(self, get_limits, on_quit):
        self.get_limits = get_limits          # função(force: bool) -> list[dict]
        self.on_quit = on_quit
        self.popup: subprocess.Popen | None = None
        self.tip = "Fôlego"
        self.alerted: dict[str, int] = {}      # chave da janela -> último nível avisado (80/100)
        self.pending_balloon: tuple[str, str, int] | None = None
        self.lock = threading.Lock()
        # Coordenadas reais de tela (sem a "virtualização" de DPI do Windows).
        try:
            user32.SetProcessDpiAwarenessContext(-4)   # PER_MONITOR_AWARE_V2
        except (OSError, AttributeError):
            pass
        # Moldura do Edge em pixels; é remedida na 1ª abertura.
        self.frame = (9, 37, 8, 8)
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
        """Janela de app do Edge com o painel (título termina em 'Fôlego' ou 'Fôlego · GGDS').

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
            if buf.value.endswith("— Fôlego") or buf.value == "Fôlego · GGDS":
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

    # Geometria em pixels físicos. O processo é "per-monitor DPI aware".
    def _target(self) -> tuple[float, int, int, int, int]:
        """Escala e retângulo (x, y, w, h) onde o conteúdo deve ficar: canto do relógio."""
        # Num clique no ícone, o monitor é o do mouse (onde está a barra de tarefas clicada).
        # Abrindo sozinha (início do Windows), usa o monitor principal.
        pt = wintypes.POINT()
        if self.at_cursor:
            user32.GetCursorPos(ctypes.byref(pt))
        mon = user32.MonitorFromPoint(pt, MONITOR_DEFAULTTOPRIMARY if not self.at_cursor else MONITOR_DEFAULTTONEAREST)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(mon, ctypes.byref(info))
        dpi_x, dpi_y = wintypes.UINT(96), wintypes.UINT(96)
        try:
            shcore.GetDpiForMonitor(mon, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
        except OSError:
            pass
        s = dpi_x.value / 96
        w, h, m = round(POPUP_W * s), round((POPUP_H + TOP_GUARD) * s), round(12 * s)
        work = info.rcWork
        return s, work.right - m - w, work.bottom - m - h, w, h

    def _open_popup(self, at_cursor: bool = True):
        self.at_cursor = at_cursor
        url = f"http://127.0.0.1:{PORT}/?mini=1"
        edge = _edge_path()
        if not edge:
            webbrowser.open(url)
            return
        s, x, y, w, h = self._target()
        left, top, right, bottom = self.frame   # moldura do Edge (barra de título, bordas)
        profile = Path(os.environ.get("LOCALAPPDATA", Path.home()), "Folego", "janela")
        profile.mkdir(parents=True, exist_ok=True)
        # Deixa o Edge vir para a frente com foco (necessário para "clicou fora, fecha").
        user32.AllowSetForegroundWindow(ASFW_ANY)
        # O Edge recebe tamanho/posição em DIPs: já abre praticamente no lugar final.
        subprocess.Popen([
            edge, f"--app={url}", f"--user-data-dir={profile}",
            f"--window-size={round((w + left + right) / s)},{round((h + top + bottom) / s)}",
            f"--window-position={round((x - left) / s)},{round((y - top) / s)}",
            "--no-first-run", "--no-default-browser-check", "--disable-sync",
            "--disable-extensions", "--disable-features=Translate,msEdgeSidebarV2",
        ], creationflags=CREATE_NO_WINDOW)
        threading.Thread(target=self._shape_when_ready, daemon=True).start()

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

    def _shape_when_ready(self):
        """Espera a janela do Edge, transforma-a num painel suspenso e fica de vigia enquanto
        ela estiver aberta: se o Edge redesenhar a moldura (e desfizer o recorte), reaplica na hora."""
        s, x, y, w, h = self._target()
        deadline = time.time() + 15          # 1ª abertura após o login pode ser lenta
        shaped: int | None = None
        missing_since: float | None = None
        while True:
            hwnd = self._find_popup()
            child = hwnd and self._render_child(hwnd)
            if not child:
                if shaped is None and time.time() > deadline:
                    return
                if shaped is not None:
                    missing_since = missing_since or time.time()
                    if time.time() - missing_since > 1.0:   # janela fechada
                        return
                time.sleep(0.02)
                continue
            missing_since = None
            if hwnd != shaped:
                self._apply_shape(hwnd, child, s, x, y, w, h, first=True)
                shaped = hwnd
                user32.SetForegroundWindow(hwnd)
            elif not self._shape_ok(hwnd, child, x, y, w, h):
                self._apply_shape(hwnd, child, s, x, y, w, h, first=False)
            time.sleep(0.05)

    def _frame_of(self, hwnd, child) -> tuple[int, int, int, int]:
        """Moldura real do Edge (barra de título + bordas), medida pela área da página."""
        win, page = wintypes.RECT(), wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(win))
        user32.GetWindowRect(child, ctypes.byref(page))
        frame = (page.left - win.left, page.top - win.top, win.right - page.right, win.bottom - page.bottom)
        return frame if all(0 <= v < 200 for v in frame) else self.frame

    def _shape_ok(self, hwnd, child, x, y, w, h) -> bool:
        page, box = wintypes.RECT(), wintypes.RECT()
        user32.GetWindowRect(child, ctypes.byref(page))
        got = (page.left, page.top, page.right - page.left, page.bottom - page.top)
        if any(abs(a - b) > 2 for a, b in zip(got, (x, y, w, h))):   # tolera arredondamento
            return False
        left, top, _, _ = self._frame_of(hwnd, child)
        kind = user32.GetWindowRgnBox(hwnd, ctypes.byref(box))
        if kind in (0, 1):                     # ERROR ou NULLREGION: o recorte sumiu
            return False
        if (box.left, box.top, box.right, box.bottom) != getattr(self, "rgn_box", None):
            return False
        return self._styles_ok(hwnd)

    def _styles_ok(self, hwnd) -> bool:
        st = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        # (Não exige "sempre por cima": o Edge o remove da própria janela e brigar com ele causaria
        #  reajustes sem fim. A janelinha abre em primeiro plano e fecha ao perder o foco.)
        return (not (st & FRAME_STYLES) and bool(ex & WS_EX_TOOLWINDOW)
                and not (ex & WS_EX_APPWINDOW))

    def _apply_shape(self, hwnd, child, s, x, y, w, h, first: bool):
        # 1) Sem moldura do Windows: sem barra de título, nada de botões desenhados pelo sistema.
        #    (Com barra de título, o estilo "ferramenta" faz o Windows desenhar um "X" que o
        #    recorte não esconde; sem a barra, não há o que desenhar.)
        # 2) Estilo "ferramenta": fora da barra de tarefas e do Alt+Tab, e pode ficar por cima.
        #    (Uma janela "dona" de outro processo também tiraria da barra, mas impede o "por cima".)
        if first or not self._styles_ok(hwnd):
            st = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
            ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongPtrW(hwnd, GWL_STYLE, st & ~FRAME_STYLES)
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
            user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
            _taskbar_delete_tab(hwnd)
        _dwm_plain(hwnd)
        # 2) Posiciona a página exatamente no canto.
        left, top, right, bottom = self.frame = self._frame_of(hwnd, child)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, x - left, y - top, w + left + right, h + top + bottom,
                            SWP_NOACTIVATE)
        # A moldura pode mudar depois de reposicionar: mede de novo antes de recortar.
        left, top, right, bottom = self.frame = self._frame_of(hwnd, child)
        # 3) Recorta só a página: barra de título e bordas do Edge ficam de fora.
        radius = round(28 * s)  # diâmetro da curva = 2 × 14 px (igual ao CSS)
        # O recorte termina exatamente no contorno desenhado pelo CSS:
        # - à direita, o Edge sem moldura às vezes não pinta a última coluna da página; por isso
        #   o contorno fica 1 px (CSS) para dentro e o recorte acompanha (largura = POPUP_W - 1);
        # - embaixo, vai até o fim da área da página.
        page = wintypes.RECT()
        user32.GetWindowRect(child, ctypes.byref(page))
        pw = min(round((POPUP_W - RIGHT_INSET) * s), page.right - page.left)
        ph = page.bottom - page.top
        g = round(TOP_GUARD * s)
        rgn = gdi32.CreateRoundRectRgn(left, top + g, left + pw + 1, top + ph + 1, radius, radius)
        user32.SetWindowRgn(hwnd, rgn, True)   # o Windows passa a ser dono da região
        box = wintypes.RECT()
        user32.GetWindowRgnBox(hwnd, ctypes.byref(box))
        self.rgn_box = (box.left, box.top, box.right, box.bottom)

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
        user32.AppendMenuW(menu, MF_STRING, CMD_QUIT, "Sair do Fôlego")
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
        self._close_popup()   # janelinha órfã de uma execução anterior (sem vigia)
        self._add_icon()
        user32.SetTimer(self.hwnd, 1, 60_000, None)
        self.refresh_async()
        if show:
            self._open_popup(at_cursor=False)
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        self.on_quit()
