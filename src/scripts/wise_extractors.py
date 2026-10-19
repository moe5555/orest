"""Print the feature extractors a WISE project holds, as JSON.

Smart Search adds new recordings to a project in one WISE run per extraction
pass (src/smartsearch/wise_cli.py), and the passes depend on which extractors
embed single frames and which embed segments. Only WISE's model registry knows
that, and the project's store is read the way WISE itself reads it, so this
runs with the WISE environment's Python:

    <wise env>/python src/scripts/wise_extractors.py PROJECT_DIR

Prints one entry per extractor and modality:

    [{"modality": "video", "id": "...", "segment_level": false}, ...]
"""

import argparse
import json
from pathlib import Path

from wise.data_models import ModalityType
from wise.feature.hf_models import is_segment_level_extractor
from wise.wise_project import WiseProject

# Modalities that hold embedded media; the project's assets also list metadata.
MEDIA_MODALITIES = (ModalityType.VIDEO, ModalityType.AUDIO, ModalityType.IMAGE)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project", type=Path, help="WISE project directory")
    args = parser.parse_args()

    assets = WiseProject(args.project).discover_assets()
    extractors = []
    for modality in MEDIA_MODALITIES:
        for feature_id in sorted(assets.get(modality, {})):
            extractors.append({
                "modality": modality.value,
                "id": feature_id,
                "segment_level": is_segment_level_extractor(feature_id),
            })
    print(json.dumps(extractors))


if __name__ == "__main__":
    main()
