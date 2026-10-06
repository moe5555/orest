"""
OSC In DAT callbacks: osc_in.tox

The one OSC In DAT on port 10000 receives everything Apollon sends. Each feature
component holds a module with `handle(address, args)`, which returns True for
the addresses it owns; this callback offers every message to each in turn.
The features share only this receiver and know nothing of one another.
"""

# Module DATs of the feature components, by absolute path.
HANDLERS = [
	'/project1/bodysearch/bodysearch_osc',  # /apollon/results/
	'/project1/sitrep/sitrep_osc',          # /apollon/sitrep/, /apollon/presence/
]


def onReceiveOSC(dat, rowIndex, message, byteData, timeStamp, address, args, peer):
	for path in HANDLERS:
		handler = op(path)
		if handler is None:
			# A feature component not loaded in this project.
			continue
		if handler.module.handle(address, args):
			return
	return
