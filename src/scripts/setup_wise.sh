#!/usr/bin/env bash
# scripts/setup_wise.sh
set -euo pipefail
WISE_SHA="fcfa443fbb46eb361bb19151339338616838a5b5"

git clone https://github.com/ox-vgg/wise.git external/wise
cd external/wise && git checkout "$WISE_SHA" 
python -m venv .venv
.venv/bin/pip install -r requirements.txt