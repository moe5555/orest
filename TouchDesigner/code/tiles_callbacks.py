"""
Replicator COMP callbacks: tiles_callbacks

Keeps the `wall` Layout TOP listing every tile, in the order of their numbers,
whenever the replicator adds or removes tiles. Listing by number keeps tile10
after tile9, so results stay in rank order across the grid.
"""


def onRemoveReplicant(comp, replicant):
	replicant.destroy()
	list_tiles(comp)
	return


def onReplicate(comp, allOps, newOps, template, master):
	list_tiles(comp)
	return


def list_tiles(comp):
	tiles = sorted((child for child in comp.children if child.digits is not None),
		key=lambda child: child.digits)
	op('wall').par.top = ' '.join(child.path + '/out1' for child in tiles)
