# Apollon - Pipeline

```mermaid
graph LR;
    P[Probebühne]:::stage --> C[1 · CAPTURE]:::mode;
    C --> DB[(Rehearsal Database)]:::store;
    DB --> PR[2 · PROCESSING]:::mode;
    PR --> DB;
    DB --> R[3 · RENDER]:::mode;
    R --> OUT[Material for the play]:::out;

    O((Apollon)):::apollon -.-> C;
    O -.-> PR;
    O -.-> R;

    classDef stage fill:#f5f0e6,stroke:#8a7a5c,color:#2b2b2b;
    classDef mode fill:#e8eef7,stroke:#3f6ea8,color:#12263a;
    classDef store fill:#eef7ee,stroke:#4a8a4a,color:#12331a;
    classDef apollon fill:#f7e8ee,stroke:#a83f6e,color:#3a1226;
    classDef out fill:#fff,stroke:#666,color:#222;
```

Apollon runs in three modes across the pipeline: **real-time** (capture), **offline** (processing) and **retrieval/generative** (render).

## [CAPTURE](capture.md)
Data capturing of rehearsals follows the AMAP principle: collect as much data as possible. 

```mermaid
graph TD;
    subgraph PB["Probebühne"]
        ACT["Actors / team / room"]:::stage;
    end

    ACT --> CAM["n × Cameras<br/>(video streams)"]:::sensor;
    ACT --> MIC["m × Microphones<br/>(audio streams)"]:::sensor;

    CLK["Clock reference<br/>(NTP / PTP)"]:::clock -.->|timestamps| SYNC;
    CAM --> SYNC["Synchronisation<br/>common timebase, shared timecode"]:::proc;
    MIC --> SYNC;

    SYNC --> REC["Recorder<br/>raw A/V + metadata"]:::proc;

    REC --> STORE[("Local storage<br/>rehearsal database")]:::store;

    STORE ==>|feeds| NEXT["2 · PROCESSING"]:::mode;

    classDef stage fill:#f5f0e6,stroke:#8a7a5c,color:#2b2b2b;
    classDef sensor fill:#fdf3e3,stroke:#c08a2e,color:#3a2a0a;
    classDef clock fill:#fff,stroke:#999,stroke-dasharray:3 3,color:#333;
    classDef proc fill:#e8eef7,stroke:#3f6ea8,color:#12263a;
    classDef apollon fill:#f7e8ee,stroke:#a83f6e,stroke-width:2px,color:#3a1226;
    classDef store fill:#eef7ee,stroke:#4a8a4a,color:#12331a;
    classDef out fill:#fff,stroke:#666,color:#222;
    classDef human fill:#f0f0f0,stroke:#777,color:#222;
    classDef mode fill:#e8eef7,stroke:#3f6ea8,stroke-dasharray:4 3,color:#12263a;
```


## [PROCESSING](processing.md)
Process the rehearsal data to gather intelligence on the room + its activities & participants

```mermaid
graph TD;
    STORE[("Rehearsal database<br/>raw A/V + live annotations")]:::store --> ORE["Apollon — processing mode<br/>batch processing"]:::apollon;

    ORE --> AV["AV analysis<br/>audio + video"]:::proc;

    AV --> EMB["Embeddings<br/>body / voice / scene"]:::idx;

    AV --> TAG["Tags & structure<br/>segments, actors, events, conflict markers"]:::idx;

    EMB --> IDX[("Search index<br/>e.g. WISE")]:::store;
    TAG --> IDX;

    ORE --> COMP["Compression / curation<br/>keep what is usable in the play"]:::proc;
    COMP --> IDX;

    HITL["Human in the loop<br/>review & correct"]:::human --> TAG;

    IDX ==>|feeds| NEXT["3 · RENDER"]:::mode;

    classDef store fill:#eef7ee,stroke:#4a8a4a,color:#12331a;
    classDef apollon fill:#f7e8ee,stroke:#a83f6e,stroke-width:2px,color:#3a1226;
    classDef proc fill:#e8eef7,stroke:#3f6ea8,color:#12263a;
    classDef idx fill:#eaf3fb,stroke:#5a86b5,color:#12263a;
    classDef human fill:#f0f0f0,stroke:#777,color:#222;
    classDef gate fill:#fdeaea,stroke:#b03a3a,color:#3a1212;
    classDef mode fill:#e8eef7,stroke:#3f6ea8,stroke-dasharray:4 3,color:#12263a;
```


## [RENDER](render.md)
Get material back out of the database — by tag, by body, or by generating something new.

```mermaid
graph TD;
    subgraph Q["Query — how you ask"]
        QT["Tags / text<br/>'conflict', 'actor X', date, scene"]:::q;
        QB["BODY SEARCH<br/>actor performs live:<br/>body pose + voice as the query"]:::q;
    end

    QT --> SS["SMART SEARCH<br/>Apollon — retrieval mode"]:::apollon;
    QB --> ENC["Live encoder<br/>pose + voice → embedding"]:::proc;
    ENC --> SS;

    IDX[("Search index<br/>embeddings + tags")]:::store --> SS;

    SS --> HITS["Ranked moments<br/>most similar rehearsal footage"]:::out;
    HITS --> CUT["Extracted footage<br/>clips for the play"]:::out;

    CUT --> STAGE["Playback on stage / in rehearsal"]:::stage;

    classDef q fill:#fdf3e3,stroke:#c08a2e,color:#3a2a0a;
    classDef apollon fill:#f7e8ee,stroke:#a83f6e,stroke-width:2px,color:#3a1226;
    classDef proc fill:#e8eef7,stroke:#3f6ea8,color:#12263a;
    classDef store fill:#eef7ee,stroke:#4a8a4a,color:#12331a;
    classDef out fill:#fff,stroke:#666,color:#222;
    classDef opt fill:#f7f7f7,stroke:#999,stroke-dasharray:4 3,color:#444;
    classDef stage fill:#f5f0e6,stroke:#8a7a5c,color:#2b2b2b;
```





