"""
Text DAT module: bodysearch_osc

Receives search results from `apollon-search ... --send-td` and writes them into
the `results` Table DAT beside this module. The wire format is documented in
src/smartsearch/td.py:

	/apollon/results/begin  <query_id> <count>
	/apollon/results/hit    <query_id> <rank> <clip_path> <ts> <te> <score> <source_file> <preroll>
	/apollon/results/end    <query_id>

Row n of `results` holds the result of rank n, and each player shows one row.
A new search replaces the previous one row by row: a hit overwrites its rank's
row as soon as its clip exists, so every player keeps looping its old clip
until its new one is ready. Rows the new search did not reach are removed at
its end.
"""

RESULTS_HEADER = ['rank', 'clip_path', 'ts', 'te', 'score', 'source', 'preroll']

# Id of the search whose hits the table receives. Hits of any other search are
# stragglers from an earlier query and are dropped.
_query_id = None

# Highest rank the current search has delivered.
_delivered = 0


def handle(address, args):
	"""Route one OSC message. Returns True if the address belonged to this module."""
	global _query_id, _delivered
	if not address.startswith('/apollon/results/'):
		return False

	results = op('results')
	kind = address.rsplit('/', 1)[-1]

	if kind == 'begin':
		_query_id = args[0]
		_delivered = 0
		if results.numRows == 0 or [cell.val for cell in results.row(0)] != RESULTS_HEADER:
			results.clear()
			results.appendRow(RESULTS_HEADER)
	elif args[0] != _query_id:
		return True
	elif kind == 'hit':
		rank = int(args[1])
		_place(results, rank, list(args[1:]))
		_delivered = max(_delivered, rank)
	elif kind == 'end':
		while results.numRows > _delivered + 1:
			results.deleteRow(results.numRows - 1)
	return True


def _place(results, rank, row):
	"""Write a result into row `rank`, padding with empty rows if one was lost."""
	while results.numRows < rank:
		results.appendRow([''] * len(RESULTS_HEADER))
	if results.numRows == rank:
		results.appendRow(row)
	else:
		results.replaceRow(rank, row)
