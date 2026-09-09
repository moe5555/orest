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
- write log file, but not necessary to time-sync with footage. Choice moments can be extracted if desired.  
- prioritises low latency over accuracy 

Implementation Steps: 
1. Install Gemma-4b and deploy via Ollama
2. Set up capture loop - select video and audio source (for now we'll be testing with webcam + laptop mic)
3. Capture one frame every x seconds
4. Transcribe everything that is said, speaker diarisation eventually. 
5. Write SITREP report JSON format.
6. Every x seconds, prompt a SITREP report. X is dependent on latency - do a p95, p99 test and make sure that the system only processes as many seconds as it can keep up with. e.g. if it takes 40 seconds to process a range of 30 seconds, that will cause increasing delay. 
7. Output: video output (for testing, eventually this will be handled perhaps via TouchDesigner) and SITREP text beneath it. 

#### Example SITREP 

Implemented in `src/sitrep/report.py`. Deutsch, knapp, Behördenstil. Ollama erhält das Schema als Grammatik, die Antwort ist daher immer gültiges JSON.

`zeitfenster` und `quelle` werden aus dem Capture-Window übernommen, nicht vom Modell erzeugt — das Modell kann sie nicht verifizieren, und jedes generierte Token kostet Latenz. Bewertungen 0–5.

```json
{
  "zeitfenster": { "beginn": "2026-09-09T14:20:35", "ende": "2026-09-09T14:21:05", "dauer_s": 30 },
  "quelle": { "bilder": 3, "ton": "142035.wav" },
  "lage": "Zwei Personen auf der Probebühne, Gespräch über Szenenablauf.",
  "personen": [
    {
      "kennung": "P-01",
      "merkmale": "männlich, dunkle Jacke, Brille",
      "taetigkeit": "steht mittig, gestikuliert",
      "verantwortungsvoll": 3,
      "menschlich": 4,
      "gefahr": 0,
      "kollaborativ": 4
    }
  ],
  "ereignisse": ["P-02 tritt von links auf", "gemeinsame Betrachtung eines Textbuchs"],
  "gesagt": "Nochmal von vorne, ab dem Einsatz.",
  "prognose": "Wiederholung der Szene zu erwarten.",
  "empfehlung": "Keine.",
  "vertrauen": 4,
  "latenz_s": 12.4
}
```

**Halluzination:** Das Modell erfindet bei reinem Raumton Inhalte (beobachtet: „Wind in den Blättern, Vogelzwitschern, Plätschern von Wasser" bei einer Aufnahme ohne Sprache). Der Prompt verbietet Spekulation explizit und lässt `gesagt` leer, wenn keine Sprache zu hören ist. `vertrauen` ist die Selbsteinschätzung des Modells und entsprechend vorsichtig zu lesen.

#### Latenz & Fenstergröße (Schritt 6)

Gemessen mit `src/sitrep/benchmark.py` auf RTX 4070 Laptop / 8GB, `gemma4:e4b`, 10 Läufe pro Konfiguration. Details und Tabelle: changelog.md, Eintrag 2026-09-09.

- **Latenz ist nahezu unabhängig von der Fenstergröße** (p95 4,4 s bei 10 s-Fenster bis 7,6 s bei 60 s-Fenster). Alle getesteten Konfigurationen halten Schritt.
- Da die Generierung das nächste Fenster blockiert, entspricht die **Lücke zwischen zwei Fenstern der Latenz**. Abdeckung = W/(W+Latenz): 65 % bei 15 s, 83 % bei 30 s. **Längere Fenster sind für die Abdeckung besser** — X ist damit eine Frage der gewünschten Berichtsfrequenz, nicht der Rechenzeit.
- **Audiolänge darf nicht auf einer 30-Sekunden-Grenze enden** (Encoder arbeitet in 30 s-Blöcken, sonst `Failed to tokenize prompt`). `capture.clip_for_encoder()` schneidet entsprechend zu.

### Smart Search 
**data_in**: rehearsal corpus <br>
**data_out**: segments or frames, either saved or streamed directly into TouchDesigner via OSC 

This feature builds on WISE (https://github.com/ox-vgg/wise) and is an interface for searching through rehearsal footage. 

#### Wise Integration 
WISE will be used to create a multi-modal embedding of all surveillance footage. Functionality: 
- Batch process rehearsal footage from folder on computer 
- Conduct WISE search on custom material via WISE's built-in front end (localhost)
- Conduct WISE search on custom material and display results on TouchDesigner via OSC 
- All other features of WISE should be usable via command-line. Essential will be the introduction of custom feature extractors, covering transcribed audio -> text, pose estimation, certain ephermeral embeddings tbd. 
  
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
