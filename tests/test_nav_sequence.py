# SPDX-License-Identifier: GPL-2.0-or-later
"""Z8_NAV_SEQUENCE/Z8_NAV_INTERVAL parse and reject before the run."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from nav_sequence import DEFAULT_INTERVAL, DEFAULT_SEQUENCE, interval, sequence


class NavSequence(unittest.TestCase):
    def test_unset_reproduces_the_builtin_walk(self):
        self.assertEqual(sequence({}), list(DEFAULT_SEQUENCE))
        self.assertEqual(sequence({}), [('ok-bank', 74), ('back-bank', 35),
                                        ('down-one', 37), ('ok-extended', 74),
                                        ('back-extended', 35),
                                        ('half-shutter', 7)])

    def test_custom_tokens_map_to_report_offsets(self):
        walk = sequence({'Z8_NAV_SEQUENCE': 'menu, left ,down,play'})
        self.assertEqual(walk, [('menu', 67), ('left', 35), ('down', 37),
                                ('play', 68)])

    def test_legacy_aliases_keep_the_builtin_keys(self):
        walk = sequence({'Z8_NAV_SEQUENCE': 'ok_bank,back_bank,down_one,'
                                            'ok_extended,back_extended'})
        self.assertEqual([offset for _, offset in walk],
                         [74, 35, 37, 74, 35])

    def test_explicitly_empty_sequence_skips_the_walk(self):
        self.assertEqual(sequence({'Z8_NAV_SEQUENCE': ''}), [])
        self.assertEqual(sequence({'Z8_NAV_SEQUENCE': ' , '}), [])

    def test_unknown_token_is_rejected_before_the_run(self):
        for bad in ('warp', 'menu,warp', 'MENU'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                sequence({'Z8_NAV_SEQUENCE': bad})

    def test_interval_default_and_fractional_values(self):
        self.assertEqual(interval({}), DEFAULT_INTERVAL)
        self.assertEqual(interval({}), 3.0)
        self.assertEqual(interval({'Z8_NAV_INTERVAL': '1.5'}), 1.5)

    def test_nonfinite_or_nonpositive_interval_is_rejected(self):
        for bad in ('nan', 'inf', '-inf', 'Infinity', '0', '-1',
                    'abc', ''):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                interval({'Z8_NAV_INTERVAL': bad})


if __name__ == '__main__':
    unittest.main()
