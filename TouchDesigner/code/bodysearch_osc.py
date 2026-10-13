"""
Text DAT module: bodysearch_osc

Receives search results from `apollon-search ... --send-td` and writes them into
the `results` Table DAT beside this module. The wire format is documented in
src/smartsearch/td.py:

	/apollon/results/begin  <query_id> <count>
	/apollon/results/hit    <query_id> <rank> <clip_path> <ts> <te> <score> <source_file> <preroll>
	/apollon/results/end    <query_id>

Each player shows one row of `results`. A new search replaces the previous one
row by row: a hit overwrites its row as soon as its clip exists, so every player
keeps looping its old clip until its new one is ready. Rows the new search did
not reach are removed at its end.

Hits arrive best first, one per cut clip. With the video wall built (the
`Tiles` parameter on this component), the ranks on screen are written to the
first `Tiles` rows in an order shuffled for each search, so the tiles change in
random order rather than in reading order. The `rank` column keeps each row's
rank. Ranks beyond the tiles, and every rank without a wall, take row n for
rank n.
"""

import random

RESULTS_HEADER = ['rank', 'clip_path', 'ts', 'te', 'score', 'source', 'preroll']

# Id of the search whose hits the table receives. Hits of any other search are
# stragglers from an earlier query and are dropped.
_query_id = None

# Row of each rank on screen in the current search: rank 1 goes to _rows[0].
_rows = []

# Highest row the current search has written.
_delivered = 0


def handle(address, args):
	"""Route one OSC message. Returns True if the address belonged to this module."""
	global _query_id, _rows, _delivered
	if not address.startswith('/apollon/results/'):
		return False

	results = op('results')
	kind = address.rsplit('/', 1)[-1]

	if kind == 'begin':
		_query_id = args[0]
		_rows = shuffled_rows(_shown(int(args[1])))
		_delivered = 0
		if results.numRows == 0 or [cell.val for cell in results.row(0)] != RESULTS_HEADER:
			results.clear()
			results.appendRow(RESULTS_HEADER)
	elif args[0] != _query_id:
		return True
	elif kind == 'hit':
		rank = int(args[1])
		row = _rows[rank - 1] if rank <= len(_rows) else rank
		_place(results, row, list(args[1:]))
		_delivered = max(_delivered, row)
	elif kind == 'end':
		while results.numRows > _delivered + 1:
			results.deleteRow(results.numRows - 1)
	return True


def shuffled_rows(count):
	"""Rows 1 to `count` in random order."""
	rows = list(range(1, count + 1))
	random.shuffle(rows)
	return rows


def _shown(count):
	"""How many of a search's `count` results are on screen, and so shuffled:
	one per tile of the video wall, none without a wall."""
	tiles = getattr(parent().par, 'Tiles', None)
	return 0 if tiles is None else min(count, int(tiles.eval()))


def _place(results, row_index, row):
	"""Write a result into row `row_index`, adding empty rows ahead of it that
	the table does not have yet."""
	while results.numRows < row_index:
		results.appendRow([''] * len(RESULTS_HEADER))
	if results.numRows == row_index:
		results.appendRow(row)
	else:
		results.replaceRow(row_index, row)
