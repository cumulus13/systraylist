"""Minimal tray host: acts as Shell_TrayWnd when Explorer is dead.

Apps re-register their icons on the 'TaskbarCreated' broadcast. We receive
Shell_NotifyIcon WM_COPYDATA, keep (hwnd, uID, callback msg, tooltip) and can
then send the icon's mouse callback to the owning app = same as clicking it.
Run at the same (or higher) elevation as the apps, else UIPI blocks messages.
"""
import ctypes
import struct
import threading
from ctypes import wintypes

import psutil
import win32api
import win32con
import win32gui
import win32process

WM_COPYDATA = 0x4A
SIG = 0x34753423
NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NIF_MESSAGE, NIF_TIP = 1, 4


class COPYDATA(ctypes.Structure):
    _fields_ = [('dwData', ctypes.c_size_t), ('cbData', wintypes.DWORD), ('lpData', ctypes.c_void_p)]


def _wstr(b):
    return b.decode('utf-16le', 'ignore').split('\0')[0]


def _parse(dw, data):
    """Return (msg, hwnd, uid, flags, cbmsg, tip, version) or None."""
    msg, off = dw, 0
    if len(data) >= 8 and struct.unpack_from('<I', data, 0)[0] == SIG:
        msg, off = struct.unpack_from('<I', data, 4)[0], 8
    n = data[off:]
    if len(n) >= 24:                                   # 32-bit handle layout
        cb, hwnd, uid, flags, cbm, _ = struct.unpack_from('<6I', n, 0)
        if hwnd and win32gui.IsWindow(hwnd):
            tip = _wstr(n[24:24 + 256]) if len(n) >= 280 else ''
            ver = struct.unpack_from('<I', n, 800)[0] if len(n) >= 804 else 0
            return msg, hwnd, uid, flags, cbm, tip, ver
    if len(n) >= 40:                                   # 64-bit handle layout
        cb, hwnd, uid, flags, cbm, _ = struct.unpack_from('<I4xQIII4xQ', n, 0)[:6]
        if hwnd and win32gui.IsWindow(hwnd):
            tip = _wstr(n[40:40 + 256]) if len(n) >= 296 else ''
            ver = struct.unpack_from('<I', n, 816)[0] if len(n) >= 820 else 0
            return msg, hwnd, uid, flags, cbm, tip, ver
    return None


class TrayHost:
    def __init__(self):
        self.icons = {}
        self.lock = threading.Lock()
        self._ready = threading.Event()
        self.err = None
        self.hwnd = None

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait(5)
        if self.err:
            raise RuntimeError(self.err)
        win32gui.PostMessage(win32con.HWND_BROADCAST, win32gui.RegisterWindowMessage('TaskbarCreated'), 0, 0)

    def _run(self):
        try:
            wc = win32gui.WNDCLASS()
            wc.lpszClassName = 'Shell_TrayWnd'
            wc.hInstance = win32api.GetModuleHandle(None)
            wc.lpfnWndProc = self._proc
            win32gui.RegisterClass(wc)
            self.hwnd = win32gui.CreateWindowEx(win32con.WS_EX_TOOLWINDOW, 'Shell_TrayWnd', '',
                                                win32con.WS_POPUP, 0, 0, 0, 0, 0, 0, wc.hInstance, None)
        except Exception as e:
            self.err = str(e)
            self._ready.set()
            return
        self._ready.set()
        win32gui.PumpMessages()

    def _proc(self, hwnd, msg, wp, lp):
        if msg == WM_COPYDATA:
            try:
                self._copydata(lp & 0xFFFFFFFFFFFFFFFF)
            except Exception:
                pass
            return 1
        return win32gui.DefWindowProc(hwnd, msg, wp, lp)

    def _copydata(self, lp):
        c = COPYDATA.from_address(lp)
        data = ctypes.string_at(c.lpData, c.cbData)
        r = _parse(c.dwData, data)
        if not r:
            return
        m, h, uid, flags, cbm, tip, ver = r
        key = (h, uid)
        with self.lock:
            if m == NIM_DELETE:
                self.icons.pop(key, None)
            elif m in (NIM_ADD, NIM_MODIFY):
                d = self.icons.setdefault(key, {'cb': 0, 'tip': '', 'ver': 0})
                if flags & NIF_MESSAGE:
                    d['cb'] = cbm
                if flags & NIF_TIP and tip:
                    d['tip'] = tip
            elif m == NIM_SETVERSION and key in self.icons:
                self.icons[key]['ver'] = ver

    def items(self):
        out = []
        with self.lock:
            for (h, uid), d in list(self.icons.items()):
                if not win32gui.IsWindow(h):
                    self.icons.pop((h, uid), None)
                    continue
                pid = win32process.GetWindowThreadProcessId(h)[1]
                try:
                    name = psutil.Process(pid).name()
                except Exception:
                    name = '?'
                label = f"{d['tip'] or '-'}  [{name} pid {pid}]"
                out.append((label, 'tray', {'hwnd': h, 'uid': uid, 'cb': d['cb'], 'ver': d['ver'], 'pid': pid}))
        return sorted(out, key=lambda x: x[0].lower())

    @staticmethod
    def click(ref, right=False, double=False):
        h, uid, cb, ver = ref['hwnd'], ref['uid'], ref['cb'], ref['ver']
        if not cb:
            return False
        x, y = win32api.GetCursorPos()
        ctypes.windll.user32.AllowSetForegroundWindow(0xFFFFFFFF)
        if right:
            evs = [0x204, 0x205] + ([0x7B] if ver >= 4 else [])        # RBUTTONDOWN/UP, CONTEXTMENU
        elif double:
            evs = [0x201, 0x202, 0x203, 0x202]                         # DOWN UP DBLCLK UP
        else:
            evs = [0x201, 0x202]                                       # LBUTTONDOWN/UP
        for ev in evs:
            if ver >= 4:
                wp = (x & 0xFFFF) | ((y & 0xFFFF) << 16)
                lp = (ev & 0xFFFF) | ((uid & 0xFFFF) << 16)
            else:
                wp, lp = uid, ev
            win32gui.PostMessage(h, cb, wp, lp)
        return True
