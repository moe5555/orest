"""
Text DAT module: sitrep_osc

Receives the live SITREP and the presence roster from `apollon-sitrep --send-td`
and writes them into Table DATs beside this module. The wire format is
documented in src/sitrep/td.py.

A report arrives only when the operator asks for one (R). The live values,
lines, recommendations and the Chronik arrive as they happen.

Rows are buffered until their `end` message and written in one step, so a
table never shows half of one report and half of the previous. The report id
and the roster tick tell one reading's rows from the next.

Tables written (sibling DATs of this module); a table that does not exist is
skipped:
	sitrep_meta        one row: time frame, source, latency, development,
	                   description, transcript, scene ratings, recommendation
	sitrep_personen    one row per person in the report
	sitrep_prognose    the three forecasts, most likely first
	sitrep_text        the report as plain text, for a Text TOP
	presence_meta      one row: tick, time, number present
	presence           one row per person the tracker sees
	live_meta          one row: tick, time, people, alarm and its cause
	live_personen      one row per person: live risiko and menschlichkeit
	live_zeilen        the last LIVE_ZEILEN lines said, newest last
	live_empfehlung    one row: the latest recommendation
	chronik            the last CHRONIK_ZEILEN summarised stretches, newest last

Report names are drawn from the presence roster of the report's window, so a
name in sitrep_personen is a label in presence. The model reads which person
carries which name from tags drawn over the faces in its frames.
"""

META_HEADER = ['id', 'nummer', 'beginn', 'ende', 'dauer_s', 'bilder', 'abschnitte',
			   'latenz_s', 'personen', 'prognosen', 'verlauf',
			   'beschreibung', 'gesagt', 'relevanz', 'eskalation', 'gefahr',
			   'einschreiten', 'massnahme']

# Rating columns follow report.BEWERTUNGEN in Apollon, in the same order.
# risiko and menschlichkeit are -1 when the action recogniser read nothing of
# the person.
PERSON_HEADER = ['zeile', 'name', 'vermutet', 'beschreibung',
				 'risiko', 'menschlichkeit', 'auffaelligkeit']

PROGNOSE_HEADER = ['rang', 'wahrscheinlichkeit', 'verlauf']

# Name Apollon gives a person in frame whom face tracking did not follow.
UNBEKANNT = 'Unbekannt'

PRESENCE_META_HEADER = ['tick', 'zeit', 'anwesend']

PRESENCE_HEADER = ['zeile', 'label', 'name', 'vermutet', 'aehnlichkeit',
				   'sichtungen', 'seit', 'dauer_s']

LIVE_META_HEADER = ['tick', 'zeit', 'personen', 'alarm', 'alarm_wert', 'alarm_wer',
					'alarm_anlass']

LIVE_PERSON_HEADER = ['zeile', 'name', 'risiko', 'menschlichkeit', 'anlass_risiko',
					  'anlass_menschlichkeit']

ZEILE_HEADER = ['beginn', 'ende', 'name', 'text', 'lautstaerke', 'risiko', 'menschlichkeit',
				'bewertet']

EMPFEHLUNG_HEADER = ['nummer', 'zeit', 'einschreiten', 'eskalation', 'gefahr', 'lage',
					 'massnahme', 'anlass', 'latenz_s']

CHRONIK_HEADER = ['beginn', 'ende', 'eskalation', 'gefahr', 'tendenz', 'zusammenfassung']

# Rows kept in the tables that grow: lines said, and summarised stretches.
LIVE_ZEILEN = 20
CHRONIK_ZEILEN = 20

# A tick this far below the last one shown means apollon-sitrep restarted and
# its first reading was lost, rather than a reading that arrived late.
TICK_RESTART = 10

# Readings in progress, keyed by report id or roster tick. Module globals are
# reset when this DAT is edited, which only drops readings still in flight.
_reports = {}
_rosters = {}
_last_tick = 0
_live = {}
_last_live = 0


def handle(address, args):
	"""Route one OSC message. Returns True if the address belonged to this module."""
	if address.startswith('/apollon/sitrep/'):
		_sitrep(address.rsplit('/', 1)[-1], list(args))
		return True
	if address.startswith('/apollon/presence/'):
		_presence(address.rsplit('/', 1)[-1], list(args))
		return True
	if address.startswith('/apollon/live/'):
		_live_message(address.rsplit('/', 1)[-1], list(args))
		return True
	if address == '/apollon/chronik/abschnitt':
		_append('chronik', CHRONIK_HEADER, list(args), CHRONIK_ZEILEN)
		return True
	return False


def _sitrep(kind, args):
	if kind == 'begin':
		# Only the newest report is of interest; anything older still pending
		# lost its end message and is dropped.
		_reports.clear()
		_reports[args[0]] = {'begin': args[1:], 'verlauf': '', 'beschreibung': '', 'gesagt': '',
							 'personen': [], 'szene': [0, 0, 0], 'prognose': [],
							 'empfehlung': [0, '']}
		return

	report = _reports.get(args[0])
	if report is None:
		# Rows of a report whose begin was missed, e.g. TouchDesigner started
		# mid-report. The next report arrives within one window.
		return

	if kind == 'verlauf':
		report['verlauf'] = args[1]
	elif kind == 'beschreibung':
		report['beschreibung'] = args[1]
	elif kind == 'gesagt':
		report['gesagt'] = args[1]
	elif kind == 'person':
		report['personen'].append(args[1:])
	elif kind == 'szene':
		report['szene'] = args[1:]
	elif kind == 'prognose':
		report['prognose'].append(args[1:])
	elif kind == 'empfehlung':
		report['empfehlung'] = args[1:]
	elif kind == 'end':
		_write_report(args[0], _reports.pop(args[0]))


def _write_report(report_id, report):
	meta = [report_id, *report['begin'], report['verlauf'], report['beschreibung'], report['gesagt'],
			*report['szene'], *report['empfehlung']]
	_fill('sitrep_meta', META_HEADER, [meta])
	_fill('sitrep_personen', PERSON_HEADER, report['personen'])
	_fill('sitrep_prognose', PROGNOSE_HEADER, report['prognose'])

	text = op('sitrep_text')
	if text is not None:
		text.text = _as_text(report)


def _as_text(report):
	"""The report laid out for reading beneath the video."""
	nummer, beginn, ende = report['begin'][0], report['begin'][1], report['begin'][2]
	latenz = report['begin'][6]

	lines = ['SITREP {}   {} - {}   Latenz {:.1f} s'.format(
				 nummer, beginn[-8:], ende[-8:], float(latenz)),
			 '',
			 'VERLAUF       {}'.format(report['verlauf']),
			 'BESCHREIBUNG  {}'.format(report['beschreibung'])]
	for zeile, name, vermutet, beschreibung, *ratings in report['personen']:
		if int(vermutet) and name != UNBEKANNT:
			name = '{} (vermutet)'.format(name)
		lines.append('PERSON        {} - {}   [{}]'.format(
			name, beschreibung, ' '.join('-' if int(r) < 0 else str(r) for r in ratings)))
	relevanz, eskalation, gefahr = report['szene']
	lines.append('SZENE         relevanz {} . eskalation {} . gefahr {}'.format(
		relevanz, eskalation, gefahr))
	if report['gesagt']:
		lines.append('GESAGT        {}'.format(report['gesagt']))
	for rang, wahrscheinlichkeit, verlauf in report['prognose']:
		lines.append('PROGNOSE {:>3} % {}'.format(wahrscheinlichkeit, verlauf))
	einschreiten, massnahme = report['empfehlung']
	lines.append('EMPFEHLUNG    {}'.format(
		'EINSCHREITEN: {}'.format(massnahme) if int(einschreiten) else 'Kein Einschreiten'))
	return '\n'.join(lines)


def _presence(kind, args):
	global _last_tick
	tick = int(args[0])

	if kind == 'begin':
		_rosters[tick] = {'begin': args[1:], 'personen': []}
		return

	roster = _rosters.get(tick)
	if roster is None:
		return

	if kind == 'person':
		roster['personen'].append(args[1:])
	elif kind == 'end':
		del _rosters[tick]
		# Tick 1 always opens a run, so it is shown even after a higher tick.
		if 1 < tick <= _last_tick and tick > _last_tick - TICK_RESTART:
			# A reading older than the one on screen.
			return
		_last_tick = tick
		# Readings older than this one can no longer be shown.
		for pending in [t for t in _rosters if t < tick]:
			del _rosters[pending]
		_fill('presence_meta', PRESENCE_META_HEADER, [[tick, *roster['begin']]])
		_fill('presence', PRESENCE_HEADER, roster['personen'])


def _live_message(kind, args):
	"""The live values, framed like the roster; lines and recommendations singly."""
	global _last_live
	if kind == 'zeile':
		# A line arrives as transcribed, then again once rated: the rating
		# takes the row of the line it belongs to.
		table = op('live_zeilen')
		if table is not None:
			for row in range(1, table.numRows):
				if table[row, 'beginn'].val == args[0] and table[row, 'text'].val == args[3]:
					table.replaceRow(row, args)
					return
		_append('live_zeilen', ZEILE_HEADER, args, LIVE_ZEILEN)
		return
	if kind == 'empfehlung':
		_fill('live_empfehlung', EMPFEHLUNG_HEADER, [args], quiet=True)
		return

	tick = int(args[0])
	if kind == 'begin':
		_live[tick] = {'begin': args, 'personen': []}
		return
	reading = _live.get(tick)
	if reading is None:
		return
	if kind == 'person':
		reading['personen'].append(args[1:])
	elif kind == 'end':
		del _live[tick]
		# A reading older than the one shown, unless Apollon restarted.
		if 1 < tick <= _last_live and tick > _last_live - TICK_RESTART:
			return
		_last_live = tick
		for pending in [t for t in _live if t < tick]:
			del _live[pending]
		_fill('live_meta', LIVE_META_HEADER, [reading['begin']], quiet=True)
		_fill('live_personen', LIVE_PERSON_HEADER, reading['personen'], quiet=True)


def _append(name, header, row, keep):
	"""Add a row to a table, keeping its header and the last `keep` rows."""
	table = op(name)
	if table is None:
		return
	if table.numRows == 0:
		table.appendRow(header)
	table.appendRow(row)
	while table.numRows > keep + 1:
		table.deleteRow(1)


def _fill(name, header, rows, quiet=False):
	"""Replace a table's contents with a header and rows.

	A missing table is reported, unless `quiet`: the live tables are optional
	and update twice a second."""
	table = op(name)
	if table is None:
		if not quiet:
			debug('sitrep_osc: no Table DAT named {}'.format(name))
		return
	table.clear()
	table.appendRow(header)
	for row in rows:
		table.appendRow(row)
