# Athene archive

The Seestone-branded prototypes of Athene, from 15 to 16 October 2026, before
Athene became an entity of her own (athene/description.md). The changelog
entries of those days describe each design.

- `description.md`: the brief they were made for: Athene as a Seestone
  program, an audioreactive sphere after the Palantir and the ElevenLabs orbs.
- `page/`: the page they were drawn on, with the Seestone mark and the name
  in Michroma, and the designs `futurist`, `painterly`, `planetary`,
  `metallic` and `liquid`.
- `moodboard_*`, `moodboad_digital`: the moodboards.
- `out/`: their renders (ignored by git, like athene/out).

An archived design is still rendered with the current renderer:

    python -m athene.render CLIP --archive --design metallic --still 20
