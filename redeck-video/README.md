# ReDeck research overview video

This Remotion project contains the source for one public video: an 84-second
English-narrated overview with burned-in English captions.

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

The committed narration assets live in `public/narration-v6/`. To regenerate
them with Fun-CosyVoice3, set `COSYVOICE_PYTHON` and run:

```bash
npm run narration:generate
```

The music credit and modification notice are in
`public/audio/INSPIRED_LICENSE.md`.
