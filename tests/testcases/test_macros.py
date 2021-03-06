#!/usr/bin/python3
# -*- coding: utf-8 -*-
# key-mapper - GUI for device specific keyboard mappings
# Copyright (C) 2021 sezanzeb <proxima@sezanzeb.de>
#
# This file is part of key-mapper.
#
# key-mapper is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# key-mapper is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with key-mapper.  If not, see <https://www.gnu.org/licenses/>.


import time
import unittest
import asyncio
import multiprocessing
import sys

from evdev.ecodes import EV_REL, EV_KEY, REL_Y, REL_X, REL_WHEEL, REL_HWHEEL

from keymapper.injection.macros import parse, _Macro, _extract_params, \
    is_this_a_macro, _parse_recurse, handle_plus_syntax, _count_brackets
from keymapper.config import config
from keymapper.mapping import Mapping
from keymapper.state import system_mapping

from tests.test import quick_cleanup


class TestMacros(unittest.TestCase):
    def setUp(self):
        self.result = []
        self.loop = asyncio.get_event_loop()
        self.mapping = Mapping()

    def tearDown(self):
        self.result = []
        self.mapping.clear_config()
        quick_cleanup()

    def handler(self, ev_type, code, value):
        """Where macros should write codes to."""
        print(f'\033[90mmacro wrote{(ev_type, code, value)}\033[0m')
        self.result.append((ev_type, code, value))

    def test_is_this_a_macro(self):
        self.assertTrue(is_this_a_macro('k(1)'))
        self.assertTrue(is_this_a_macro('k(1).k(2)'))
        self.assertTrue(is_this_a_macro('r(1, k(1).k(2))'))

        self.assertFalse(is_this_a_macro('1'))
        self.assertFalse(is_this_a_macro('key_kp1'))
        self.assertFalse(is_this_a_macro('btn_left'))
        self.assertFalse(is_this_a_macro('minus'))
        self.assertFalse(is_this_a_macro('k'))
        self.assertFalse(is_this_a_macro(1))
        self.assertFalse(is_this_a_macro(None))

        self.assertTrue(is_this_a_macro('a+b'))
        self.assertTrue(is_this_a_macro('a+b+c'))
        self.assertTrue(is_this_a_macro('a + b'))
        self.assertTrue(is_this_a_macro('a + b + c'))

    def test_handle_plus_syntax(self):
        self.assertEqual(handle_plus_syntax('a + b'), 'm(a,m(b,h()))')
        self.assertEqual(handle_plus_syntax('a + b + c'), 'm(a,m(b,m(c,h())))')
        self.assertEqual(handle_plus_syntax(' a+b+c '), 'm(a,m(b,m(c,h())))')

        # invalid
        self.assertEqual(handle_plus_syntax('+'), '+')
        self.assertEqual(handle_plus_syntax('a+'), 'a+')
        self.assertEqual(handle_plus_syntax('+b'), '+b')
        self.assertEqual(handle_plus_syntax('k(a + b)'), 'k(a + b)')
        self.assertEqual(handle_plus_syntax('a'), 'a')
        self.assertEqual(handle_plus_syntax('k(a)'), 'k(a)')
        self.assertEqual(handle_plus_syntax(''), '')

    def test_run_plus_syntax(self):
        macro = parse('a + b + c + d', self.mapping)
        self.assertSetEqual(macro.get_capabilities()[EV_KEY], {
            system_mapping.get('a'),
            system_mapping.get('b'),
            system_mapping.get('c'),
            system_mapping.get('d')
        })

        macro.press_key()
        asyncio.ensure_future(macro.run(self.handler))
        self.loop.run_until_complete(asyncio.sleep(0.2))
        self.assertTrue(macro.is_holding())

        # starting from the left, presses each one down
        self.assertEqual(self.result[0], (EV_KEY, system_mapping.get('a'), 1))
        self.assertEqual(self.result[1], (EV_KEY, system_mapping.get('b'), 1))
        self.assertEqual(self.result[2], (EV_KEY, system_mapping.get('c'), 1))
        self.assertEqual(self.result[3], (EV_KEY, system_mapping.get('d'), 1))

        # and then releases starting with the previously pressed key
        macro.release_key()
        self.loop.run_until_complete(asyncio.sleep(0.2))
        self.assertFalse(macro.is_holding())
        self.assertEqual(self.result[4], (EV_KEY, system_mapping.get('d'), 0))
        self.assertEqual(self.result[5], (EV_KEY, system_mapping.get('c'), 0))
        self.assertEqual(self.result[6], (EV_KEY, system_mapping.get('b'), 0))
        self.assertEqual(self.result[7], (EV_KEY, system_mapping.get('a'), 0))

    def test_extract_params(self):
        def expect(raw, expectation):
            self.assertListEqual(_extract_params(raw), expectation)

        expect('a', ['a'])
        expect('a,b', ['a', 'b'])
        expect('a,b,c', ['a', 'b', 'c'])

        expect('k(a)', ['k(a)'])
        expect('k(a).k(b), k(a)', ['k(a).k(b)', 'k(a)'])
        expect('k(a), k(a).k(b)', ['k(a)', 'k(a).k(b)'])

        expect('r(1, k(a))', ['r(1, k(a))'])
        expect('r(1, k(a)), r(1, k(b))', ['r(1, k(a))', 'r(1, k(b))'])
        expect(
            'r(1, k(a)), r(1, k(b)), r(1, k(c))',
            ['r(1, k(a))', 'r(1, k(b))', 'r(1, k(c))']
        )

        expect('', [''])
        expect(',', ['', ''])
        expect(',,', ['', '', ''])

    def test_fails(self):
        self.assertIsNone(parse('r(1, a)', self.mapping))
        self.assertIsNone(parse('r(a, k(b))', self.mapping))
        self.assertIsNone(parse('m(a, b)', self.mapping))

    def test_parse_params(self):
        self.assertEqual(_parse_recurse('', self.mapping), None)
        self.assertEqual(_parse_recurse('5', self.mapping), 5)
        self.assertEqual(_parse_recurse('foo', self.mapping), 'foo')

    def test_0(self):
        macro = parse('k(1)', self.mapping)
        one_code = system_mapping.get('1')
        self.assertSetEqual(macro.get_capabilities()[EV_KEY], {one_code})
        self.assertSetEqual(macro.get_capabilities()[EV_REL], set())

        self.loop.run_until_complete(macro.run(self.handler))
        self.assertListEqual(self.result, [(EV_KEY, one_code, 1), (EV_KEY, one_code, 0)])
        self.assertEqual(len(macro.child_macros), 0)

    def test_1(self):
        # quotation marks are removed automatically and don't do any harm
        macro = parse('k(1).k("a").k(3)', self.mapping)
        self.assertSetEqual(macro.get_capabilities()[EV_KEY], {
            system_mapping.get('1'),
            system_mapping.get('a'),
            system_mapping.get('3')
        })

        self.loop.run_until_complete(macro.run(self.handler))
        self.assertListEqual(self.result, [
            (EV_KEY, system_mapping.get('1'), 1), (EV_KEY, system_mapping.get('1'), 0),
            (EV_KEY, system_mapping.get('a'), 1), (EV_KEY, system_mapping.get('a'), 0),
            (EV_KEY, system_mapping.get('3'), 1), (EV_KEY, system_mapping.get('3'), 0),
        ])
        self.assertEqual(len(macro.child_macros), 0)

    def test_return_errors(self):
        error = parse('k(1).h(k(a)).k(3)', self.mapping, return_errors=True)
        self.assertIsNone(error)
        error = parse('k(1))', self.mapping, return_errors=True)
        self.assertIn('bracket', error)
        error = parse('k((1)', self.mapping, return_errors=True)
        self.assertIn('bracket', error)
        error = parse('k((1).k)', self.mapping, return_errors=True)
        self.assertIsNotNone(error)
        error = parse('r(a, k(1))', self.mapping, return_errors=True)
        self.assertIsNotNone(error)
        error = parse('k()', self.mapping, return_errors=True)
        self.assertIsNotNone(error)
        error = parse('k(1)', self.mapping, return_errors=True)
        self.assertIsNone(error)
        error = parse('k(1, 1)', self.mapping, return_errors=True)
        self.assertIsNotNone(error)
        error = parse('h(1, 1)', self.mapping, return_errors=True)
        self.assertIsNotNone(error)
        error = parse('h(h(h(1, 1)))', self.mapping, return_errors=True)
        self.assertIsNotNone(error)
        error = parse('r(1)', self.mapping, return_errors=True)
        self.assertIsNotNone(error)
        error = parse('r(1, 1)', self.mapping, return_errors=True)
        self.assertIsNotNone(error)
        error = parse('r(k(1), 1)', self.mapping, return_errors=True)
        self.assertIsNotNone(error)
        error = parse('r(1, k(1))', self.mapping, return_errors=True)
        self.assertIsNone(error)
        error = parse('m(asdf, k(a))', self.mapping, return_errors=True)
        self.assertIsNotNone(error)
        error = parse('foo(a)', self.mapping, return_errors=True)
        self.assertIn('unknown', error.lower())
        self.assertIn('foo', error)

    def test_hold(self):
        # repeats k(a) as long as the key is held down
        macro = parse('k(1).h(k(a)).k(3)', self.mapping)
        self.assertSetEqual(macro.get_capabilities()[EV_KEY], {
            system_mapping.get('1'),
            system_mapping.get('a'),
            system_mapping.get('3')
        })

        """down"""

        macro.press_key()
        self.loop.run_until_complete(asyncio.sleep(0.05))
        self.assertTrue(macro.is_holding())

        macro.press_key()  # redundantly calling doesn't break anything
        asyncio.ensure_future(macro.run(self.handler))
        self.loop.run_until_complete(asyncio.sleep(0.2))
        self.assertTrue(macro.is_holding())
        self.assertGreater(len(self.result), 2)

        """up"""

        macro.release_key()
        self.loop.run_until_complete(asyncio.sleep(0.05))
        self.assertFalse(macro.is_holding())

        self.assertEqual(self.result[0], (EV_KEY, system_mapping.get('1'), 1))
        self.assertEqual(self.result[-1], (EV_KEY, system_mapping.get('3'), 0))

        code_a = system_mapping.get('a')
        self.assertGreater(self.result.count((EV_KEY, code_a, 1)), 2)

        self.assertEqual(len(macro.child_macros), 1)

    def test_dont_hold(self):
        macro = parse('k(1).h(k(a)).k(3)', self.mapping)
        self.assertSetEqual(macro.get_capabilities()[EV_KEY], {
            system_mapping.get('1'),
            system_mapping.get('a'),
            system_mapping.get('3')
        })

        asyncio.ensure_future(macro.run(self.handler))
        self.loop.run_until_complete(asyncio.sleep(0.2))
        self.assertFalse(macro.is_holding())
        # press_key was never called, so the macro completes right away
        # and the child macro of hold is never called.
        self.assertEqual(len(self.result), 4)

        self.assertEqual(self.result[0], (EV_KEY, system_mapping.get('1'), 1))
        self.assertEqual(self.result[-1], (EV_KEY, system_mapping.get('3'), 0))

        self.assertEqual(len(macro.child_macros), 1)

    def test_just_hold(self):
        macro = parse('k(1).h().k(3)', self.mapping)
        self.assertSetEqual(macro.get_capabilities()[EV_KEY], {
            system_mapping.get('1'),
            system_mapping.get('3')
        })

        """down"""

        macro.press_key()
        asyncio.ensure_future(macro.run(self.handler))
        self.loop.run_until_complete(asyncio.sleep(0.1))
        self.assertTrue(macro.is_holding())
        self.assertEqual(len(self.result), 2)
        self.loop.run_until_complete(asyncio.sleep(0.1))
        # doesn't do fancy stuff, is blocking until the release
        self.assertEqual(len(self.result), 2)

        """up"""

        macro.release_key()
        self.loop.run_until_complete(asyncio.sleep(0.05))
        self.assertFalse(macro.is_holding())
        self.assertEqual(len(self.result), 4)

        self.assertEqual(self.result[0], (EV_KEY, system_mapping.get('1'), 1))
        self.assertEqual(self.result[-1], (EV_KEY, system_mapping.get('3'), 0))

        self.assertEqual(len(macro.child_macros), 0)

    def test_dont_just_hold(self):
        macro = parse('k(1).h().k(3)', self.mapping)
        self.assertSetEqual(macro.get_capabilities()[EV_KEY], {
            system_mapping.get('1'),
            system_mapping.get('3')
        })

        asyncio.ensure_future(macro.run(self.handler))
        self.loop.run_until_complete(asyncio.sleep(0.1))
        self.assertFalse(macro.is_holding())
        # since press_key was never called it just does the macro
        # completely
        self.assertEqual(len(self.result), 4)

        self.assertEqual(self.result[0], (EV_KEY, system_mapping.get('1'), 1))
        self.assertEqual(self.result[-1], (EV_KEY, system_mapping.get('3'), 0))

        self.assertEqual(len(macro.child_macros), 0)

    def test_hold_down(self):
        # writes down and waits for the up event until the key is released
        macro = parse('h(a)', self.mapping)
        self.assertSetEqual(macro.get_capabilities()[EV_KEY], {
            system_mapping.get('a'),
        })
        self.assertEqual(len(macro.child_macros), 0)

        """down"""

        macro.press_key()
        self.loop.run_until_complete(asyncio.sleep(0.05))
        self.assertTrue(macro.is_holding())

        asyncio.ensure_future(macro.run(self.handler))
        macro.press_key()  # redundantly calling doesn't break anything
        self.loop.run_until_complete(asyncio.sleep(0.2))
        self.assertTrue(macro.is_holding())
        self.assertEqual(len(self.result), 1)
        self.assertEqual(self.result[0], (EV_KEY, system_mapping.get('a'), 1))

        """up"""

        macro.release_key()
        self.loop.run_until_complete(asyncio.sleep(0.05))
        self.assertFalse(macro.is_holding())

        self.assertEqual(len(self.result), 2)
        self.assertEqual(self.result[0], (EV_KEY, system_mapping.get('a'), 1))
        self.assertEqual(self.result[1], (EV_KEY, system_mapping.get('a'), 0))

    def test_2(self):
        start = time.time()
        repeats = 20

        macro = parse(f'r({repeats}, k(k)).r(1, k(k))', self.mapping)
        k_code = system_mapping.get('k')
        self.assertSetEqual(macro.get_capabilities()[EV_KEY], {k_code})

        self.loop.run_until_complete(macro.run(self.handler))
        keystroke_sleep = self.mapping.get('macros.keystroke_sleep_ms')
        sleep_time = 2 * repeats * keystroke_sleep / 1000
        self.assertGreater(time.time() - start, sleep_time * 0.9)
        self.assertLess(time.time() - start, sleep_time * 1.1)

        self.assertListEqual(
            self.result,
            [(EV_KEY, k_code, 1), (EV_KEY, k_code, 0)] * (repeats + 1)
        )

        self.assertEqual(len(macro.child_macros), 2)
        self.assertEqual(len(macro.child_macros[0].child_macros), 0)

    def test_3(self):
        start = time.time()
        macro = parse('r(3, k(m).w(100))', self.mapping)
        m_code = system_mapping.get('m')
        self.assertSetEqual(macro.get_capabilities()[EV_KEY], {m_code})
        self.loop.run_until_complete(macro.run(self.handler))

        keystroke_time = 6 * self.mapping.get('macros.keystroke_sleep_ms')
        total_time = keystroke_time + 300
        total_time /= 1000

        self.assertGreater(time.time() - start, total_time * 0.9)
        self.assertLess(time.time() - start, total_time * 1.1)
        self.assertListEqual(self.result, [
            (EV_KEY, m_code, 1), (EV_KEY, m_code, 0),
            (EV_KEY, m_code, 1), (EV_KEY, m_code, 0),
            (EV_KEY, m_code, 1), (EV_KEY, m_code, 0),
        ])
        self.assertEqual(len(macro.child_macros), 1)
        self.assertEqual(len(macro.child_macros[0].child_macros), 0)

    def test_4(self):
        macro = parse('  r(2,\nk(\nr ).k(minus\n )).k(m)  ', self.mapping)

        r = system_mapping.get('r')
        minus = system_mapping.get('minus')
        m = system_mapping.get('m')

        self.assertSetEqual(macro.get_capabilities()[EV_KEY], {r, minus, m})

        self.loop.run_until_complete(macro.run(self.handler))
        self.assertListEqual(self.result, [
            (EV_KEY, r, 1), (EV_KEY, r, 0),
            (EV_KEY, minus, 1), (EV_KEY, minus, 0),
            (EV_KEY, r, 1), (EV_KEY, r, 0),
            (EV_KEY, minus, 1), (EV_KEY, minus, 0),
            (EV_KEY, m, 1), (EV_KEY, m, 0),
        ])
        self.assertEqual(len(macro.child_macros), 1)
        self.assertEqual(len(macro.child_macros[0].child_macros), 0)

    def test_5(self):
        start = time.time()
        macro = parse('w(200).r(2,m(w,\nr(2,\tk(BtN_LeFt))).w(10).k(k))', self.mapping)

        self.assertEqual(len(macro.child_macros), 1)
        self.assertEqual(len(macro.child_macros[0].child_macros), 1)

        w = system_mapping.get('w')
        left = system_mapping.get('bTn_lEfT')
        k = system_mapping.get('k')

        self.assertSetEqual(macro.get_capabilities()[EV_KEY], {w, left, k})

        self.loop.run_until_complete(macro.run(self.handler))

        num_pauses = 8 + 6 + 4
        keystroke_time = num_pauses * self.mapping.get('macros.keystroke_sleep_ms')
        wait_time = 220
        total_time = (keystroke_time + wait_time) / 1000

        self.assertLess(time.time() - start, total_time * 1.1)
        self.assertGreater(time.time() - start, total_time * 0.9)
        expected = [(EV_KEY, w, 1)]
        expected += [(EV_KEY, left, 1), (EV_KEY, left, 0)] * 2
        expected += [(EV_KEY, w, 0)]
        expected += [(EV_KEY, k, 1), (EV_KEY, k, 0)]
        expected *= 2
        self.assertListEqual(self.result, expected)

    def test_6(self):
        # does nothing without .run
        macro = parse('k(a).r(3, k(b))', self.mapping)
        self.assertIsInstance(macro, _Macro)
        self.assertListEqual(self.result, [])

    def test_keystroke_sleep_config(self):
        # global config as fallback
        config.set('macros.keystroke_sleep_ms', 100)
        start = time.time()
        macro = parse('k(a).k(b)', self.mapping)
        self.loop.run_until_complete(macro.run(self.handler))
        delta = time.time() - start
        # is currently over 400, k(b) adds another sleep afterwards
        # that doesn't do anything
        self.assertGreater(delta, 0.300)

        # now set the value in the mapping, which is prioritized
        self.mapping.set('macros.keystroke_sleep_ms', 50)
        start = time.time()
        macro = parse('k(a).k(b)', self.mapping)
        self.loop.run_until_complete(macro.run(self.handler))
        delta = time.time() - start
        self.assertGreater(delta, 0.150)
        self.assertLess(delta, 0.300)

    def test_duplicate_run(self):
        # it won't restart the macro, because that may screw up the
        # internal state (in particular the _holding_lock).
        # I actually don't know at all what kind of bugs that might produce,
        # lets just avoid it. It might cause it to be held down forever.
        a = system_mapping.get('a')
        b = system_mapping.get('b')
        c = system_mapping.get('c')

        macro = parse('k(a).m(b, h()).k(c)', self.mapping)
        asyncio.ensure_future(macro.run(self.handler))
        self.assertFalse(macro.is_holding())

        asyncio.ensure_future(macro.run(self.handler))  # ignored
        self.assertFalse(macro.is_holding())

        macro.press_key()
        self.loop.run_until_complete(asyncio.sleep(0.2))
        self.assertTrue(macro.is_holding())

        asyncio.ensure_future(macro.run(self.handler))  # ignored
        self.assertTrue(macro.is_holding())

        macro.release_key()
        self.loop.run_until_complete(asyncio.sleep(0.2))
        self.assertFalse(macro.is_holding())

        expected = [
            (EV_KEY, a, 1), (EV_KEY, a, 0),
            (EV_KEY, b, 1), (EV_KEY, b, 0),
            (EV_KEY, c, 1), (EV_KEY, c, 0),
        ]
        self.assertListEqual(self.result, expected)

        """not ignored, since previous run is over"""

        asyncio.ensure_future(macro.run(self.handler))
        macro.press_key()
        self.loop.run_until_complete(asyncio.sleep(0.2))
        self.assertTrue(macro.is_holding())
        macro.release_key()
        self.loop.run_until_complete(asyncio.sleep(0.2))
        self.assertFalse(macro.is_holding())

        expected = [
            (EV_KEY, a, 1), (EV_KEY, a, 0),
            (EV_KEY, b, 1), (EV_KEY, b, 0),
            (EV_KEY, c, 1), (EV_KEY, c, 0),
        ] * 2
        self.assertListEqual(self.result, expected)

    def test_mouse(self):
        macro_1 = parse('mouse(up, 4)', self.mapping)
        macro_2 = parse('wheel(left, 3)', self.mapping)
        macro_1.press_key()
        macro_2.press_key()
        asyncio.ensure_future(macro_1.run(self.handler))
        asyncio.ensure_future(macro_2.run(self.handler))
        self.loop.run_until_complete(asyncio.sleep(0.1))
        self.assertTrue(macro_1.is_holding())
        self.assertTrue(macro_2.is_holding())
        macro_1.release_key()
        macro_2.release_key()

        self.assertIn((EV_REL, REL_Y, -4), self.result)
        self.assertIn((EV_REL, REL_HWHEEL, 1), self.result)

        self.assertIn(REL_WHEEL, macro_1.get_capabilities()[EV_REL])
        self.assertIn(REL_Y, macro_1.get_capabilities()[EV_REL])
        self.assertIn(REL_X, macro_1.get_capabilities()[EV_REL])

        self.assertIn(REL_WHEEL, macro_2.get_capabilities()[EV_REL])
        self.assertIn(REL_Y, macro_2.get_capabilities()[EV_REL])
        self.assertIn(REL_X, macro_2.get_capabilities()[EV_REL])

    def test_event_1(self):
        macro = parse('e(EV_KEY, KEY_A, 1)', self.mapping)
        a_code = system_mapping.get('a')
        self.assertSetEqual(macro.get_capabilities()[EV_KEY], {a_code})
        self.assertSetEqual(macro.get_capabilities()[EV_REL], set())

        self.loop.run_until_complete(macro.run(self.handler))
        self.assertListEqual(self.result, [(EV_KEY, a_code, 1)])
        self.assertEqual(len(macro.child_macros), 0)

    def test_event_2(self):
        macro = parse('r(1, e(5421, 324, 154))', self.mapping)
        code = 324
        self.assertSetEqual(macro.get_capabilities()[5421], {324})
        self.assertSetEqual(macro.get_capabilities()[EV_REL], set())
        self.assertSetEqual(macro.get_capabilities()[EV_KEY], set())

        self.loop.run_until_complete(macro.run(self.handler))
        self.assertListEqual(self.result, [(5421, code, 154)])
        self.assertEqual(len(macro.child_macros), 1)

    def test_ifeq_runs(self):
        macro = parse('set(foo, 2).ifeq(foo, 2, k(a), k(b))', self.mapping)
        code_a = system_mapping.get('a')
        code_b = system_mapping.get('b')
        self.assertSetEqual(macro.get_capabilities()[EV_KEY], {code_a, code_b})
        self.assertSetEqual(macro.get_capabilities()[EV_REL], set())

        self.loop.run_until_complete(macro.run(self.handler))
        self.assertListEqual(self.result, [
            (EV_KEY, code_a, 1),
            (EV_KEY, code_a, 0)
        ])
        self.assertEqual(len(macro.child_macros), 2)

    def test_ifeq_unknown_key(self):
        macro = parse('ifeq(qux, 2, k(a), k(b))', self.mapping)
        code_a = system_mapping.get('a')
        code_b = system_mapping.get('b')
        self.assertSetEqual(macro.get_capabilities()[EV_KEY], {code_a, code_b})
        self.assertSetEqual(macro.get_capabilities()[EV_REL], set())

        self.loop.run_until_complete(macro.run(self.handler))
        self.assertListEqual(self.result, [
            (EV_KEY, code_b, 1),
            (EV_KEY, code_b, 0)
        ])
        self.assertEqual(len(macro.child_macros), 2)

    def test_ifeq_runs_multiprocessed(self):
        macro = parse('ifeq(foo, 3, k(a), k(b))', self.mapping)
        code_a = system_mapping.get('a')
        code_b = system_mapping.get('b')

        self.assertSetEqual(macro.get_capabilities()[EV_KEY], {code_a, code_b})
        self.assertSetEqual(macro.get_capabilities()[EV_REL], set())
        self.assertEqual(len(macro.child_macros), 2)

        def set_foo(value):
            # will write foo = 2 into the shared dictionary of macros
            macro_2 = parse(f'set(foo, {value})', self.mapping)
            loop = asyncio.new_event_loop()
            loop.run_until_complete(macro_2.run(lambda: None))

        """foo is not 3"""

        process = multiprocessing.Process(target=set_foo, args=(2,))
        process.start()
        process.join()
        self.loop.run_until_complete(macro.run(self.handler))
        self.assertListEqual(self.result, [
            (EV_KEY, code_b, 1),
            (EV_KEY, code_b, 0)
        ])

        """foo is 3"""

        process = multiprocessing.Process(target=set_foo, args=(3,))
        process.start()
        process.join()
        self.loop.run_until_complete(macro.run(self.handler))
        self.assertListEqual(self.result, [
            (EV_KEY, code_b, 1),
            (EV_KEY, code_b, 0),
            (EV_KEY, code_a, 1),
            (EV_KEY, code_a, 0)
        ])

    def test_count_brackets(self):
        self.assertEqual(_count_brackets(''), 0)
        self.assertEqual(_count_brackets('()'), 2)
        self.assertEqual(_count_brackets('a()'), 3)
        self.assertEqual(_count_brackets('a(b)'), 4)
        self.assertEqual(_count_brackets('a(b())'), 6)
        self.assertEqual(_count_brackets('a(b(c))'), 7)
        self.assertEqual(_count_brackets('a(b(c))d'), 7)
        self.assertEqual(_count_brackets('a(b(c))d()'), 7)


if __name__ == '__main__':
    unittest.main()
