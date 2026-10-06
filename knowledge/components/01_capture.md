# Data Capture

Overview: components/pipeline.md

During rehearsals, audiovisual data will be captured. Specifics of sync camera and audio capture TBD. 

The data of one camera will be streamed into "Apollon" for real-time processing for the SITREP. All data from cameras and mics (including the SITREP one) will be saved onto e.g. SD cards, time-synced, and then saved to the computer for processing. 

## Streaming 
TEMPORARY: we will build the system to work with webcam data for now.

check 02_processing.md for processing of streamed data.

## Saving
TODO: unified file naming. For now, we will use test data that I will point to that doesn't follow any particular file naming convention. 

## Hardware
- Microphones (ASK Tonkids)
- Cameras (ASK Nils)
  
## Software
- TODO: what is the most effective way of recording all this data in sync? 
- TODO: file naming standard
- TODO: database structure
- TODO: Perhaps a tool that allows a human to annotate exact timestamps with a tag during rehearsal? 

## Anticipating Issues
- capturing third-party individuals? e.g. technicians, AMA, etc. -> perhaps one full-room setup, one stage setup that we can easily switch between
- explicit team-consent?

---

> **⚠ Written by Claude (2026-09-17), not yet reviewed by Moe.**

### Camera framing affects body search

The camera used for live body queries should frame bodies the way the archive
camera does — ideally the same camera and the same shot.

Consequences for the rehearsal setup:

- A live query from a differently framed camera is pulled toward whichever
  archive material happens to match that framing.
- A switch between a full-room setup and a stage setup, as considered above,
  splits the archive into two framings; a live query then favours the half that
  matches the camera it came from.
- Whole bodies in frame carry the most movement information, since no keypoints
  are lost.

> **⚠ End of Claude-written section.**
