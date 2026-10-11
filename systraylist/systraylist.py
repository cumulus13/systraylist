import os, sys, re, time
import win32gui, win32process, psutil
from pywinauto.controls.uiawrapper import UIAWrapper
from pywinauto.uia_element_info import UIAElementInfo
from pywinauto.keyboard import send_keys

OVERFLOW_RE = r'TopLevelWindowForOverflowXamlIsland|NotifyIconOverflowWindow'
TRAYCLS_RE = r'(?i)tray|notifyicon|gntp|notify'


def _hwnds(pattern):
    r, out = re.compile(pattern), []

    def cb(h, _):
        try:
            if r.search(win32gui.GetClassName(h)):
                out.append(h)
        except Exception:
            pass
        return True

    win32gui.EnumWindows(cb, None)
    return out


def _wrap(h):
    return UIAWrapper(UIAElementInfo(h))


def _btns(w):
    try:
        return w.descendants(control_type='Button')
    except Exception:
        return []


def _name(b):
    try:
        return (b.window_text() or b.element_info.automation_id or '?').strip()
    except Exception:
        return '?'


def _is_chev(b):
    i = b.element_info
    s = f'{i.automation_id} {i.name}'.lower()
    return 'chevron' in s or 'hidden icons' in s or 'show hidden' in s


def _is_tray(b):
    if b.element_info.automation_id == 'SystemTrayIcon':
        return True
    try:
        return 'notification' in b.parent().window_text().lower()
    except Exception:
        return False


def _taskbars():
    return [_wrap(h) for h in _hwnds(r'^Shell_TrayWnd$')]


def _visible():
    bs = []
    for t in _taskbars():
        bs += _btns(t)
    chev = next((b for b in bs if _is_chev(b)), None)
    return chev, [b for b in bs if b is not chev and _is_tray(b)]


def _overflow(chev):
    if not chev:
        return []
    chev.click_input()
    time.sleep(0.6)
    for h in _hwnds(OVERFLOW_RE):
        bs = _btns(_wrap(h))
        tray = [b for b in bs if b.element_info.automation_id == 'SystemTrayIcon'] or \
               [b for b in bs if _is_tray(b)] or bs
        if tray:
            return tray
    return []


def _close():
    send_keys('{ESC}')


# ---- fallback: no Explorer taskbar -> list background/tray-like processes ----

IGNORE_CLS = re.compile(
    r'^(IME|MSCTFIME UI|Default IME|GDI\+ Hook Window Class|DDE Server Window|'
    r'SystemResourceNotifyWindow|CicMarshalWnd|tooltips_class32|UIRibbonStatic|'
    r'MediaContextNotificationWindow|Static|ForegroundStaging|WorkerW|Progman)$'
    r'|^\.NET-BroadcastEventWindow|^WMI|^BroadcastListenerWindow')
SKIP_PROCS = {'explorer.exe', 'svchost.exe', 'ctfmon.exe', 'dwm.exe', 'csrss.exe', 'conhost.exe',
              'runtimebroker.exe', 'dllhost.exe', 'sihost.exe', 'taskhostw.exe', 'searchhost.exe',
              'startmenuexperiencehost.exe', 'shellexperiencehost.exe', 'textinputhost.exe',
              'applicationframehost.exe', 'systemsettings.exe', 'lockapp.exe', 'fontdrvhost.exe',
              'winlogon.exe', 'wininit.exe', 'services.exe', 'lsass.exe', 'cmd.exe',
              'windowsterminal.exe', 'powershell.exe', 'pwsh.exe', 'openconsole.exe', 'rundll32.exe',
              'crash_handler.exe'}


def _all_windows():
    """(hwnd, class, title, visible, msgonly) for top-level + message-only windows."""
    out = []

    def cb(h, _):
        try:
            out.append((h, win32gui.GetClassName(h), win32gui.GetWindowText(h),
                        bool(win32gui.IsWindowVisible(h)), False))
        except Exception:
            pass
        return True

    win32gui.EnumWindows(cb, None)
    prev = 0
    while True:
        try:
            h = win32gui.FindWindowEx(-3, prev, None, None)   # HWND_MESSAGE
        except Exception:
            break
        if not h:
            break
        try:
            out.append((h, win32gui.GetClassName(h), win32gui.GetWindowText(h), False, True))
        except Exception:
            pass
        prev = h
    return out


def _proc_items(all_=False):
    procs = {}
    for h, cls, title, vis, msg in _all_windows():
        try:
            pid = win32process.GetWindowThreadProcessId(h)[1]
        except Exception:
            continue
        d = procs.setdefault(pid, {'tray': False, 'rel': 0, 'vis': False, 'msg': False, 'any': 0})
        d['any'] += 1
        if IGNORE_CLS.search(cls):
            continue
        d['rel'] += 1
        d['msg'] |= msg
        if re.search(TRAYCLS_RE, cls):
            d['tray'] = True
        if vis and title:
            d['vis'] = True
    items = []
    for pid, d in procs.items():
        try:
            name = psutil.Process(pid).name()
        except Exception:
            continue
        if pid == os.getpid() or (name.lower() in SKIP_PROCS and not all_):
            continue
        if all_:
            ok = d['any'] > 0
        else:
            ok = d['tray'] or (d['rel'] > 0 and not d['vis']) or d['msg']
        if ok:
            tag = ('T' if d['tray'] else '-') + ('M' if d['msg'] else '-') + ('V' if d['vis'] else '-')
            items.append((f'{name} (pid {pid}) {tag}', 'process', pid))
    return sorted(items, key=lambda x: x[0].lower())


def _show_pid(pid):
    import win32con
    cand, soft = [], []

    def cb(h, _):
        try:
            if win32process.GetWindowThreadProcessId(h)[1] != pid:
                return True
            cls = win32gui.GetClassName(h)
            if IGNORE_CLS.search(cls) or re.search(TRAYCLS_RE, cls):
                return True
            if win32gui.GetWindowText(h):
                cand.append(h)
            else:
                l, t, r, b = win32gui.GetWindowRect(h)
                if r - l > 50 and b - t > 50:
                    soft.append(h)
        except Exception:
            pass
        return True

    win32gui.EnumWindows(cb, None)
    wins = cand or soft
    for h in wins:
        win32gui.ShowWindow(h, win32con.SW_SHOW)
        win32gui.ShowWindow(h, win32con.SW_RESTORE)
        try:
            win32gui.SetForegroundWindow(h)
        except Exception:
            pass
    if not wins:
        print(f'pid {pid}: no real window (only helper/GDI windows). Use e<N> to relaunch the exe; single-instance apps then show themselves.')


def _relaunch(pid):
    import subprocess
    try:
        subprocess.Popen([psutil.Process(pid).exe()])
    except Exception as e:
        print(f'relaunch failed: {e}')


_HOST = None


def _host_items():
    global _HOST
    first = _HOST is None
    if first:
        from .host import TrayHost
        _HOST = TrayHost()
        _HOST.start()
        time.sleep(2.5)                      # let apps re-register after TaskbarCreated
    return _HOST.items()


def collect(all_=False, procs=False):
    if all_ or procs:
        return _proc_items(all_)
    if _taskbars():
        chev, vis = _visible()
        items = [(_name(b), 'visible', None) for b in vis]
        ov = _overflow(chev)
        items += [(_name(b), 'hidden', None) for b in ov]
        if ov:
            _close()
        return items
    try:                                      # Explorer dead: act as the tray host
        items = _host_items()
        if items:
            return items
        print('(tray host started, no app re-registered yet; showing process list. try l to refresh)')
    except Exception as e:
        print(f'(tray host failed: {e}; showing process list)')
    return _proc_items()


def activate(idx, items, mode=''):
    label, kind, ref = items[idx]
    if kind == 'tray':
        if mode == 'e':
            return _relaunch(ref['pid'])
        if mode == 's':
            return _show_pid(ref['pid'])
        if not _HOST.click(ref, right=(mode == 'r'), double=(mode == 'd')):
            print('icon has no callback message; use s<N> (show window) or e<N> (relaunch)')
        return
    if kind == 'process':
        return _relaunch(ref) if mode == 'e' else _show_pid(ref)
    chev, vis = _visible()
    if kind == 'visible':
        tgt = vis[sum(1 for x in items[:idx] if x[1] == 'visible')]
    else:
        ov = _overflow(chev)
        tgt = ov[sum(1 for x in items[:idx] if x[1] == 'hidden')]
    tgt.click_input(button='right' if mode == 'r' else 'left')


def _print(items, flt=''):
    for i, (n, k, _) in enumerate(items):
        if flt in n.lower():
            print(f'{i:3}  [{k[0]}] {n}')


def _cmd(s, items):
    m = re.match(r'^([resd]?)(\d+)$', s)
    if not m or int(m.group(2)) >= len(items):
        print('?')
        return
    activate(int(m.group(2)), items, m.group(1))


HELP = ('\nN = click/show | rN = right-click | dN = double-click | sN = show real window | '
        'eN = relaunch exe\n/text = filter | l = refresh | a = all processes | q = quit')


def main():
    args = sys.argv[1:]
    all_ = any(a in ('-a', '--all') for a in args)
    procs = any(a in ('-p', '--procs') for a in args)
    list_only = any(a in ('-l', '--list') for a in args)
    rest = [a for a in args if not a.startswith('-')]
    items = collect(all_, procs)
    if not items:
        print('nothing found')
        return
    if rest:                                   # one-shot: systraylist 3 / r3
        return _cmd(rest[0].strip().lower(), items)
    _print(items)
    if list_only:
        return
    print(HELP)
    while True:
        try:
            s = input('#> ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if s in ('q', 'quit', 'exit', ''):
            break
        if s == 'l':
            items = collect(all_, procs)
            _print(items)
        elif s == 'a':
            items = collect(True)
            _print(items)
        elif s.startswith('/'):
            _print(items, s[1:])
        else:
            _cmd(s, items)


if __name__ == '__main__':
    main()
