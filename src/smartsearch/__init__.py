"""Smart Search: retrieval over the rehearsal corpus, built on WISE.

Implements the Smart Search affordance of knowledge/components/02_processing.md
and the SMART SEARCH node of knowledge/source_of_truth/pipeline.md. WISE builds
and serves the multimodal index; this package drives it — batch work through its
command line, retrieval through its HTTP API — and owns everything Apollon adds on
top.
"""
