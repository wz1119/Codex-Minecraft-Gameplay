# Copyright 2026 Wuyang Zhou and Tianyu Wei
# SPDX-License-Identifier: Apache-2.0

"""Bounded Windows input adapter for a foreground Minecraft game. Python 3.8+."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
import math
import multiprocessing as MP
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
STOP_FILE = ROOT / '.minecraft-control-stop'
MAX_SECONDS = 5.0
# Physical PC scan codes; extended keys are marked separately.
KEYS = {
    'w': (0x11, 0x57, False), 'a': (0x1e, 0x41, False),
    's': (0x1f, 0x53, False), 'd': (0x20, 0x44, False),
    'e': (0x12, 0x45, False), 'q': (0x10, 0x51, False),
    'f': (0x21, 0x46, False), 't': (0x14, 0x54, False),
    'h': (0x23, 0x48, False),
    'space': (0x39, 0x20, False), 'shift': (0x2a, 0xa0, False),
    'ctrl': (0x1d, 0xa2, False), 'esc': (0x01, 0x1b, False),
    'enter': (0x1c, 0x0d, False), 'tab': (0x0f, 0x09, False),
    'f3': (0x3d, 0x72, False), 'f5': (0x3f, 0x74, False),
    'up': (0x48, 0x26, True), 'down': (0x50, 0x28, True),
    'left': (0x4b, 0x25, True), 'right': (0x4d, 0x27, True),
}
KEYS.update({str(n): (n + 1, 0x30 + n, False) for n in range(1, 10)})
BUTTONS = {'left': (0x0002, 0x0004, 0x01),
           'right': (0x0008, 0x0010, 0x02),
           'middle': (0x0020, 0x0040, 0x04)}


class ControlError(RuntimeError):
    pass


class MOUSEINPUT(C.Structure):
    _fields_ = [('dx', W.LONG), ('dy', W.LONG), ('mouseData', W.DWORD),
                ('dwFlags', W.DWORD), ('time', W.DWORD), ('dwExtraInfo', C.c_size_t)]


class KEYBDINPUT(C.Structure):
    _fields_ = [('wVk', W.WORD), ('wScan', W.WORD), ('dwFlags', W.DWORD),
                ('time', W.DWORD), ('dwExtraInfo', C.c_size_t)]


class HARDWAREINPUT(C.Structure):
    _fields_ = [('uMsg', W.DWORD), ('wParamL', W.WORD), ('wParamH', W.WORD)]


class INPUTUNION(C.Union):
    _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT), ('hi', HARDWAREINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ('u',)
    _fields_ = [('type', W.DWORD), ('u', INPUTUNION)]


def validate_action(keys, buttons, seconds, dx, dy):
    if not math.isfinite(seconds) or not 0.02 <= seconds <= MAX_SECONDS:
        raise ValueError('Duration must be between 0.02 and 5 seconds.')
    if len(set(keys)) != len(keys) or any(k not in KEYS for k in keys):
        raise ValueError('Keys must be unique supported names: ' + ', '.join(KEYS))
    if len(set(buttons)) != len(buttons) or any(b not in BUTTONS for b in buttons):
        raise ValueError('Buttons must be unique: left, right, middle.')
    if any(isinstance(v, bool) or not isinstance(v, int) or abs(v) > 2000 for v in (dx, dy)):
        raise ValueError('Relative mouse totals must be integers from -2000 to 2000.')


def motion_steps(dx, dy, count):
    """Integer deltas whose sums are exact, including negative directions."""
    last_x = last_y = 0
    for i in range(1, count + 1):
        x, y = round(dx * i / count), round(dy * i / count)
        yield x - last_x, y - last_y
        last_x, last_y = x, y


class Windows:
    def __init__(self):
        if os.name != 'nt':
            raise ControlError('This adapter requires Windows.')
        self.u = C.WinDLL('user32', use_last_error=True)
        self.k = C.WinDLL('kernel32', use_last_error=True)
        self.enum_cb = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        self._bind(self.u, 'EnumWindows', [self.enum_cb, W.LPARAM], W.BOOL)
        self._bind(self.u, 'IsWindow', [W.HWND], W.BOOL)
        self._bind(self.u, 'IsWindowVisible', [W.HWND], W.BOOL)
        self._bind(self.u, 'IsIconic', [W.HWND], W.BOOL)
        self._bind(self.u, 'GetWindowTextLengthW', [W.HWND], C.c_int)
        self._bind(self.u, 'GetWindowTextW', [W.HWND, W.LPWSTR, C.c_int], C.c_int)
        self._bind(self.u, 'GetClassNameW', [W.HWND, W.LPWSTR, C.c_int], C.c_int)
        self._bind(self.u, 'GetWindowThreadProcessId', [W.HWND, C.POINTER(W.DWORD)], W.DWORD)
        self._bind(self.u, 'GetForegroundWindow', [], W.HWND)
        self._bind(self.u, 'SetForegroundWindow', [W.HWND], W.BOOL)
        self._bind(self.u, 'GetAsyncKeyState', [C.c_int], C.c_short)
        self._bind(self.u, 'SendInput', [W.UINT, C.POINTER(INPUT), C.c_int], W.UINT)
        self._bind(self.u, 'GetClientRect', [W.HWND, C.POINTER(W.RECT)], W.BOOL)
        self._bind(self.u, 'ClientToScreen', [W.HWND, C.POINTER(W.POINT)], W.BOOL)
        self._bind(self.u, 'SetCursorPos', [C.c_int, C.c_int], W.BOOL)
        self._bind(self.k, 'OpenProcess', [W.DWORD, W.BOOL, W.DWORD], W.HANDLE)
        self._bind(self.k, 'QueryFullProcessImageNameW', [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)], W.BOOL)
        self._bind(self.k, 'CloseHandle', [W.HANDLE], W.BOOL)
        self._bind(self.k, 'CreateMutexW', [C.c_void_p, W.BOOL, W.LPCWSTR], W.HANDLE)
        self._bind(self.k, 'WaitForSingleObject', [W.HANDLE, W.DWORD], W.DWORD)
        self._bind(self.k, 'ReleaseMutex', [W.HANDLE], W.BOOL)
        if C.sizeof(INPUT) != (40 if C.sizeof(C.c_void_p) == 8 else 28):
            raise ControlError('Unexpected Win32 INPUT layout.')
        try:
            self._bind(self.u, 'SetProcessDpiAwarenessContext', [C.c_void_p], W.BOOL)
            self.u.SetProcessDpiAwarenessContext(C.c_void_p(-4))
        except AttributeError:
            self.u.SetProcessDPIAware()

    @staticmethod
    def _bind(lib, name, args, result):
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, result

    def pid(self, hwnd):
        value = W.DWORD()
        if not self.u.GetWindowThreadProcessId(hwnd, C.byref(value)):
            return 0
        return value.value

    def describe(self, hwnd):
        buf = C.create_unicode_buffer(self.u.GetWindowTextLengthW(hwnd) + 1)
        self.u.GetWindowTextW(hwnd, buf, len(buf))
        cls = C.create_unicode_buffer(256)
        self.u.GetClassNameW(hwnd, cls, len(cls))
        pid = self.pid(hwnd)
        proc = self.k.OpenProcess(0x1000, False, pid)
        exe = ''
        if proc:
            try:
                path, size = C.create_unicode_buffer(32768), W.DWORD(32768)
                if self.k.QueryFullProcessImageNameW(proc, 0, path, C.byref(size)):
                    exe = path.value
            finally:
                self.k.CloseHandle(proc)
        return {'hwnd': int(hwnd), 'pid': pid, 'title': buf.value,
                'class_name': cls.value, 'executable': exe,
                'foreground': self.u.GetForegroundWindow() == hwnd,
                'minimized': bool(self.u.IsIconic(hwnd))}

    def games(self):
        found = []
        def visit(hwnd, _):
            if self.u.IsWindowVisible(hwnd):
                length = self.u.GetWindowTextLengthW(hwnd)
                title = C.create_unicode_buffer(length + 1)
                self.u.GetWindowTextW(hwnd, title, length + 1)
                if title.value.startswith('Minecraft') and 'Launcher' not in title.value:
                    item = self.describe(hwnd)
                    if Path(item['executable']).name.lower() in ('javaw.exe', 'java.exe', 'minecraft.windows.exe'):
                        found.append(item)
            return True
        callback = self.enum_cb(visit)
        if not self.u.EnumWindows(callback, 0):
            raise ControlError('Unable to enumerate game windows.')
        return found

    def choose(self, hwnd=None):
        candidates = self.games()
        if hwnd is not None:
            candidates = [w for w in candidates if w['hwnd'] == hwnd]
        if len(candidates) != 1:
            raise ControlError('Expected exactly one Minecraft game window; found %d. Use status and --hwnd.' % len(candidates))
        return candidates[0]

    def focus(self, target):
        if target['minimized']:
            raise ControlError('Restore Minecraft from the taskbar first.')
        self.u.SetForegroundWindow(target['hwnd'])
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            if self.u.GetForegroundWindow() == target['hwnd']:
                return
            time.sleep(0.01)
        raise ControlError('Windows did not grant focus to Minecraft.')

    def guard(self, target):
        if STOP_FILE.exists() or self.down(0x77):
            raise ControlError('Stopped: F8 or stop file.')
        if (not self.u.IsWindow(target['hwnd']) or self.pid(target['hwnd']) != target['pid']
                or self.u.GetForegroundWindow() != target['hwnd'] or self.u.IsIconic(target['hwnd'])):
            raise ControlError('Minecraft lost focus or its window identity changed.')

    def down(self, vk):
        return bool(self.u.GetAsyncKeyState(vk) & 0x8000)

    def preflight(self, target, keys, buttons):
        self.guard(target)
        # Existing modifiers could turn otherwise benign keys into OS shortcuts.
        vks = [0x10, 0x11, 0x12, 0x5b, 0x5c]
        vks += [KEYS[name][1] for name in keys] + [BUTTONS[name][2] for name in buttons]
        if any(self.down(vk) for vk in vks):
            raise ControlError('Release physical keys/buttons before starting an action.')

    def _send(self, event):
        C.set_last_error(0)
        if self.u.SendInput(1, C.byref(event), C.sizeof(INPUT)) != 1:
            raise ControlError('SendInput failed (Win32 error %d); game may have a different privilege level.' % C.get_last_error())

    def key(self, name, pressed):
        scan, _, extended = KEYS[name]
        flags = 0x0008 | (0x0001 if extended else 0) | (0 if pressed else 0x0002)
        item = INPUT(type=1)
        item.ki = KEYBDINPUT(0, scan, flags, 0, 0)
        self._send(item)

    def button(self, name, pressed):
        flags = BUTTONS[name][0 if pressed else 1]
        item = INPUT(type=0)
        item.mi = MOUSEINPUT(0, 0, 0, flags, 0, 0)
        self._send(item)

    def move(self, dx, dy):
        if dx or dy:
            item = INPUT(type=0)
            item.mi = MOUSEINPUT(dx, dy, 0, 0x0001, 0, 0)
            self._send(item)

    def point(self, target, x, y):
        """Position a menu cursor using native game-client screenshot coordinates."""
        self.guard(target)
        rect, point = W.RECT(), W.POINT(x, y)
        if not self.u.GetClientRect(target['hwnd'], C.byref(rect)):
            raise ControlError('Unable to locate the game client rectangle.')
        if not (0 <= x < rect.right and 0 <= y < rect.bottom):
            raise ValueError('Menu cursor point is outside the game client area.')
        if not self.u.ClientToScreen(target['hwnd'], C.byref(point)):
            raise ControlError('Unable to convert the menu cursor point.')
        self.guard(target)
        if not self.u.SetCursorPos(point.x, point.y):
            raise ControlError('Unable to position the menu cursor.')
        time.sleep(0.05)
        self.guard(target)

    def release(self, keys, buttons, on_released=None):
        errors = []
        for name in reversed(buttons):
            try:
                self.button(name, False)
                if on_released is not None:
                    on_released('button', name)
            except Exception as exc:
                errors.append(str(exc))
        for name in reversed(keys):
            try:
                self.key(name, False)
                if on_released is not None:
                    on_released('key', name)
            except Exception as exc:
                errors.append(str(exc))
        return errors

    def lock(self):
        handle = self.k.CreateMutexW(None, False, 'Local\\CodexMinecraftControl')
        if not handle:
            raise ControlError('Unable to create adapter mutex.')
        if self.k.WaitForSingleObject(handle, 0) not in (0, 0x80):
            self.k.CloseHandle(handle)
            raise ControlError('Another adapter action is already running.')
        return handle

    def unlock(self, handle):
        self.k.ReleaseMutex(handle)
        self.k.CloseHandle(handle)

    def frame(self, target):
        """Return a native client image for local checks without PNG encoding."""
        self.guard(target)
        from PIL import ImageGrab
        rect, point = W.RECT(), W.POINT(0, 0)
        if not self.u.GetClientRect(target['hwnd'], C.byref(rect)) or not self.u.ClientToScreen(target['hwnd'], C.byref(point)):
            raise ControlError('Unable to locate the game client rectangle.')
        box = (point.x, point.y, point.x + rect.right, point.y + rect.bottom)
        frame = ImageGrab.grab(bbox=box, all_screens=True)
        self.guard(target)
        return frame

    def capture(self, target, destination, max_width=1600):
        frame = self.frame(target)
        original = frame.size
        if frame.width > max_width:
            frame = frame.resize((max_width, round(frame.height * max_width / frame.width)))
        path = Path(destination).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.save(str(path))
        return {'path': str(path), 'source_size': list(original), 'image_size': list(frame.size)}


def perform(backend, target, keys, buttons, seconds, dx=0, dy=0, clock=time, ownership=None):
    """One bounded action. Every acquired input is released even on abort."""
    validate_action(keys, buttons, seconds, dx, dy)
    backend.preflight(target, keys, buttons)
    held_keys, held_buttons = [], []
    start = clock.monotonic()
    try:
        for index, key in enumerate(keys):
            backend.guard(target)
            held_keys.append(key)  # Include an attempted press if its result is uncertain.
            if ownership is not None:
                ownership[index] = 1
            backend.key(key, True)
        for index, button in enumerate(buttons, len(keys)):
            backend.guard(target)
            held_buttons.append(button)
            if ownership is not None:
                ownership[index] = 1
            backend.button(button, True)
        steps = max(1, math.ceil(seconds / 0.01))
        for i, (mx, my) in enumerate(motion_steps(dx, dy, steps), 1):
            backend.guard(target)
            backend.move(mx, my)
            deadline = start + seconds * i / steps
            while clock.monotonic() < deadline:
                backend.guard(target)
                clock.sleep(max(0.0, min(0.01, deadline - clock.monotonic())))
        backend.guard(target)
    finally:
        if ownership is None:
            errors = backend.release(held_keys, held_buttons)
        else:
            def clear_released(kind, name):
                index = keys.index(name) if kind == 'key' else len(keys) + buttons.index(name)
                ownership[index] = 0
            errors = backend.release(held_keys, held_buttons, on_released=clear_released)
        if errors:
            raise ControlError('Could not release every input: ' + '; '.join(errors))
    return {'elapsed_seconds': round(clock.monotonic() - start, 4),
            'keys': keys, 'buttons': buttons, 'mouse_delta': [dx, dy]}


def watchdog(reader, keys, buttons, ownership, timeout):
    """Independent cleanup if the action process dies or exceeds its time budget."""
    try:
        if reader.poll(timeout) and reader.recv() == 'released':
            return
    except EOFError:
        pass
    finally:
        reader.close()
    try:
        STOP_FILE.touch()
    finally:
        owned_keys = [k for i, k in enumerate(keys) if ownership[i]]
        owned_buttons = [b for i, b in enumerate(buttons, len(keys)) if ownership[i]]
        errors = Windows().release(owned_keys, owned_buttons)
        if errors:
            print('Watchdog cleanup: ' + '; '.join(errors), file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    subs.add_parser('status')
    subs.add_parser('stop')
    subs.add_parser('reset-stop')
    for name in ('act', 'capture'):
        sub = subs.add_parser(name)
        sub.add_argument('--hwnd', type=int)
        sub.add_argument('--focus', action='store_true')
        sub.add_argument('--capture', required=name == 'capture')
        sub.add_argument('--max-width', type=int, default=1600)
        if name == 'act':
            sub.add_argument('--keys', nargs='*', default=[])
            sub.add_argument('--buttons', nargs='*', default=[])
            sub.add_argument('--seconds', type=float, default=0.1)
            sub.add_argument('--dx', type=int, default=0)
            sub.add_argument('--dy', type=int, default=0)
            sub.add_argument('--at', nargs=2, type=int, metavar=('X', 'Y'),
                             help='Menu cursor point in native game-client pixels; do not use during mouse-look.')
            sub.add_argument('--settle', type=float, default=0.15)
    args = parser.parse_args()
    if args.command == 'stop':
        STOP_FILE.touch()
        return {'stopped': True}
    if args.command == 'reset-stop':
        if STOP_FILE.exists():
            STOP_FILE.unlink()
        return {'stopped': False}
    backend = Windows()
    if args.command == 'status':
        return {'games': backend.games(), 'stop_requested': STOP_FILE.exists(),
                'input_struct_bytes': C.sizeof(INPUT), 'max_action_seconds': MAX_SECONDS}
    if not 320 <= args.max_width <= 7680:
        raise ValueError('--max-width must be between 320 and 7680.')
    if args.command == 'act':
        validate_action(args.keys, args.buttons, args.seconds, args.dx, args.dy)
        if not math.isfinite(args.settle) or not 0 <= args.settle <= 2:
            raise ValueError('--settle must be between 0 and 2 seconds.')
        if args.at is not None and (args.dx or args.dy):
            raise ValueError('--at cannot be combined with relative mouse deltas.')
    target = backend.choose(args.hwnd)
    mutex = backend.lock()
    try:
        if args.focus:
            backend.focus(target)
        backend.guard(target)
        output = {'target': target}
        if args.command == 'act':
            backend.preflight(target, args.keys, args.buttons)
            if args.at is not None:
                backend.point(target, *args.at)
            ctx = MP.get_context('spawn')
            reader, writer = ctx.Pipe(duplex=False)
            ownership = ctx.RawArray('b', len(args.keys) + len(args.buttons))
            monitor = ctx.Process(target=watchdog, args=(reader, args.keys, args.buttons, ownership, args.seconds + 2.0))
            monitor.start()
            reader.close()
            try:
                output['action'] = perform(backend, target, args.keys, args.buttons, args.seconds, args.dx, args.dy, ownership=ownership)
            finally:
                try:
                    if not any(ownership):
                        writer.send('released')
                except (BrokenPipeError, EOFError):
                    pass
                finally:
                    writer.close()
                    monitor.join(1.0)
            deadline = time.monotonic() + args.settle
            while time.monotonic() < deadline:
                backend.guard(target)
                time.sleep(max(0.0, min(0.01, deadline - time.monotonic())))
        if args.capture:
            output['capture'] = backend.capture(target, args.capture, args.max_width)
        return output
    finally:
        backend.unlock(mutex)


if __name__ == '__main__':
    MP.freeze_support()
    try:
        print(json.dumps(main(), indent=2))
    except (ControlError, ValueError, OSError, KeyboardInterrupt) as exc:
        print(json.dumps({'error': str(exc) or 'Interrupted'}), file=sys.stderr)
        sys.exit(1)
