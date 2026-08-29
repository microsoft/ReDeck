#!/usr/bin/env python3
"""Generate consistently paced ReDeck narration with Fun-CosyVoice3."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cosyvoice-root", default=os.environ.get("COSYVOICE_ROOT"))
    parser.add_argument("--model", default="pretrained_models/Fun-CosyVoice3-0.5B")
    parser.add_argument("--cues", default=str(Path(__file__).with_name("cues.json")))
    parser.add_argument("--prompt-wav", required=True)
    parser.add_argument("--prompt-metadata", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=20260821)
    parser.add_argument("--min-margin", type=float, default=0.12)
    args = parser.parse_args()
    if not args.cosyvoice_root:
        parser.error("--cosyvoice-root or COSYVOICE_ROOT is required")
    return args


def trim_and_normalize(audio, sample_rate: int, torch):
    if audio.ndim == 1:
        audio = audio.unsqueeze(0)
    audio = audio.float().cpu()
    threshold = 10 ** (-55 / 20)
    active = torch.any(torch.abs(audio) > threshold, dim=0)
    indices = torch.where(active)[0]
    if len(indices) > 0:
        pad = round(0.06 * sample_rate)
        start = max(0, int(indices[0]) - pad)
        end = min(audio.shape[1], int(indices[-1]) + pad + 1)
        audio = audio[:, start:end]

    active = torch.abs(audio) > threshold
    rms = torch.sqrt(torch.mean(audio[active] ** 2)) if torch.any(active) else torch.tensor(1.0)
    target_rms = 10 ** (-20 / 20)
    peak_limit = 10 ** (-2 / 20)
    peak = torch.max(torch.abs(audio)).clamp_min(1e-6)
    gain = min(target_rms / float(rms), peak_limit / float(peak))
    audio = audio * gain

    fade_samples = min(round(0.035 * sample_rate), audio.shape[1] // 2)
    if fade_samples > 1:
        fade = torch.linspace(0, 1, fade_samples)
        audio[:, :fade_samples] *= fade
        audio[:, -fade_samples:] *= torch.flip(fade, dims=(0,))
    return audio.clamp(-1, 1)


def main() -> None:
    args = parse_args()
    cosyvoice_root = Path(args.cosyvoice_root).resolve()
    sys.path[:0] = [str(cosyvoice_root), str(cosyvoice_root / "third_party" / "Matcha-TTS")]

    import torch
    import torchaudio
    from cosyvoice.cli.cosyvoice import AutoModel

    cues = json.loads(Path(args.cues).read_text(encoding="utf-8"))
    prompt_metadata = json.loads(Path(args.prompt_metadata).read_text(encoding="utf-8"))
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    model_dir = Path(args.model)
    if not model_dir.is_absolute():
        model_dir = cosyvoice_root / model_dir
    model = AutoModel(model_dir=str(model_dir), fp16=torch.cuda.is_available())
    prompt_text = f"You are a helpful assistant.<|endofprompt|>{prompt_metadata['text']}"

    manifest = {
        "engine": "Fun-CosyVoice3-0.5B",
        "engine_license": "Apache-2.0",
        "reference": prompt_metadata,
        "speed": args.speed,
        "seed": args.seed,
        "sample_rate": model.sample_rate,
        "normalization": {"active_rms_dbfs": -20, "peak_limit_dbfs": -2},
        "cues": [],
    }
    failures = []

    for cue_index, cue in enumerate(cues):
        torch.manual_seed(args.seed + cue_index)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(args.seed + cue_index)
        spoken_text = cue.get("tts_en", cue["en"])
        instruction = cue.get("instruct")
        if instruction:
            chunks = list(model.inference_instruct2(
                spoken_text,
                f"You are a helpful assistant. {instruction}<|endofprompt|>",
                args.prompt_wav,
                stream=False,
                speed=args.speed,
            ))
        else:
            chunks = list(model.inference_zero_shot(
                spoken_text,
                prompt_text,
                args.prompt_wav,
                stream=False,
                speed=args.speed,
            ))
        if not chunks:
            raise RuntimeError(f"No audio generated for {cue['id']}")
        audio = torch.cat([chunk["tts_speech"].cpu() for chunk in chunks], dim=1)
        audio = trim_and_normalize(audio, model.sample_rate, torch)
        target = output_dir / f"{cue['id']}.wav"
        torchaudio.save(str(target), audio, model.sample_rate, encoding="PCM_S", bits_per_sample=16)

        duration = audio.shape[1] / model.sample_rate
        window = cue["end"] - cue["start"]
        margin = window - duration
        item = {
            "id": cue["id"],
            "text": spoken_text,
            "mode": "instruct2" if instruction else "zero_shot",
            "instruction": instruction,
            "duration": round(duration, 3),
            "window": round(window, 3),
            "margin": round(margin, 3),
            "rms_dbfs": round(20 * math.log10(max(float(torch.sqrt(torch.mean(audio ** 2))), 1e-8)), 2),
            "peak_dbfs": round(20 * math.log10(max(float(torch.max(torch.abs(audio))), 1e-8)), 2),
        }
        manifest["cues"].append(item)
        print(f"{item['id']}: {duration:.3f}s / {window:.3f}s, margin {margin:.3f}s")
        if margin < args.min_margin:
            failures.append(item)

    (output_dir / "cosyvoice-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if failures:
        failed = ", ".join(f"{item['id']} ({item['margin']:.3f}s)" for item in failures)
        raise RuntimeError(f"Narration cues exceed the required timing margin: {failed}")


if __name__ == "__main__":
    main()