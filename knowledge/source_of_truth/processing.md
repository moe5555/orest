# Data Processing 

## Wise Integration 
WISE will be used to create a multi-modal embedding of all surveillance footage. Functionality: 
- Batch process rehearsal footage from folder on computer 
- Conduct WISE search on custom material via WISE's built-in front end (localhost)
- Conduct WISE search on custom material and display results on TouchDesigner via OSC 
- All other features of WISE should be usable via command-line. Essential will be the introduction of custom feature extractors, covering transcribed audio -> text, pose estimation, certain ephermeral embeddings tbd. 
  
BONUS very-nice-to-have: If we get to it, a localhost that allows us to conduct WISE search within a front-end "Orest" localhost used for the show. Functionality that diverges from WISE's localhost: 
- Results (segments or frames) are piped into TouchDesigner via OSC 
- Image search input from a selection of the team members/actors 
- Live video search: actors are recorded during performance/rehearsal, and the operator can do a WISE search from an extracted frame/clip in real-time. e.g. actor strikes pose X -> WISE search returns moments the actor did pose X in the rehearsal footage. Actor says "Hello World" -> WISE search returns footage where the actor said "Hello World" 