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
  - categories per person: verantwortungsvoll, menschlich, gefahr, kollaborativ, relevanz
  - prediction of what might happen next. 
  - whether to interfere, if so, what to do. 
- prioritises low latency over accuracy 

Implementation Steps: 
1. Install Gemma-4b and deploy via Ollama
2. Set up capture loop - select video and audio source (for now we'll be testing with webcam + laptop mic)
3. Capture one frame every x seconds
4. Transcribe everything that is said, speaker diarisation eventually. 
5. Write SITREP report JSON format.
6. Every x seconds, prompt a SITREP report. X is dependent on latency - do a p95, p99 test and make sure that the system only processes as many seconds as it can keep up with. e.g. if it takes 40 seconds to process a range of 30 seconds, that will cause increasing delay. 
7. Output: video output (for testing, eventually this will be handled perhaps via TouchDesigner) and SITREP text beneath it. 

#### Calculating Values
How do we calculate the values the system comes up with? 

- *Sentiment Analysis*: feed the transcript into Gemma and ask it to score the person's values (gefahr, kollaborativ, etc.) - to do this, we need to implement speaker diarisation. 
- *Pose*: 

### Smart Search 
**data_in**: rehearsal corpus <br>
**data_out**: segments or frames, either saved or streamed directly into TouchDesigner via OSC 

This feature builds on WISE (https://github.com/ox-vgg/wise) and is an interface for searching through rehearsal footage. 

#### Wise Integration 
WISE will be used to create a multi-modal embedding of all surveillance footage. Functionality: 
- Process rehearsal footage from folder on computer 
- Feature embedding that WISE offers out of the box
- Custom retrieval pipeline
  - embodied search: 
    - body: conduct WISE search with a video segment. e.g. a 5 second video of an actor falling to their knees returns segments that match. During the performance, I should be able to press a button, then press a button again after a few seconds to capture that live sequence and then that gets used to do the retrieval. This is custom behaviour we need to figure out how to do.   
    - audio (speech): Actor says a line, line gets piped into WISE, live. e.g. Actor says "Hello World" -> WISE search returns footage where the actor said "Hello World" WISE currently cannot search for tone of voice - nice to have.   
  

#### Hindsight-SITREP 
**data_in**: time-stamped rehearsal footage <br>
**data_out**: time-stamped SITREP report as concise metadata 

Hindsight-SITREP runs over all the data once its recorded and writes metadata, tags, etc. and timestamps them to the corresponding clips. Create a database (e.g. SQLite) that maps metadata to corresponding footage. 

#### UI for Rehearsals & Performances
A localhost with following features: 
- Conduct WISE search via text, static image, and/or from frames from a live camera input
- Conduct Hindsight search via text
- Conduct hybrid search: select from WISE then of those select from Hindsight, or vice versa. e.g. "person running" in WISE, "is considered a threat" in Hindsight -> select top WISE results for person running, then sort those by Hindsight's threat metric 
- Results are piped into TouchDesigner  
