"""
OSC In DAT Callbacks

me - this DAT

peer - a Peer object describing the originating message
  peer.close()    #close the connection
  peer.owner  #the operator to whom the peer belongs
  peer.address    #network address associated with the peer
  peer.port       #network port associated with the peer
"""

from typing import List, Any

def onReceiveOSC(dat, rowIndex, message, byteData, timeStamp, address, args, peer):
    results = op('results')

    if address == '/apollon/results/begin':
        # A new search: remember its id and start an empty list.
        dat.store('query_id', args[0])
        results.clear()
        results.appendRow(['rank', 'clip_path', 'ts', 'te', 'score', 'source', 'preroll'])

    elif address == '/apollon/results/hit':
        if args[0] != dat.fetch('query_id', None):
            return
        query_id, rank, clip_path, ts, te, score, source, preroll = args
        results.appendRow([rank, clip_path, ts, te, score, source, preroll])


    elif address == '/apollon/results/end':
        pass  # all clips of this search have arrived

    return
