# orest
"Orest" is the surveillance system that will be used in the production of Human in the Loop/Human on a Leash at Schauspiel Stuttgart December 2026.

## Setup 

### External Code: WISE 
WISE is not vendored in this repo. Clone it into folder `external/`:

    mkdir -p external
    git clone https://github.com/ox-vgg/wise.git external/wise
    cd external/wise && git checkout fcfa443fbb46eb361bb19151339338616838a5b5

Pinned version: fcfa443fbb46eb361bb19151339338616838a5b5 2026-08-06 (cloned 2026-08-29)
Install per external/wise/docs/Install.md, or `docker compose up`.
WISE serves on http://localhost:9670.

Follow Install.md from WISE, install via conda as described. Then: conda activate wise followed by wise --help to make sure it is up and running.
