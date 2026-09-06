# Copyright 2026 Wuyang Zhou and Tianyu Wei
# SPDX-License-Identifier: Apache-2.0

"""Run a bounded Minecraft action plan with local visual checkpoints. Python 3.8+."""
import argparse
import json
import math
import multiprocessing as MP
from pathlib import Path
import sys
import time

import minecraft_control as mc

MAX_STEPS = 32
MAX_WALL_SECONDS = 30.0
COMPARISON_MODES = ('pixels', 'bright_text', 'red_pixels')


class SequenceError(mc.ControlError):
    def __init__(self, message, report):
        super().__init__(message)
        self.report = report


def number(value, low, high, label):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not low <= value <= high):
        raise ValueError('%s must be between %s and %s.' % (label, low, high))
    return value


def prepare(plan, base):
    """Validate the complete plan and load all image references before any input."""
    from PIL import Image
    if not isinstance(plan, dict) or plan.get('version') != 1:
        raise ValueError('Expected a version 1 plan object.')
    if set(plan) - {'version', 'name', 'client_size', 'checks', 'start_check', 'steps', 'max_seconds'}:
        raise ValueError('Unknown plan fields.')
    size = plan.get('client_size')
    if (not isinstance(size, list) or len(size) != 2
            or any(type(v) is not int or not 1 <= v <= 7680 for v in size)):
        raise ValueError('client_size must be [native_width, native_height].')
    budget = number(plan.get('max_seconds', 20), 1, MAX_WALL_SECONDS, 'max_seconds')
    checks = {}
    raw_checks = plan.get('checks', {})
    if not isinstance(raw_checks, dict):
        raise ValueError('checks must be an object.')
    for name, check in raw_checks.items():
        if not isinstance(check, dict) or set(check) - {'image', 'regions', 'max_mean_error', 'mode'}:
            raise ValueError('Invalid visual check: ' + name)
        image_path = (Path(base) / check['image']).resolve()
        with Image.open(str(image_path)) as reference:
            reference = reference.convert('RGB')
        if list(reference.size) != size:
            raise ValueError('Reference size does not match client_size: ' + name)
        regions = check.get('regions', [])
        if not isinstance(regions, list) or not 1 <= len(regions) <= 16:
            raise ValueError('A visual check needs 1–16 regions.')
        for rect in regions:
            if (not isinstance(rect, list) or len(rect) != 4 or any(type(v) is not int for v in rect)
                    or not 0 <= rect[0] < rect[2] <= size[0]
                    or not 0 <= rect[1] < rect[3] <= size[1]):
                raise ValueError('Invalid visual check rectangle: ' + name)
        mode = check.get('mode', 'pixels')
        if mode not in COMPARISON_MODES:
            raise ValueError('Unknown visual comparison mode.')
        checks[name] = {'regions': regions, 'reference': reference, 'mode': mode,
                        'max_mean_error': number(check.get('max_mean_error', 8), 0, 30, 'max_mean_error')}
    start = plan.get('start_check')
    if start not in checks:
        raise ValueError('start_check must name a loaded visual check.')
    raw_steps = plan.get('steps')
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= MAX_STEPS:
        raise ValueError('A sequence requires 1–32 steps.')
    steps, planned = [], 0.0
    allowed = {'label', 'keys', 'buttons', 'seconds', 'dx', 'dy', 'at', 'settle',
               'expect_before', 'expect_after', 'repeat', 'watch', 'progress'}
    for index, raw in enumerate(raw_steps, 1):
        if not isinstance(raw, dict) or set(raw) - allowed:
            raise ValueError('Unknown fields in step %d.' % index)
        step = dict(raw)
        step.setdefault('label', 'Step %d' % index)
        if not isinstance(step['label'], str) or len(step['label']) > 160:
            raise ValueError('Step label must be a short string.')
        for field in ('keys', 'buttons'):
            step.setdefault(field, [])
            if not isinstance(step[field], list) or any(not isinstance(v, str) for v in step[field]):
                raise ValueError(field + ' must be a list of names.')
        step.setdefault('seconds', 0.08)
        step.setdefault('settle', 0.12)
        step.setdefault('dx', 0)
        step.setdefault('dy', 0)
        number(step['seconds'], 0.02, mc.MAX_SECONDS, 'seconds')
        number(step['settle'], 0.02, 2, 'settle')
        mc.validate_action(step['keys'], step['buttons'], step['seconds'], step['dx'], step['dy'])
        point = step.get('at')
        if point is not None:
            if (not isinstance(point, list) or len(point) != 2 or any(type(v) is not int for v in point)
                    or not 0 <= point[0] < size[0] or not 0 <= point[1] < size[1]):
                raise ValueError('Invalid native menu point in step %d.' % index)
            if step['dx'] or step['dy']:
                raise ValueError('Menu points and relative motion cannot be combined.')
        for field in ('expect_before', 'expect_after'):
            if field in step and step[field] not in checks:
                raise ValueError('Unknown visual check in step %d.' % index)
        repeat = step.pop('repeat', 1)
        if type(repeat) is not int or not 1 <= repeat <= 16:
            raise ValueError('repeat must be an integer from 1 to 16.')
        watch = step.get('watch', [])
        if (not isinstance(watch, list) or len(watch) > 8
                or any(not isinstance(name, str) or name not in checks for name in watch)):
            raise ValueError('watch must list up to eight loaded visual checks.')
        progress = step.get('progress')
        if progress is not None:
            if (not isinstance(progress, dict)
                    or not {'regions', 'min_mean_error'} <= set(progress)
                    or set(progress) - {'regions', 'min_mean_error', 'mode'}):
                raise ValueError('progress requires regions and min_mean_error.')
            regions = progress['regions']
            if not isinstance(regions, list) or not 1 <= len(regions) <= 16:
                raise ValueError('progress requires 1–16 regions.')
            for rect in regions:
                if (not isinstance(rect, list) or len(rect) != 4
                        or any(type(v) is not int for v in rect)
                        or not 0 <= rect[0] < rect[2] <= size[0]
                        or not 0 <= rect[1] < rect[3] <= size[1]):
                    raise ValueError('Invalid progress rectangle.')
            number(progress['min_mean_error'], 0.01, 255, 'progress min_mean_error')
            if progress.get('mode', 'pixels') not in COMPARISON_MODES:
                raise ValueError('Unknown progress comparison mode.')
        # A point click must be tied to a confirmed layout, not just window focus.
        if point is not None and 'expect_before' not in step:
            raise ValueError('Menu point steps require expect_before.')
        if repeat > 1 and (point is not None or step['dx'] or step['dy']):
            raise ValueError('Repeated steps must keep a fixed aim and cannot use menu points.')
        if repeat > 1 and progress is None:
            raise ValueError('Repeated steps require a progress check for every repetition.')
        planned += repeat * (step['seconds'] + step['settle'] + (0.05 if point is not None else 0))
        for repetition in range(repeat):
            expanded = dict(step)
            if repeat > 1:
                expanded['label'] = '%s (%d/%d)' % (step['label'], repetition + 1, repeat)
            steps.append(expanded)
        if len(steps) > MAX_STEPS:
            raise ValueError('Expanded sequence exceeds 32 steps.')
    if planned >= budget:
        raise ValueError('Planned input time leaves no room within max_seconds.')
    if 'expect_after' not in steps[-1]:
        raise ValueError('The final step needs expect_after to verify its ending state.')
    return {'name': plan.get('name', 'sequence'), 'client_size': size, 'checks': checks,
            'start_check': start, 'steps': steps, 'max_seconds': budget,
            'planned_seconds': round(planned, 3)}


def match_frame(frame, check):
    from PIL import ImageChops, ImageStat
    reference = check['reference']
    if frame.size != reference.size:
        return False, [255.0]
    transform = lambda source: source.convert('RGB')
    if check.get('mode') == 'bright_text':
        # Minecraft debug text is bright over a dark translucent backing.
        # Ignore changes in the dim world behind it; this is not text recognition.
        def text_mask(source):
            red, green, blue = source.convert('RGB').split()
            low = ImageChops.darker(red, ImageChops.darker(green, blue))
            high = ImageChops.lighter(red, ImageChops.lighter(green, blue))
            neutral = ImageChops.subtract(high, low).point(lambda value: 255 if value <= 12 else 0)
            bright = low.point(lambda value: 255 if value >= 200 else 0)
            return ImageChops.multiply(bright, neutral).convert('RGB')
        transform = text_mask
    elif check.get('mode') == 'red_pixels':
        def red_mask(source):
            red, green, blue = source.convert('RGB').split()
            red = red.point(lambda value: 255 if value >= 160 else 0)
            green = green.point(lambda value: 255 if value <= 100 else 0)
            blue = blue.point(lambda value: 255 if value <= 100 else 0)
            return ImageChops.multiply(red, ImageChops.multiply(green, blue)).convert('RGB')
        transform = red_mask
    errors = []
    for rect in check['regions']:
        delta = ImageChops.difference(transform(frame.crop(rect)), transform(reference.crop(rect)))
        errors.append(round(sum(ImageStat.Stat(delta).mean) / 3.0, 3))
    return max(errors) <= check['max_mean_error'], errors


class OwnershipView:
    def __init__(self, shared, indices):
        self.shared, self.indices = shared, indices

    def __setitem__(self, index, value):
        self.shared[self.indices[index]] = value


class DeadlineBackend:
    """Keep the existing input implementation, adding a deadline to every guard."""
    def __init__(self, backend, deadline, clock):
        self.backend, self.deadline, self.clock = backend, deadline, clock

    def __getattr__(self, name):
        return getattr(self.backend, name)

    def guard(self, target):
        if self.clock.monotonic() >= self.deadline:
            raise mc.ControlError('Sequence wall-clock deadline reached.')
        self.backend.guard(target)

    def preflight(self, target, keys, buttons):
        self.guard(target)
        self.backend.preflight(target, keys, buttons)


class WatchedBackend:
    """Sample visual guards during a hold; never inject input from a watcher."""
    def __init__(self, backend, sample, clock, interval=0.25):
        self.backend, self.sample, self.clock = backend, sample, clock
        self.interval, self.next_sample, self.samples = interval, 0.0, 0

    def __getattr__(self, name):
        return getattr(self.backend, name)

    def guard(self, target):
        self.backend.guard(target)
        if self.clock.monotonic() >= self.next_sample:
            self.sample()
            self.samples += 1
            self.next_sample = self.clock.monotonic() + self.interval
        self.backend.guard(target)

    def preflight(self, target, keys, buttons):
        self.backend.preflight(target, keys, buttons)
        self.guard(target)


def await_watchdog(reader, wall_deadline, clock=time):
    deadline = wall_deadline
    try:
        while True:
            remaining = min(deadline, wall_deadline) - clock.monotonic()
            if remaining <= 0 or not reader.poll(remaining):
                return False
            message = reader.recv()
            if message == 'released':
                return True
            if isinstance(message, dict) and set(message) == {'deadline'}:
                deadline = min(float(message['deadline']), wall_deadline)
            else:
                return False
    except (EOFError, OSError):
        return False
    finally:
        reader.close()


def sequence_watchdog(reader, keys, buttons, ownership, wall_deadline):
    if await_watchdog(reader, wall_deadline):
        return
    try:
        mc.STOP_FILE.touch()
    finally:
        errors = mc.Windows().release(
            [key for i, key in enumerate(keys) if ownership[i]],
            [button for i, button in enumerate(buttons, len(keys)) if ownership[i]])
        if errors:
            print('Sequence watchdog cleanup: ' + '; '.join(errors), file=sys.stderr)


def execute(backend, target, plan, clock=time, shared=None, writer=None):
    start = clock.monotonic()
    deadline = start + plan['max_seconds']
    checked = DeadlineBackend(backend, deadline, clock)
    keys = list(dict.fromkeys(k for step in plan['steps'] for k in step['keys']))
    buttons = list(dict.fromkeys(b for step in plan['steps'] for b in step['buttons']))
    if shared is None:
        shared = [0] * (len(keys) + len(buttons))
    report = {'name': plan['name'], 'status': 'running', 'completed_steps': 0, 'steps': []}
    active = 'start check'

    def frame():
        checked.guard(target)
        current = backend.frame(target)
        checked.guard(target)
        if list(current.size) != plan['client_size']:
            raise mc.ControlError('Game client size changed; sequence stopped.')
        return current

    def visual(name, wait=False):
        check_deadline = min(deadline, clock.monotonic() + (0.6 if wait else 0))
        while True:
            matches, errors = match_frame(frame(), plan['checks'][name])
            if matches:
                return {'check': name, 'region_errors': errors}
            if clock.monotonic() >= check_deadline:
                raise mc.ControlError('Visual check failed: %s (region errors %s).' % (name, errors))
            clock.sleep(0.04)

    def wait(seconds):
        until = clock.monotonic() + seconds
        while clock.monotonic() < until:
            checked.guard(target)
            clock.sleep(max(0.0, min(0.01, until - clock.monotonic())))

    try:
        report['start'] = visual(plan['start_check'])
        for index, step in enumerate(plan['steps'], 1):
            active = '%d: %s' % (index, step['label'])
            item = {'index': index, 'label': step['label']}
            if 'expect_before' in step:
                item['before'] = visual(step['expect_before'])
            checked.preflight(target, step['keys'], step['buttons'])
            baseline = frame() if step.get('progress') else None
            if step.get('at') is not None:
                backend.point(target, *step['at'])
                checked.guard(target)
            indices = [keys.index(k) for k in step['keys']]
            indices += [len(keys) + buttons.index(b) for b in step['buttons']]
            if writer is not None:
                # Per-action lease: a hung key hold is cleaned up before the whole plan deadline.
                writer.send({'deadline': min(deadline, clock.monotonic() + step['seconds'] + 1.0)})
            watch_names = step.get('watch', [])
            def watch_frame():
                current = frame()
                for name in watch_names:
                    matches, errors = match_frame(current, plan['checks'][name])
                    if not matches:
                        raise mc.ControlError('During-action visual check failed: %s (%s).' % (name, errors))
            actor = WatchedBackend(checked, watch_frame, clock) if watch_names else checked
            item['input_completed'] = False
            report['steps'].append(item)
            try:
                item['input'] = mc.perform(actor, target, step['keys'], step['buttons'], step['seconds'],
                                           step['dx'], step['dy'], clock, OwnershipView(shared, indices))
                item['input_completed'] = True
            finally:
                if watch_names:
                    item['watch_samples'] = actor.samples
            if writer is not None:
                writer.send({'deadline': deadline})
            wait(step['settle'])
            if 'expect_after' in step:
                item['after'] = visual(step['expect_after'], wait=True)
            if baseline is not None:
                progress = step['progress']
                _, errors = match_frame(frame(), {'reference': baseline, 'regions': progress['regions'],
                                                   'max_mean_error': 0, 'mode': progress.get('mode', 'pixels')})
                # Pixel change is a stall detector, not semantic proof of a gameplay effect.
                passed = max(errors) >= progress['min_mean_error']
                item['progress'] = {'kind': 'pixel_change', 'passed': passed, 'region_errors': errors}
                if not passed:
                    raise mc.ControlError('No visible progress in configured regions; remaining steps cancelled.')
            report['completed_steps'] = index
        checked.guard(target)
        report['status'] = 'complete'
    except Exception as exc:
        report.update(status='stopped', stopped_at=active, error=str(exc))
        raise SequenceError(str(exc), report) from exc
    finally:
        report['elapsed_seconds'] = round(clock.monotonic() - start, 4)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan')
    parser.add_argument('--focus', action='store_true')
    parser.add_argument('--hwnd', type=int)
    parser.add_argument('--capture', default='captures/sequence-final.png')
    parser.add_argument('--report', default='captures/sequence-report.json')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    source = Path(args.plan).resolve()
    plan = prepare(json.loads(source.read_text(encoding='utf-8-sig')), source.parent)
    if args.dry_run:
        print(json.dumps({'valid': True, 'name': plan['name'], 'steps': len(plan['steps']),
                          'planned_seconds': plan['planned_seconds'], 'max_seconds': plan['max_seconds']}))
        return 0
    backend = mc.Windows()
    target = backend.choose(args.hwnd)
    mutex = backend.lock()
    report, writer, monitor = {}, None, None
    exit_code = 0
    try:
        if args.focus:
            backend.focus(target)
        backend.guard(target)
        keys = list(dict.fromkeys(k for step in plan['steps'] for k in step['keys']))
        buttons = list(dict.fromkeys(b for step in plan['steps'] for b in step['buttons']))
        ctx = MP.get_context('spawn')
        ownership = ctx.RawArray('b', len(keys) + len(buttons))
        reader, writer = ctx.Pipe(duplex=False)
        monitor = ctx.Process(target=sequence_watchdog,
                              args=(reader, keys, buttons, ownership, time.monotonic() + plan['max_seconds'] + 1))
        monitor.start()
        reader.close()
        try:
            report = execute(backend, target, plan, shared=ownership, writer=writer)
        except SequenceError as exc:
            report = exc.report
            exit_code = 1
        finally:
            try:
                if not any(ownership):
                    writer.send('released')
            except (BrokenPipeError, EOFError, OSError):
                pass
            writer.close()
            monitor.join(1.0)
        # A failure never triggers Escape or clicks. Capture only if the guard still permits it.
        try:
            report['capture'] = backend.capture(target, args.capture)
        except (mc.ControlError, OSError) as exc:
            report['capture_error'] = str(exc)
        report_path = Path(args.report).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps({'status': report['status'], 'completed_steps': report['completed_steps'],
                          'elapsed_seconds': report['elapsed_seconds'], 'error': report.get('error'),
                          'capture': report.get('capture'), 'capture_error': report.get('capture_error'),
                          'report': str(report_path)}, indent=2))
        return exit_code
    finally:
        backend.unlock(mutex)


if __name__ == '__main__':
    MP.freeze_support()
    try:
        sys.exit(main())
    except (mc.ControlError, ValueError, OSError, KeyError, TypeError, KeyboardInterrupt) as exc:
        print(json.dumps({'error': str(exc) or 'Interrupted'}), file=sys.stderr)
        sys.exit(1)
