"""Recognising what people do: the Pose route of the SITREP's values.

knowledge/components/02_processing.md ("Calculating Values", Pose) asks for
activities such as hitting, running or hugging to be recognised and mapped to
the report's values. This package recognises them with a model trained by
others: ST-GCN on NTU RGB+D 120, exported to ONNX once, outside Orest
(src/scripts/export_ntu_stgcn.py).

    preprocess  MMAction2's test pipeline, reproduced in numpy
    model       the ONNX network and its 120 classes
    tracking    bodies followed from frame to frame
    recognizer  continuous pose, windows, pairs, and the readings they produce

Watch it run over a recording:

    python -m action --recording rehearsal.mp4 --start 120 --duration 60
"""
