# Data Processing 

Overview: components/pipeline.md

## Affordances 

### Realtime-SITREP 
**data_in**: rehearsal stream <br>
**data_out**: SITREP text report, TODO  
 
- batch-process incoming video stream with Gemma-4 model 
- write SITREP report
  - who is in the scene (provide the system with images of each team member, perhaps their bio?)
  - what they are doing 
  - time frame covered
  - categories per person: verantwortungsvoll, menschlich, gefahr, kollaborativ
  - suggested action maybe, or prediction of what might happen next. 
- prioritises low latency over accuracy 

Implementation Steps: 
1. Install Gemma-4b and deploy via Ollama
2. Set up capture loop - select video and audio source (for now we'll be testing with webcam + laptop mic)
3. Capture one frame every x seconds
4. Transcribe everything that is said, speaker diarisation eventually. 
5. Write SITREP report JSON format.
6. Every x seconds, prompt a SITREP report. X is dependent on latency - do a p95, p99 test and make sure that the system only processes as many seconds as it can keep up with. e.g. if it takes 40 seconds to process a range of 30 seconds, that will cause increasing delay. 
7. Output: video output (for testing, eventually this will be handled perhaps via TouchDesigner) and SITREP text beneath it. 

### Smart Search 
**data_in**: rehearsal corpus <br>
**data_out**: segments or frames, either saved or streamed directly into TouchDesigner via OSC 

This feature builds on WISE (https://github.com/ox-vgg/wise) and is an interface for searching through rehearsal footage. 

#### Wise Integration 
WISE will be used to create a multi-modal embedding of all surveillance footage. Functionality: 
- Batch process rehearsal footage from folder on computer 
- Feature embedding that WISE offers out of the box
- Custom retrieval pipeline
  - embodied search: conduct WISE search with a video segment. For the play: I press a bu    
  
BONUS very-nice-to-have: If we get to it, a localhost that allows us to conduct WISE search within a front-end "Orest" localhost used for the show. Functionality that diverges from WISE's localhost: 
- Results (segments or frames) are piped into TouchDesigner via OSC 
- Image search input from a selection of the team members/actors 
- Live video search: actors are recorded during performance/rehearsal, and the operator can do a WISE search from an extracted frame/clip in real-time. e.g. actor strikes pose X -> WISE search returns moments the actor did pose X in the rehearsal footage. Actor says "Hello World" -> WISE search returns footage where the actor said "Hello World" 

#### Hindsight-SITREP 
**data_in**: time-stamped rehearsal footage <br>
**data_out**: time-stamped SITREP report as concise metadata 

Hindsight-SITREP runs over all the data once its recorded and writes metadata, tags, etc. and timestamps them to the corresponding clips. **TODO**: in WISE, metadata is publishable for a video clip. If e.g. one rehearsal corresponds to one metadata entry, then that won't be particularly helpful. Alternative: part of the pre-processing of the footage includes chunking the videos into e.g. 30 second segments that each receive metadata. 

## STEPS 

### Pre Processing


## Hardware
- PC to run local inference on 

## Software
- "smart" database existing between capture & processing. Features: annotation during collection, smart search. perhaps use this: [WISE](https://gitlab.com/vgg/wise/wise)
- profile actors (+ team?)
- compress data, optimising for footage to be used in the play. Current topic focus: teaching the AI to learn how to deal with conflicts by observing human conflict. 
- 

## Anticipating Issues 
- EU AI Act for stuff like face & emotion recognition etc. 
