"""Speech transcription for the SITREP, via faster-whisper.

Implements step 4 of the Realtime-SITREP implementation steps in
knowledge/components/02_processing.md ("Transcribe everything that is said,
speaker diarisation eventually"). Diarisation is not yet implemented.

report.py gives the model this transcript instead of the recording and writes
it into the report verbatim, so speech in a SITREP is always what Whisper
heard rather than what the model inferred.

Whisper emits phantom text on silence and non-speech noise, which a rehearsal
room with long pauses presents constantly. The voice-activity filter drops
non-speech before decoding and is required for usable output.
"""

import functools
import io
import os
from pathlib import Path

import nvidia.cublas
from faster_whisper import WhisperModel

# large-v3-turbo decodes several times faster than large-v3 at close to its
# accuracy, and unlike the distil models it covers German. 02_processing.md
# asks the Realtime-SITREP to prioritise latency over accuracy.
MODEL = "large-v3-turbo"

COMPUTE_TYPE = "int8_float16"

# The production is at Schauspiel Stuttgart (README.md). Fixing the language
# skips detection, which is slower and unreliable on short or quiet clips.
LANGUAGE = "de"

# Greedy decoding. Beam search buys a small accuracy gain at a considerable
# cost in speed, against the latency-first requirement in 02_processing.md.
BEAM_SIZE = 1


def _add_cublas_to_path():
    """Make the cuBLAS wheel loadable before the first GPU model is built.

    CTranslate2 loads cuBLAS by name on first GPU use, but the pip wheel places
    it inside site-packages, which is not on the Windows DLL search path. Its
    loader searches PATH and ignores os.add_dll_directory(): with the latter it
    still fails with "cublas64_12.dll is not found".
    """
    binaries = Path(next(iter(nvidia.cublas.__path__))) / "bin"
    os.environ["PATH"] = str(binaries) + os.pathsep + os.environ["PATH"]


@functools.cache
def _model() -> WhisperModel:
    _add_cublas_to_path()
    return WhisperModel(MODEL, device="cuda", compute_type=COMPUTE_TYPE)


def transcribe(wav: bytes) -> str:
    """Transcribe a WAV clip; returns an empty string when nothing is said."""
    segments, _ = _model().transcribe(
        io.BytesIO(wav), language=LANGUAGE, beam_size=BEAM_SIZE, vad_filter=True)
    return " ".join(segment.text.strip() for segment in segments).strip()
