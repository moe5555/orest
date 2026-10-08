"""
Keyboard In DAT callbacks: wall_keys

Keyboard control of the body search video wall:

	space   held: captures a movement; released: stops the capture and searches
	0-9     number of tiles on the wall, set when the last digit key is released.
	        Digits pressed while another is held add a digit: hold 1, press 6,
	        release both for 16.

Space sends the same messages as button1 through oscout1, to
`apollon-search body-live` on port 10001. Key repeat while space is held sends
further starts, which body-live ignores during a capture.
"""

import time

DIGITS = '0123456789'

# A digit pressed this long after the previous one starts a new entry. Without
# it, a release lost while the keyboard focus changed would leave a digit held
# for good and block every later entry.
ENTRY_TIMEOUT = 5.0

# Digit keys currently down, the digits typed since the first went down, and
# when the last digit was pressed.
_held = set()
_typed = []
_last_press = float('-inf')


def onKey(dat, key, character, alt, lAlt, rAlt, ctrl, lCtrl, rCtrl, shift, lShift, rShift, state, time, cmd, lCmd, rCmd):
	if key == 'space':
		address = '/apollon/body/start' if state else '/apollon/body/stop'
		op('oscout1').sendOSC(address, [1])
	elif len(key) == 1 and key in DIGITS:
		_digit(key, state)
	return


def _digit(key, down):
	"""Collect digits while any digit key is held; set the tile count on release."""
	global _last_press
	if down:
		now = time.monotonic()
		if now - _last_press > ENTRY_TIMEOUT:
			_held.clear()
			_typed.clear()
		_last_press = now
		# Key repeat reports a held key as pressed again; it adds no digit but
		# keeps the entry from timing out.
		if key not in _held:
			_held.add(key)
			_typed.append(key)
		return
	_held.discard(key)
	if _held or not _typed:
		return
	number = int(''.join(_typed))
	_typed.clear()
	if number > 0:
		parent().par.Tiles = number


def onShortcut(dat, shortcutName, time):
	return
