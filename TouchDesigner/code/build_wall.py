"""
Textport script: builds the body search video wall in /project1/bodysearch.

	exec(open(project.folder + '/code/build_wall.py').read())

Creates, or updates if they exist:

	Tiles        custom parameter on bodysearch, 1-99 tiles on the wall
	tile         master player: Movie File In TOP `movie` -> Out TOP `out1`
	tiles        Replicator COMP making one copy of `tile` per tile
	wall         Layout TOP arranging the tiles in a grid
	wall_window  Window COMP showing `wall` full screen, set as Perform Window
	keys         Keyboard In DAT: space captures, digits set the tile count
	wall_keys    its callbacks, synced from code/wall_keys.py

A tile plays the result whose rank is its position among the tiles, read from
the `results` table that bodysearch_osc fills. Safe to run again.
"""

BODYSEARCH = '/project1/bodysearch'
DEFAULT_TILES = 4
# Two digit keys, so at most 99.
MAX_TILES = 99

# Size of the wall and the monitor it opens on (0 is the primary display).
RESOLUTION = (1920, 1080)
DISPLAY = 0


def _menu(par, *candidates, required=True):
	"""Set a menu parameter by its label: the first candidate whose words all
	appear in a label, ignoring case. Menu tokens are not documented, labels are."""
	labels = list(par.menuLabels)
	for words in candidates:
		for index, label in enumerate(labels):
			if all(word in label.lower() for word in words):
				par.menuIndex = index
				return
	message = '{}: none of {} among {}'.format(par.name, candidates, labels)
	if required:
		raise ValueError(par.owner.path + '.' + message)
	print('build_wall: left unchanged, ' + message)


def _expr(par, expression):
	par.expr = expression
	par.mode = ParMode.EXPRESSION


def _child(comp, op_type, name, x, y):
	existing = comp.op(name)
	node = existing if existing is not None else comp.create(op_type, name)
	node.nodeX, node.nodeY = x, y
	return node


def _custom_page(comp, name):
	for page in comp.customPages:
		if page.name == name:
			return page
	return comp.appendCustomPage(name)


bodysearch = op(BODYSEARCH)
bodysearch.par.parentshortcut = 'bodysearch'
x = max(child.nodeX for child in bodysearch.children) + 300

if not hasattr(bodysearch.par, 'Tiles'):
	_custom_page(bodysearch, 'Wall').appendInt('Tiles', label='Tiles')
	bodysearch.par.Tiles.val = DEFAULT_TILES
tiles_par = bodysearch.par.Tiles
tiles_par.default = DEFAULT_TILES
tiles_par.min, tiles_par.max = 1, MAX_TILES
tiles_par.normMin, tiles_par.normMax = 1, MAX_TILES
tiles_par.clampMin = tiles_par.clampMax = True

# Master player. Its copies sit inside `tiles` and take their rank from their
# order there, which holds whether the replicator numbers them from 0 or 1.
# The master itself has no number and plays nothing.
tile = _child(bodysearch, baseCOMP, 'tile', x, 0)
if not hasattr(tile.par, 'Rank'):
	_custom_page(tile, 'Tile').appendInt('Rank', label='Rank')
_expr(tile.par.Rank,
	"sorted(c.digits for c in me.parent().children if c.digits is not None and c.name.startswith('tile'))"
	".index(me.digits) + 1 if me.digits is not None else 0")

movie = _child(tile, moviefileinTOP, 'movie', 0, 0)
_expr(movie.par.file,
	"parent.bodysearch.op('results')[parent().par.Rank.eval(), 'clip_path'].val "
	"if 0 < parent().par.Rank.eval() < parent.bodysearch.op('results').numRows else ''")
_menu(movie.par.playmode, ('sequential',))
_menu(movie.par.textendright, ('cycle',), ('loop',))
# Waiting for the first frame of a new clip keeps the old one on screen until
# it is ready, rather than showing a skipped, black frame.
movie.par.alwaysloadinitial = True
out = _child(tile, outTOP, 'out1', 200, 0)
out.inputConnectors[0].connect(movie)

# Max Columns of ceil(sqrt(n)): 1 -> 1x1, 2 -> 2x1, 3-4 -> 2x2, 5-6 -> 3x2,
# 7-9 -> 3x3, 10-12 -> 4x3, 13-16 -> 4x4.
# The list of tiles is written by the replicator's callbacks
# (code/tiles_callbacks.py) whenever tiles are added or removed.
wall = _child(bodysearch, layoutTOP, 'wall', x + 200, -150)
wall.par.top.mode = ParMode.CONSTANT

tiles_callbacks = _child(bodysearch, textDAT, 'tiles_callbacks', x, -450)
tiles_callbacks.par.file = 'code/tiles_callbacks.py'
tiles_callbacks.text = open(project.folder + '/code/tiles_callbacks.py').read()
tiles_callbacks.par.syncfile = True

tiles = _child(bodysearch, replicatorCOMP, 'tiles', x, -150)
_menu(tiles.par.method, ('number',))
_expr(tiles.par.numreplicants, 'parent().par.Tiles')
tiles.par.master = tile
tiles.par.destination = '.'
tiles.par.opprefix = 'tile'
tiles.par.callbacks = tiles_callbacks
tiles_callbacks.module.list_tiles(tiles)
_menu(wall.par.align, ('grid', 'row'), ('horizontal',))
_expr(wall.par.maxcols, 'int(parent().par.Tiles.eval() ** 0.5 + 0.999)')
_menu(wall.par.fit, ('best',), ('inside',), required=False)
_menu(wall.par.outputresolution, ('custom',))
wall.par.resolutionw, wall.par.resolutionh = RESOLUTION
if hasattr(wall.par, 'bgcolora'):
	wall.par.bgcolorr = wall.par.bgcolorg = wall.par.bgcolorb = 0
	wall.par.bgcolora = 1

window = _child(bodysearch, windowCOMP, 'wall_window', x + 400, -150)
window.par.winop = wall
window.par.borders = False
window.par.display = DISPLAY
_menu(window.par.justifyoffsetto, ('single',), ('monitor',), required=False)
_menu(window.par.size, ('custom',))
window.par.winw, window.par.winh = RESOLUTION
window.par.closeescape = True
window.par.setperform.pulse()

callbacks = _child(bodysearch, textDAT, 'wall_keys', x, -300)
callbacks.par.file = 'code/wall_keys.py'
callbacks.text = open(project.folder + '/code/wall_keys.py').read()
callbacks.par.syncfile = True

keys = _child(bodysearch, keyboardinDAT, 'keys', x + 200, -300)
keys.par.keys = 'space 0 1 2 3 4 5 6 7 8 9'
# Keys are read only in the Perform Window, so space in the network editor
# (where it pans) cannot start a capture.
keys.par.perform = True
keys.par.callbacks = callbacks

print('build_wall: {} tiles, F1 opens the wall, Esc closes it'.format(int(bodysearch.par.Tiles)))
