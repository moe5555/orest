"""Body-pose retrieval for Orest: the same encoder on both sides of a search.

Implements the "body" half of embodied search in
knowledge/components/02_processing.md, where a captured live sequence becomes
the query and the corpus answers with segments that match it.

Neither CLIP nor Qwen3-VL encodes kinematics — they retrieve an event at
scene-semantic granularity, not a configuration of limbs
(knowledge/background/wise_clip_as_query.md). A separate keypoint index is
therefore the only route to matching on the body itself, rather than the
cheapest one.

The package is installed into both Python environments. WISE's environment
imports `extractor` to build the index; Orest's imports `model` and `keypoints`
to encode a live clip into the same space, and submits the result to WISE's
/search_with_feature endpoint. Keeping one implementation of the embedding is
the point: a query encoded even slightly differently from the index retrieves
nothing useful.
"""

from .keypoints import (  # noqa: F401
    COCO_KEYPOINTS,
    FRAMES_PER_SEGMENT,
    segment_embedding,
)

# Feature extractor id, as WISE addresses it. Four slash-separated parts are
# required: the id is split to dispatch the factory and is reused verbatim as a
# path under the project's store directory.
EXTRACTOR_ID = "orest/pose/rtmo-s/body7"

__all__ = ["COCO_KEYPOINTS", "EXTRACTOR_ID", "FRAMES_PER_SEGMENT", "segment_embedding"]
