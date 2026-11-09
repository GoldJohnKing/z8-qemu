# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Z8_NAV_SEQUENCE / Z8_NAV_INTERVAL parsing for the stream-tool walk.

Both values are validated here, before the run, so a misspelled token or
a nonfinite / nonpositive interval raises immediately instead of running
a silently shortened walk or stalling after the first key (nan and inf
are accepted by float() but never satisfy the next-key deadline).
"""
import math
import os

# Token -> byte offset in the 124-byte controller key report; the same
# offsets the built-in walk and the browser control panel (control.py)
# use. Legacy aliases keep spelling the built-in walk's keys.
TOKENS = dict(menu=67, left=35, right=34, up=36, down=37, ok=74,
              half_shutter=7, play=68,
              ok_bank=74, back_bank=35, down_one=37,
              ok_extended=74, back_extended=35)

DEFAULT_SEQUENCE = [('ok-bank', 74), ('back-bank', 35), ('down-one', 37),
                    ('ok-extended', 74), ('back-extended', 35),
                    ('half-shutter', 7)]
DEFAULT_INTERVAL = 3.0


def sequence(environ=None):
    """The walk's (label, offset) list: Z8_NAV_SEQUENCE when set (an
    explicitly empty value means no navigation inputs), the built-in
    six-key walk otherwise."""
    env = os.environ if environ is None else environ
    spec = env.get('Z8_NAV_SEQUENCE')
    if spec is None:
        return list(DEFAULT_SEQUENCE)
    tokens = [t.strip() for t in spec.split(',') if t.strip()]
    for token in tokens:
        if token not in TOKENS:
            raise ValueError('Unknown navigation token: ' + token +
                             ' (expected menu/left/right/up/down/ok/play/'
                             'half_shutter plus ok_bank/back_bank/down_one/'
                             'ok_extended/back_extended aliases)')
    return [(token, TOKENS[token]) for token in tokens]


def interval(environ=None):
    """Seconds between keys (virtual time); default 3, the previous fixed
    cadence. Only finite positive values pace a walk."""
    env = os.environ if environ is None else environ
    value = float(env.get('Z8_NAV_INTERVAL', str(DEFAULT_INTERVAL)))
    if not math.isfinite(value) or value <= 0:
        raise ValueError('Z8_NAV_INTERVAL must be a finite positive number '
                         'of virtual seconds')
    return value
