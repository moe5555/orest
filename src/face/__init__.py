"""Face detection, embedding and cast enrolment.

The identity half of the Realtime-SITREP's "who is in the scene"
(knowledge/components/02_processing.md): a cast member is enrolled from a few
photographs, and a face seen during a rehearsal is matched against that
enrolment. The input is the live camera stream, so nothing here reads a file
except the enrolment images themselves.
"""
