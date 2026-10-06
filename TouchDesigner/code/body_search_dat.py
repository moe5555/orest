"""
Panel Execute DAT

me - this DAT

panelValue - the PanelValue object that changed
prev - the previous value of the PanelValue object that changed

Make sure the corresponding toggle is enabled in the Panel Execute DAT.
"""

from typing import Any

def onOffToOn(panelValue: PanelValue):
	"""
	Called when a panel value changes from 0 to non-zero.
	"""
	op('oscout1').sendOSC('/apollon/body/start', [1])

def whileOn(panelValue: PanelValue):
	"""
	Called every frame while a panel value is non-zero.
	"""
	return

def onOnToOff(panelValue: PanelValue):
	"""
	Called when a panel value changes from non-zero to 0.
	"""
	op('oscout1').sendOSC('/apollon/body/stop', [1])

def whileOff(panelValue: PanelValue):
	"""
	Called every frame while a panel value is 0.
	"""
	return

def onValueChange(panelValue: PanelValue, prev: Any):
	"""
	Called when a panel value changes.
	
	Args:
		panelValue: The PanelValue object that changed
		prev: The previous value of the PanelValue object
	"""
	return
