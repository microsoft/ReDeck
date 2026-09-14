# ReDeck research overview video

This Remotion project contains the source for one public video: an 84-second
English-narrated overview with burned-in English captions.

## Video Content

The d181, d120 and d171 case studies replay recorded repair trajectories. Labels identify
actions, rollbacks and accepted states from those runs.

The separate opening d78 comparison uses an injected-defect input and a manually post-edited
final; see [example details](../demo/repair_pairs/README.md). The bundled MP4 and poster retain
the older “Verified slide” label; the source labels identify the manual edit.

Scores refer to the [paper experiments](../demo/tech.html#results). The DeckQuiz dataset and
evaluation harness mentioned in the closing narration are not bundled with this release.

## Build

```bash
npm install
npm run build
```

The build writes `../demo/assets/redeck-demo.mp4` at 1920×1168. It preserves the
native 1920×1080 picture with a 16 px top bar and a 72 px caption bar. Burned-in
English captions use 36 px type.

## Preview

```bash
npm run dev
```

The only composition is `ReDeckDemo`.

## Narration

The committed narration assets live in `public/narration-v6/`. To regenerate them with
Fun-CosyVoice3, set `COSYVOICE_ROOT` to its checkout and `COSYVOICE_PYTHON` to its interpreter, then run:

```bash
npm run narration:generate
```

The music credit and modification notice are in
`public/audio/INSPIRED_LICENSE.md`.
The reference-voice metadata identifies synthetic Microsoft Edge TTS audio. Check the service's
reuse terms separately before redistributing reference or derived speech; the model and repository
licenses do not by themselves establish those rights.
