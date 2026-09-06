# Copyright 2026 Wuyang Zhou and Tianyu Wei
# SPDX-License-Identifier: Apache-2.0

"""Sequence tests use synthetic images and fake inputs only."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from PIL import Image
import minecraft_control as mc
import minecraft_sequence as seq
from test_minecraft_control import FakeBackend, FakeClock


class ScreenBackend(FakeBackend):
    def __init__(self, clock):
        super().__init__(clock)
        self.screen = 'closed'
        self.ignore_toggle = False
        self.size = (1280, 649)
        self.points = []

    def frame(self, target):
        return Image.new('RGB', self.size, 'white' if self.screen == 'open' else 'black')

    def key(self, name, pressed):
        super().key(name, pressed)
        if name == 'e' and not pressed and not self.ignore_toggle:
            self.screen = 'open' if self.screen == 'closed' else 'closed'

    def point(self, target, x, y):
        self.guard(target)
        self.points.append((x, y))


class SequenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        Image.new('RGB', (1280, 649), 'black').save(str(self.base / 'closed.png'))
        Image.new('RGB', (1280, 649), 'white').save(str(self.base / 'open.png'))
        self.raw = {'version': 1, 'name': 'test', 'client_size': [1280, 649], 'max_seconds': 5,
                    'checks': {name: {'image': name + '.png', 'regions': [[0, 0, 100, 100]],
                                     'max_mean_error': 0} for name in ('closed', 'open')},
                    'start_check': 'closed', 'steps': [
                        {'keys': ['e'], 'expect_after': 'open'},
                        {'at': [500, 200], 'keys': ['shift'], 'buttons': ['left'],
                         'expect_before': 'open', 'expect_after': 'open'},
                        {'keys': ['e'], 'expect_after': 'closed'}]}
        self.clock = FakeClock()
        self.backend = ScreenBackend(self.clock)
        self.target = {'hwnd': 123, 'pid': 456}

    def plan(self):
        return seq.prepare(self.raw, self.base)

    def test_ordered_sequence_checks_layout_and_releases_between_steps(self):
        report = seq.execute(self.backend, self.target, self.plan(), self.clock)
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(report['completed_steps'], 3)
        self.assertEqual(self.backend.points, [(500, 200)])
        self.assertEqual(self.backend.held, set())
        self.assertEqual(self.backend.screen, 'closed')
        events = [(e[1], e[2], e[3]) for e in self.backend.events if e[1] != 'move']
        self.assertEqual(events, [('key', 'e', True), ('key', 'e', False),
                                  ('key', 'shift', True), ('button', 'left', True),
                                  ('button', 'left', False), ('key', 'shift', False),
                                  ('key', 'e', True), ('key', 'e', False)])

    def test_wrong_start_screen_emits_no_inputs(self):
        self.backend.screen = 'open'
        with self.assertRaises(seq.SequenceError) as raised:
            seq.execute(self.backend, self.target, self.plan(), self.clock)
        self.assertEqual(raised.exception.report['completed_steps'], 0)
        self.assertEqual(self.backend.events, [])

    def test_failed_transition_stops_before_later_menu_click(self):
        self.backend.ignore_toggle = True
        with self.assertRaisesRegex(seq.SequenceError, 'Visual check failed') as raised:
            seq.execute(self.backend, self.target, self.plan(), self.clock)
        self.assertEqual(raised.exception.report['completed_steps'], 0)
        self.assertTrue(raised.exception.report['steps'][0]['input_completed'])
        self.assertEqual(self.backend.points, [])
        self.assertEqual(self.backend.held, set())

    def test_client_resize_stops_before_input(self):
        self.backend.size = (1280, 650)
        with self.assertRaisesRegex(seq.SequenceError, 'client size changed'):
            seq.execute(self.backend, self.target, self.plan(), self.clock)
        self.assertEqual(self.backend.events, [])

    def test_focus_loss_during_hold_releases_and_cancels_remaining_steps(self):
        self.backend.lose_focus_at = 0.025
        with self.assertRaisesRegex(seq.SequenceError, 'lost focus'):
            seq.execute(self.backend, self.target, self.plan(), self.clock)
        self.assertEqual(self.backend.held, set())
        self.assertEqual(self.backend.points, [])
        self.assertLess(self.clock.now, 0.06)

    def test_wall_deadline_releases_active_input(self):
        plan = self.plan()
        plan['max_seconds'] = 0.035
        with self.assertRaisesRegex(seq.SequenceError, 'deadline'):
            seq.execute(self.backend, self.target, plan, self.clock)
        self.assertEqual(self.backend.held, set())
        self.assertEqual(self.backend.points, [])

    def test_shared_ownership_maps_step_keys_and_mouse_independently(self):
        shared, writer = [0, 0, 0], Mock()
        seq.execute(self.backend, self.target, self.plan(), self.clock, shared, writer)
        self.assertEqual(shared, [0, 0, 0])
        self.assertEqual(writer.send.call_count, 6)
        leases = [call.args[0]['deadline'] for call in writer.send.call_args_list]
        self.assertLess(leases[0], leases[1])

    def test_rejects_bad_future_steps_during_preparation(self):
        mutations = [
            lambda p: p['steps'][1].update(at=[1280, 0]),
            lambda p: p['steps'][1].update(dx=1),
            lambda p: p['steps'][1].pop('expect_before'),
            lambda p: p['steps'][1].update(seconds=5.1),
            lambda p: p['steps'][1].update(keys='w'),
            lambda p: p['steps'][1].update(seconds=float('nan')),
            lambda p: p['steps'][1].update(unknown=True),
            lambda p: p['steps'][1].update(expect_after='missing'),
            lambda p: p['steps'][-1].pop('expect_after'),
            lambda p: p.update(max_seconds=31),
            lambda p: p.update(steps=p['steps'] * 11),
            lambda p: p['checks']['open'].update(regions=[[0, 0, 1281, 649]]),
        ]
        for mutate in mutations:
            raw = copy.deepcopy(self.raw)
            mutate(raw)
            with self.subTest(raw=repr(raw)[:150]), self.assertRaises(ValueError):
                seq.prepare(raw, self.base)

    def test_checks_compare_each_region_not_average_over_whole_image(self):
        reference = Image.new('RGB', (20, 20), 'black')
        actual = reference.copy()
        actual.paste('white', (0, 0, 2, 2))
        matched, errors = seq.match_frame(actual, {'reference': reference,
                                                  'regions': [[0, 0, 2, 2], [5, 5, 20, 20]],
                                                  'max_mean_error': 8})
        self.assertFalse(matched)
        self.assertEqual(errors, [255.0, 0.0])

    def test_repeat_expands_and_checks_progress_after_every_iteration(self):
        def frame(target):
            result = Image.new('RGB', self.backend.size, 'black')
            if self.backend.screen == 'open':
                result.paste('white', (500, 200, 510, 210))
            return result
        self.backend.frame = frame
        self.raw['steps'] = [{'keys': ['e'], 'repeat': 3, 'expect_after': 'closed',
                              'progress': {'regions': [[500, 200, 510, 210]], 'min_mean_error': 1}}]
        report = seq.execute(self.backend, self.target, self.plan(), self.clock)
        self.assertEqual(report['completed_steps'], 3)
        self.assertTrue(all(step['progress']['passed'] for step in report['steps']))
        self.assertEqual(sum(e[1:4] == ('key', 'e', True) for e in self.backend.events), 3)
        self.assertEqual(self.backend.held, set())

    def test_no_progress_cancels_repetitions_after_releasing_input(self):
        self.raw['steps'] = [{'keys': ['w'], 'repeat': 3, 'expect_after': 'closed',
                              'progress': {'regions': [[500, 200, 510, 210]], 'min_mean_error': 1}}]
        with self.assertRaisesRegex(seq.SequenceError, 'No visible progress') as raised:
            seq.execute(self.backend, self.target, self.plan(), self.clock)
        self.assertEqual(raised.exception.report['completed_steps'], 0)
        self.assertTrue(raised.exception.report['steps'][0]['input_completed'])
        self.assertEqual(sum(e[1:4] == ('key', 'w', True) for e in self.backend.events), 1)
        self.assertEqual(self.backend.held, set())

    def test_watch_failure_interrupts_hold_and_releases_inputs(self):
        self.raw['steps'] = [{'keys': ['w'], 'seconds': 1, 'watch': ['closed'], 'expect_after': 'closed'}]
        self.backend.frame = lambda target: Image.new('RGB', self.backend.size,
                                                      'white' if self.clock.now >= 0.12 else 'black')
        with self.assertRaisesRegex(seq.SequenceError, 'During-action') as raised:
            seq.execute(self.backend, self.target, self.plan(), self.clock)
        self.assertLess(self.clock.now, 0.3)
        self.assertEqual(self.backend.held, set())
        self.assertFalse(raised.exception.report['steps'][0]['input_completed'])

    def test_watch_rejects_before_first_press_when_initial_state_changed(self):
        self.raw['steps'] = [{'keys': ['w'], 'watch': ['open'], 'expect_after': 'closed'}]
        with self.assertRaisesRegex(seq.SequenceError, 'During-action'):
            seq.execute(self.backend, self.target, self.plan(), self.clock)
        self.assertEqual(self.backend.events, [])

    def test_new_options_are_fully_validated_before_input(self):
        for changes in [{'repeat': 2}, {'repeat': 17}, {'repeat': True}, {'watch': ['missing']},
                        {'watch': 'closed'}, {'progress': {'regions': [[0, 0, 1281, 1]], 'min_mean_error': 1}},
                        {'progress': {'regions': [[0, 0, 1, 1]], 'min_mean_error': 0}}]:
            raw = copy.deepcopy(self.raw)
            raw['steps'][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                seq.prepare(raw, self.base)

    def test_bright_text_ignores_dim_background_but_detects_changed_glyph(self):
        before = Image.new('RGB', (20, 20), (30, 30, 30))
        after = Image.new('RGB', (20, 20), (186, 205, 244))
        before.paste((220, 220, 220), (2, 2, 5, 8))
        after.paste((220, 220, 220), (2, 2, 5, 8))
        check = {'reference': before, 'regions': [[0, 0, 20, 20]],
                 'mode': 'bright_text', 'max_mean_error': 0}
        self.assertTrue(seq.match_frame(after, check)[0])
        after.paste((220, 220, 220), (7, 2, 10, 8))
        self.assertFalse(seq.match_frame(after, check)[0])
    def test_repetitions_obey_expanded_count_and_total_time_limits(self):
        for count in [16, 2]:
            raw = copy.deepcopy(self.raw)
            raw['steps'] = [{'keys': ['w'], 'repeat': count, 'seconds': 1,
                             'expect_after': 'closed', 'progress': {'regions': [[0, 0, 1, 1]], 'min_mean_error': 1}}] * 3
            with self.subTest(count=count), self.assertRaises(ValueError):
                seq.prepare(raw, self.base)

    def test_red_mask_ignores_background_but_detects_lost_heart_pixels(self):
        before = Image.new('RGB', (20, 20), (40, 90, 40))
        after = Image.new('RGB', (20, 20), (90, 140, 80))
        before.paste((240, 40, 30), (4, 4, 10, 10))
        after.paste((240, 40, 30), (4, 4, 10, 10))
        check = {'reference': before, 'regions': [[0, 0, 20, 20]], 'mode': 'red_pixels', 'max_mean_error': 0}
        self.assertTrue(seq.match_frame(after, check)[0])
        after.paste((20, 20, 20), (4, 4, 7, 10))
        self.assertFalse(seq.match_frame(after, check)[0])


class SequenceWatchdogTests(unittest.TestCase):
    def test_per_step_lease_shortens_watchdog_wait(self):
        clock, reader = FakeClock(), Mock()
        reader.poll.side_effect = [True, False]
        reader.recv.return_value = {'deadline': 1.2}
        self.assertFalse(seq.await_watchdog(reader, 20, clock))
        self.assertEqual([call.args[0] for call in reader.poll.call_args_list], [20, 1.2])
        reader.close.assert_called_once()

    def test_clean_completion_and_eof(self):
        for message, success in [('released', True), ({'unexpected': True}, False)]:
            reader = Mock()
            reader.poll.return_value = True
            reader.recv.return_value = message
            self.assertEqual(seq.await_watchdog(reader, 20, FakeClock()), success)
        reader = Mock()
        reader.poll.side_effect = EOFError
        self.assertFalse(seq.await_watchdog(reader, 20, FakeClock()))

    def test_lease_cannot_extend_past_whole_sequence_deadline(self):
        reader = Mock()
        reader.poll.side_effect = [True, False]
        reader.recv.return_value = {'deadline': 1000}
        self.assertFalse(seq.await_watchdog(reader, 20, FakeClock()))
        self.assertEqual([call.args[0] for call in reader.poll.call_args_list], [20, 20])


if __name__ == '__main__':
    unittest.main()
