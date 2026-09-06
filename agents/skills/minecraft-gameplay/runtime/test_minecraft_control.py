# Copyright 2026 Wuyang Zhou and Tianyu Wei
# SPDX-License-Identifier: Apache-2.0

"""Mock-only tests: importing/running this file never injects Windows input."""
import math
import unittest
from unittest.mock import Mock, patch

import minecraft_control as control


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        if seconds <= 0:
            raise AssertionError('A bounded action must not request a nonpositive sleep.')
        self.sleeps.append(seconds)
        self.now += seconds


class RacingClock(FakeClock):
    """Model a thread descheduled between two reads of the same deadline."""
    def monotonic(self):
        self.now += 0.006
        return self.now

    def sleep(self, seconds):
        if seconds < 0:
            raise AssertionError('Scheduling delay must not produce a negative sleep.')
        self.sleeps.append(seconds)
        self.now += seconds


class TrackingOwnership(list):
    def __init__(self, count):
        super().__init__([0] * count)
        self.writes = []

    def __setitem__(self, index, value):
        self.writes.append((index, value))
        super().__setitem__(index, value)


class FakeBackend:
    """All inputs are recorded locally; no native backend is constructed."""
    def __init__(self, clock, reject_preflight=False, lose_focus_at=None,
                 fail_press=None, fail_release=None):
        self.clock = clock
        self.reject_preflight = reject_preflight
        self.lose_focus_at = lose_focus_at
        self.fail_press = fail_press
        self.fail_release = fail_release
        self.events = []
        self.preflight_calls = 0
        self.release_calls = []
        self.held = set()

    def preflight(self, target, keys, buttons):
        self.preflight_calls += 1
        if self.reject_preflight:
            raise control.ControlError('Preflight rejected')
        self.guard(target)

    def guard(self, target):
        if self.lose_focus_at is not None and self.clock.now >= self.lose_focus_at:
            raise control.ControlError('Minecraft lost focus')

    def _input(self, kind, name, pressed):
        self.events.append((self.clock.now, kind, name, pressed))
        identity = (kind, name)
        if pressed:
            # Simulate an uncertain press: it could have reached the OS before
            # the backend reported failure, so cleanup must include it.
            self.held.add(identity)
            if identity == self.fail_press:
                raise control.ControlError('Uncertain press failure')
        else:
            if identity == self.fail_release:
                raise control.ControlError('Release failure')
            self.held.discard(identity)

    def key(self, name, pressed):
        self._input('key', name, pressed)

    def button(self, name, pressed):
        self._input('button', name, pressed)

    def move(self, dx, dy):
        self.events.append((self.clock.now, 'move', dx, dy))

    def release(self, keys, buttons, on_released=None):
        self.release_calls.append((list(keys), list(buttons)))
        # Exercise the actual best-effort release routine with fake key/button
        # methods. Windows.__init__ and SendInput are never called.
        return control.Windows.release(self, keys, buttons, on_released=on_released)


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.backend = FakeBackend(self.clock)
        self.target = {'hwnd': 123, 'pid': 456}

    def perform(self, keys=None, buttons=None, seconds=0.25, dx=0, dy=0,
                backend=None, ownership=None):
        return control.perform(backend or self.backend, self.target,
                               keys or [], buttons or [], seconds, dx, dy,
                               clock=self.clock, ownership=ownership)

    def test_simultaneous_keys_and_button_remain_held_for_requested_duration(self):
        result = self.perform(keys=['w', 'space'], buttons=['left'], seconds=0.257)
        pressed = [e for e in self.backend.events if e[1] != 'move' and e[3]]
        released = [e for e in self.backend.events if e[1] != 'move' and not e[3]]
        self.assertEqual([(e[1], e[2]) for e in pressed],
                         [('key', 'w'), ('key', 'space'), ('button', 'left')])
        self.assertTrue(all(e[0] == 0.0 for e in pressed))
        self.assertEqual([(e[1], e[2]) for e in released],
                         [('button', 'left'), ('key', 'space'), ('key', 'w')])
        for event in released:
            self.assertAlmostEqual(event[0], 0.257)
        self.assertAlmostEqual(result['elapsed_seconds'], 0.257)
        self.assertEqual(self.backend.held, set())
        self.assertTrue(self.clock.sleeps)
        self.assertTrue(all(0 < interval <= 0.01 for interval in self.clock.sleeps))

    def test_relative_motion_is_distributed_and_has_exact_requested_totals(self):
        self.perform(keys=['w'], seconds=0.073, dx=-103, dy=67)
        moves = [event for event in self.backend.events if event[1] == 'move']
        self.assertGreater(len(moves), 1)
        self.assertEqual(sum(event[2] for event in moves), -103)
        self.assertEqual(sum(event[3] for event in moves), 67)
        self.assertGreater(moves[-1][0], moves[0][0])
        self.assertLess(moves[-1][0], 0.073)
        self.assertAlmostEqual(self.clock.now, 0.073)

    def test_focus_loss_aborts_early_and_releases_every_held_input(self):
        self.backend.lose_focus_at = 0.035
        with self.assertRaisesRegex(control.ControlError, 'lost focus'):
            self.perform(keys=['w', 'shift'], buttons=['left', 'right'],
                         seconds=0.5, dx=100, dy=-100)
        self.assertLess(self.clock.now, 0.5)
        self.assertLessEqual(self.clock.now, 0.045)
        self.assertEqual(self.backend.held, set())
        self.assertEqual(self.backend.release_calls,
                         [(['w', 'shift'], ['left', 'right'])])
        # Once focus is lost, the only remaining input events are releases.
        after_abort = [e for e in self.backend.events if e[0] >= 0.035]
        self.assertTrue(after_abort)
        self.assertTrue(all(e[1] in ('key', 'button') and not e[3]
                            for e in after_abort))

    def test_partial_key_press_failure_releases_successful_and_uncertain_press(self):
        self.backend.fail_press = ('key', 'a')
        with self.assertRaisesRegex(control.ControlError, 'Uncertain press'):
            self.perform(keys=['w', 'a', 'space'], buttons=['left'])
        self.assertEqual(self.backend.release_calls, [(['w', 'a'], [])])
        self.assertEqual(self.backend.held, set())
        self.assertFalse(any(e[1] == 'button' or e[2] == 'space'
                             for e in self.backend.events))
        self.assertEqual(self.clock.now, 0)

    def test_partial_button_press_failure_releases_all_attempted_inputs(self):
        self.backend.fail_press = ('button', 'right')
        with self.assertRaisesRegex(control.ControlError, 'Uncertain press'):
            self.perform(keys=['w'], buttons=['left', 'right', 'middle'])
        self.assertEqual(self.backend.release_calls, [(['w'], ['left', 'right'])])
        self.assertEqual(self.backend.held, set())
        self.assertFalse(any(e[2] == 'middle' for e in self.backend.events))
        self.assertEqual(self.clock.now, 0)

    def test_cleanup_continues_when_one_release_fails_and_reports_error(self):
        self.backend.fail_release = ('button', 'right')
        with self.assertRaisesRegex(control.ControlError, 'Could not release every input'):
            self.perform(keys=['w', 'space'], buttons=['left', 'right'])
        self.assertEqual(self.backend.held, {('button', 'right')})
        releases = [(e[1], e[2]) for e in self.backend.events
                    if e[1] != 'move' and not e[3]]
        self.assertEqual(releases,
                         [('button', 'right'), ('button', 'left'),
                          ('key', 'space'), ('key', 'w')])

    def test_preflight_rejection_emits_no_input_or_cleanup_events(self):
        self.backend.reject_preflight = True
        with self.assertRaisesRegex(control.ControlError, 'Preflight rejected'):
            self.perform(keys=['w'], buttons=['left'], dx=20)
        self.assertEqual(self.backend.preflight_calls, 1)
        self.assertEqual(self.backend.events, [])
        self.assertEqual(self.backend.release_calls, [])
        self.assertEqual(self.clock.sleeps, [])

    def test_invalid_actions_are_rejected_before_backend_is_used(self):
        invalid = [
            {'seconds': value} for value in
            (-1, 0, 0.019, 5.001, math.inf, -math.inf, math.nan)
        ]
        invalid += [
            {'keys': ['w', 'w']}, {'keys': ['unsupported']},
            {'buttons': ['left', 'left']}, {'buttons': ['unsupported']},
            {'dx': 2001}, {'dy': -2001}, {'dx': 1.2}, {'dy': True},
        ]
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    self.perform(**arguments)
        self.assertEqual(self.backend.preflight_calls, 0)
        self.assertEqual(self.backend.events, [])
        self.assertEqual(self.backend.release_calls, [])
        self.assertEqual(self.clock.sleeps, [])

    def test_minimum_and_maximum_duration_are_accepted(self):
        for seconds in (0.02, control.MAX_SECONDS):
            with self.subTest(seconds=seconds):
                start = self.clock.now
                self.perform(seconds=seconds)
                self.assertAlmostEqual(self.clock.now - start, seconds)

    def test_ownership_tracks_all_inputs_then_clears_on_success(self):
        ownership = TrackingOwnership(4)
        self.perform(keys=['w', 'space'], buttons=['left', 'right'], ownership=ownership)
        self.assertEqual(ownership, [0, 0, 0, 0])
        self.assertEqual(ownership.writes,
                         [(0, 1), (1, 1), (2, 1), (3, 1),
                          (3, 0), (2, 0), (1, 0), (0, 0)])
        self.assertEqual(self.backend.held, set())

    def test_ownership_clears_after_focus_abort_cleanup(self):
        ownership = TrackingOwnership(2)
        self.backend.lose_focus_at = 0.025
        with self.assertRaisesRegex(control.ControlError, 'lost focus'):
            self.perform(keys=['w'], buttons=['left'], ownership=ownership)
        self.assertEqual(ownership, [0, 0])
        self.assertEqual(ownership.writes, [(0, 1), (1, 1), (1, 0), (0, 0)])
        self.assertEqual(self.backend.held, set())

    def test_uncertain_press_is_owned_until_partial_press_cleanup(self):
        ownership = TrackingOwnership(3)
        self.backend.fail_press = ('key', 'a')
        with self.assertRaisesRegex(control.ControlError, 'Uncertain press'):
            self.perform(keys=['w', 'a'], buttons=['left'], ownership=ownership)
        self.assertEqual(ownership, [0, 0, 0])
        self.assertEqual([write for write in ownership.writes if write[1]],
                         [(0, 1), (1, 1)])
        self.assertEqual(self.backend.release_calls, [(['w', 'a'], [])])
        self.assertEqual(self.backend.held, set())

    def test_preflight_rejection_never_acquires_ownership(self):
        ownership = TrackingOwnership(2)
        self.backend.reject_preflight = True
        with self.assertRaisesRegex(control.ControlError, 'Preflight rejected'):
            self.perform(keys=['w'], buttons=['left'], ownership=ownership)
        self.assertEqual(ownership, [0, 0])
        self.assertEqual(ownership.writes, [])
        self.assertEqual(self.backend.events, [])
        self.assertEqual(self.backend.release_calls, [])

    def test_failed_release_keeps_only_failed_input_owned_for_watchdog(self):
        ownership = TrackingOwnership(2)
        self.backend.fail_release = ('button', 'left')
        with self.assertRaisesRegex(control.ControlError, 'Could not release every input'):
            self.perform(keys=['w'], buttons=['left'], ownership=ownership)
        self.assertEqual(ownership, [0, 1])
        self.assertEqual(ownership.writes, [(0, 1), (1, 1), (0, 0)])

    def test_partial_release_failure_clears_other_keys_and_buttons(self):
        keys = ['w', 'left', 'space']
        buttons = ['left', 'right']
        identities = [('key', name) for name in keys] + [('button', name) for name in buttons]
        # The same name for a key and a button verifies that ownership is
        # identified by both kind and name during selective cleanup.
        for failed in [('key', 'left'), ('button', 'left')]:
            with self.subTest(failed=failed):
                backend = FakeBackend(self.clock, fail_release=failed)
                ownership = TrackingOwnership(len(identities))
                with self.assertRaisesRegex(control.ControlError,
                                            'Could not release every input'):
                    self.perform(keys=keys, buttons=buttons, backend=backend,
                                 ownership=ownership)
                self.assertEqual(ownership, [int(identity == failed) for identity in identities])
                self.assertEqual(backend.held, {failed})
                cleared_indices = [index for index, value in ownership.writes if value == 0]
                self.assertCountEqual(cleared_indices,
                                      [i for i, identity in enumerate(identities) if identity != failed])

    def test_release_callback_follows_each_successful_up_and_skips_failed_up(self):
        self.backend.held = {('key', 'w'), ('button', 'left'), ('button', 'right')}
        self.backend.fail_release = ('button', 'right')
        callbacks = []

        def on_released(kind, name):
            self.assertEqual(self.backend.events[-1][1:], (kind, name, False))
            self.assertNotIn((kind, name), self.backend.held)
            callbacks.append((kind, name))

        errors = self.backend.release(['w'], ['left', 'right'], on_released=on_released)
        self.assertEqual(errors, ['Release failure'])
        self.assertEqual(callbacks, [('button', 'left'), ('key', 'w')])
        self.assertEqual(self.backend.held, {('button', 'right')})

    def test_descheduling_between_clock_reads_never_requests_negative_sleep(self):
        clock = RacingClock()
        backend = FakeBackend(clock)
        control.perform(backend, self.target, ['w'], [], 0.025, clock=clock)
        self.assertIn(0.0, clock.sleeps)
        self.assertTrue(all(0 <= interval <= 0.01 for interval in clock.sleeps))
        self.assertEqual(backend.held, set())


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.reader = Mock()
        self.stop_file = Mock()
        self.backend = Mock()
        self.backend.release.return_value = []
        self.windows_patch = patch.object(control, 'Windows', return_value=self.backend)
        self.windows = self.windows_patch.start()
        self.addCleanup(self.windows_patch.stop)
        self.stop_patch = patch.object(control, 'STOP_FILE', self.stop_file)
        self.stop_patch.start()
        self.addCleanup(self.stop_patch.stop)
        self.keys = ['w', 'space']
        self.buttons = ['left', 'right']
        # Noncontiguous flags verify the button offset and exclude unowned input.
        self.ownership = [0, 1, 1, 0]

    def run_watchdog(self):
        control.watchdog(self.reader, self.keys, self.buttons, self.ownership, 1.5)

    def assert_owned_cleanup(self):
        self.reader.close.assert_called_once_with()
        self.stop_file.touch.assert_called_once_with()
        self.windows.assert_called_once_with()
        self.backend.release.assert_called_once_with(['space'], ['left'])

    def test_timeout_releases_only_flagged_inputs(self):
        self.reader.poll.return_value = False
        self.run_watchdog()
        self.reader.poll.assert_called_once_with(1.5)
        self.reader.recv.assert_not_called()
        self.assert_owned_cleanup()

    def test_eof_receiving_message_releases_only_flagged_inputs(self):
        self.reader.poll.return_value = True
        self.reader.recv.side_effect = EOFError
        self.run_watchdog()
        self.reader.recv.assert_called_once_with()
        self.assert_owned_cleanup()

    def test_eof_polling_releases_only_flagged_inputs(self):
        self.reader.poll.side_effect = EOFError
        self.run_watchdog()
        self.reader.recv.assert_not_called()
        self.assert_owned_cleanup()

    def test_release_acknowledgement_skips_cleanup(self):
        self.reader.poll.return_value = True
        self.reader.recv.return_value = 'released'
        self.run_watchdog()
        self.reader.close.assert_called_once_with()
        self.stop_file.touch.assert_not_called()
        self.windows.assert_not_called()
        self.backend.release.assert_not_called()

    def test_unrecognized_message_still_cleans_up_flagged_inputs(self):
        self.reader.poll.return_value = True
        self.reader.recv.return_value = 'not-confirmed'
        self.run_watchdog()
        self.assert_owned_cleanup()

    def test_stop_file_failure_does_not_prevent_input_cleanup(self):
        self.reader.poll.return_value = False
        self.stop_file.touch.side_effect = OSError('Cannot write stop file')
        with self.assertRaisesRegex(OSError, 'Cannot write stop file'):
            self.run_watchdog()
        self.assert_owned_cleanup()

    def test_no_ownership_releases_no_keys_or_buttons(self):
        self.reader.poll.return_value = False
        self.ownership = [0, 0, 0, 0]
        self.run_watchdog()
        self.backend.release.assert_called_once_with([], [])


class MenuPointTests(unittest.TestCase):
    def setUp(self):
        self.backend = object.__new__(control.Windows)
        self.backend.u = Mock()
        self.backend.guard = Mock()
        self.target = {'hwnd': 123, 'pid': 456}

        def rectangle(hwnd, pointer):
            pointer._obj.right, pointer._obj.bottom = 1280, 649
            return True

        def to_screen(hwnd, pointer):
            pointer._obj.x += -1280  # A window on a monitor left of primary.
            pointer._obj.y += 23  # Client origin excludes the title bar.
            return True

        self.backend.u.GetClientRect.side_effect = rectangle
        self.backend.u.ClientToScreen.side_effect = to_screen
        self.backend.u.SetCursorPos.return_value = True

    def test_client_coordinates_translate_to_screen_without_title_bar_or_monitor_error(self):
        with patch.object(control.time, 'sleep'):
            self.backend.point(self.target, 942, 230)
        self.backend.u.SetCursorPos.assert_called_once_with(-338, 253)
        self.assertEqual(self.backend.guard.call_count, 3)

    def test_outside_client_points_never_position_cursor(self):
        for point in ((-1, 0), (0, -1), (1280, 0), (0, 649)):
            with self.subTest(point=point), self.assertRaises(ValueError):
                self.backend.point(self.target, *point)
        self.backend.u.SetCursorPos.assert_not_called()

    def test_focus_loss_after_coordinate_conversion_prevents_positioning(self):
        self.backend.guard.side_effect = [None, control.ControlError('Focus lost')]
        with self.assertRaisesRegex(control.ControlError, 'Focus lost'):
            self.backend.point(self.target, 942, 230)
        self.backend.u.SetCursorPos.assert_not_called()

    def test_failed_positioning_is_reported(self):
        self.backend.u.SetCursorPos.return_value = False
        with self.assertRaisesRegex(control.ControlError, 'position the menu cursor'):
            self.backend.point(self.target, 942, 230)

    def test_cli_rejects_combined_absolute_and_relative_motion_before_targeting(self):
        argv = ['minecraft_control.py', 'act', '--at', '942', '230', '--dx', '1']
        with patch.object(control.sys, 'argv', argv), patch.object(control, 'Windows') as windows:
            with self.assertRaisesRegex(ValueError, 'cannot be combined'):
                control.main()
        windows.return_value.choose.assert_not_called()


class MotionStepsTests(unittest.TestCase):
    def test_exact_integer_totals_for_positive_negative_and_zero_deltas(self):
        for dx in (-2000, -103, -1, 0, 1, 103, 2000):
            for dy in (-2000, -67, -1, 0, 1, 67, 2000):
                for count in (1, 3, 17, 500):
                    with self.subTest(dx=dx, dy=dy, count=count):
                        steps = list(control.motion_steps(dx, dy, count))
                        self.assertEqual(len(steps), count)
                        self.assertEqual(sum(x for x, _ in steps), dx)
                        self.assertEqual(sum(y for _, y in steps), dy)
                        self.assertTrue(all(isinstance(v, int)
                                            for pair in steps for v in pair))
                        # Quantization may vary step sizes by one count.
                        self.assertLessEqual(max(x for x, _ in steps) -
                                             min(x for x, _ in steps), 1)
                        self.assertLessEqual(max(y for _, y in steps) -
                                             min(y for _, y in steps), 1)


if __name__ == '__main__':
    unittest.main()
