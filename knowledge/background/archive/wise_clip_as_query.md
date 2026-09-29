# WISE: clip-as-query feasibility (state of upstream, Sept 2026)

Assessed against `ox-vgg/wise` @ `fcfa443` (2026-08-06), mirror of gitlab.com/vgg/wise/wise,
and the SIGIR '26 paper (arXiv:2602.12819).

## What WISE indexes

| Stream | Model | Unit |
|---|---|---|
| Visual (frames) | OpenCLIP, default `ViT-B-16-SigLIP2-512/webli` | one vector per frame, sampled ~2 fps |
| Visual (segments) | `hf/Qwen/Qwen3-VL-Embedding/{2B,8B}` | one vector per 8 s segment, 16 frames, 4 s overlap |
| Audio | Microsoft CLAP `2023/four-datasets` | ~4 s windows, 2 s overlap |
| Faces | InsightFace (`buffalo_l`) | per detected face |
| Objects | OWLv2 | per region |
| Metadata / ASR | text, FTS | per file or per timed segment |

Shot boundaries come from TransNetV2 as a **separate** project
(gitlab.com/vgg/wise/shot-detection), imported into `shots.db`. Retrieval hits are merged
into shots, so results arrive as playable `media/{id}#t=ts,te` ranges rather than stills.

## Query-by-example: what actually works

- **Image** → yes (`MediaQueryTerm.qtype="visual"`, upload/URL/internal vector id).
- **Image region** → yes (`bbox`, XYWH).
- **Audio file** → yes (`qtype="audio"`, one file only — `load_audio()` raises `NotImplementedError` on more).
- **Text ± media**, weighted vector arithmetic → yes (`text_queries_weight=2.0`, `negative_queries_weight=0.2`).
- **Video clip** → **no**. `MediaQueryTerm` declares `ts`/`te` and documents "if ts and te
  have the same value it uses a single frame, otherwise it's a video segment", but
  `EmbeddingService.embed()` never reads them: `qtype="visual"` goes straight to
  `load_image()` → `PIL.Image.open()`. A video file fails there. The API surface exists;
  the implementation does not.

## The gap is small

`Qwen3VLEmbeddingFeatureExtractor.extract_video_segment_features(frames: (N,C,H,W)) -> Features`
already exists and is called by `extract_features.py` via `VideoSegmentDataset`. It is not
reachable from any search path. Wiring clip-as-query = decode the query clip, sample 16
frames over 8 s, call that method, return the vector — one branch in
`src/wise/api/services/embedding/_embedding.py`.

Note that class sets `extract_image_features = None`, so a Qwen segment index is currently
searchable **by text only** (an image query raises `ModalityNotSupportedError`).

## Escape hatch, no patch required

`POST /search_with_feature` accepts a raw `VectorQueryTerm` (base64 float32 + shape) plus
`feature_extractor_id` and `search_in`, and runs it against that extractor's Faiss index.
Any embedding computed outside WISE can be queried through it, provided it lands in the
same space as the indexed vectors.

## What the models do and do not encode

- **Pose**: neither CLIP nor Qwen3-VL encodes kinematics. They retrieve the *event*
  ("someone collapsing") at scene-semantic granularity, not the *configuration of limbs*.
  Confirms the existing decision to keep pose in a separate keypoint-embedding index.
- **Intonation**: CLAP encodes acoustic-event semantics (shouting, music, applause); ASR
  encodes words. Neither carries prosody. Pitch/energy contour or a speech-embedding model
  in its own index is the route.

## Sources

- https://gitlab.com/vgg/wise/wise — `src/wise/api/services/embedding/_embedding.py`, `src/wise/api/common.py`, `src/wise/feature/hf_models.py`, `src/wise/feature/qwen3vl.py`, `docs/Shot-Detection.md`, `docs/Grammar-of-Audiovisual-Search.md`
- Sridhar, Lee, Pinto, Zisserman, Dutta. *WISE: A Multimodal Search Engine for Visual Scenes, Audio, Objects, Faces, Speech, and Metadata*. SIGIR '26. doi:10.1145/3805712.3808375