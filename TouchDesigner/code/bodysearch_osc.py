"""
Text DAT module: bodysearch_osc

Receives search results from `orest-search ... --send-td` and writes them into
the `results` Table DAT beside this module. The wire format is documented in
src/smartsearch/td.py:

	/orest/results/begin  <query_id> <count>
	/orest/results/hit    <query_id> <rank> <clip_path> <ts> <te> <score> <source_file> <preroll>
	/orest/results/end    <query_id>

Hits are appended as they arrive, since each is announced once its clip exists
and rank 1 is playable before the rest are cut.
"""

RESULTS_HEADER = ['rank', 'clip_path', 'ts', 'te', 'score', 'source', 'preroll']

# Id of the search whose hits the table holds. Hits of any other search are
# stragglers from an earlier query and are dropped.
_query_id = None


def handle(address, args):
	"""Route one OSC message. Returns True if the address belonged to this module."""
	global _query_id
	if not address.startswith('/orest/results/'):
		return False

	results = op('results')
	kind = address.rsplit('/', 1)[-1]

	if kind == 'begin':
		_query_id = args[0]
		results.clear()
		results.appendRow(RESULTS_HEADER)
	elif kind == 'hit':
		if args[0] != _query_id:
			return True
		results.appendRow(list(args[1:]))
	# 'end' marks that every clip of the search has arrived; nothing to do.
	return True
