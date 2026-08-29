import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile } from "remotion";
import cuesData from "../../narration/v6-cues.json";
import { colors } from "../styles";
import { V6CtaScene, V6ResultsScene } from "./V6ClosingScenes";
import { V6MechanismScene } from "./V6MechanismScene";
import {
  V6ComplexityScene,
  V6TitleScene,
  V6TurnLevelScene,
} from "./V6OpeningScenes";
import { V6ShowcaseScene } from "./V6ShowcaseScene";
import { V6CreditsScene } from "./V6CreditsScene";

const FPS = 30;

export const V6_DURATIONS = {
  title: 5 * FPS,
  complexity: 7 * FPS,
  turnLevel: 8 * FPS,
  mechanism: 20 * FPS,
  showcase: 25 * FPS,
  results: 11 * FPS,
  cta: 5 * FPS,
  credits: 3 * FPS,
} as const;

export const V6_BOUNDARIES = {
  title: 0,
  complexity: V6_DURATIONS.title,
  turnLevel: V6_DURATIONS.title + V6_DURATIONS.complexity,
  mechanism: V6_DURATIONS.title + V6_DURATIONS.complexity + V6_DURATIONS.turnLevel,
  showcase: V6_DURATIONS.title + V6_DURATIONS.complexity + V6_DURATIONS.turnLevel + V6_DURATIONS.mechanism,
  results: V6_DURATIONS.title + V6_DURATIONS.complexity + V6_DURATIONS.turnLevel + V6_DURATIONS.mechanism + V6_DURATIONS.showcase,
  cta: V6_DURATIONS.title + V6_DURATIONS.complexity + V6_DURATIONS.turnLevel + V6_DURATIONS.mechanism + V6_DURATIONS.showcase + V6_DURATIONS.results,
  credits: V6_DURATIONS.title + V6_DURATIONS.complexity + V6_DURATIONS.turnLevel + V6_DURATIONS.mechanism + V6_DURATIONS.showcase + V6_DURATIONS.results + V6_DURATIONS.cta,
} as const;

export const V6_DEMO_FRAMES = Object.values(V6_DURATIONS).reduce(
  (total, duration) => total + duration,
  0,
);

type MusicCue = { start: number; end: number };
const musicCues = cuesData as MusicCue[];

const narrationDuck = (seconds: number) => {
  const fadeSeconds = 0.24;
  let gain = 1;
  for (const cue of musicCues) {
    if (seconds < cue.start - fadeSeconds || seconds > cue.end + fadeSeconds) continue;
    if (seconds < cue.start) gain = Math.min(gain, 1 - 0.38 * ((seconds - cue.start + fadeSeconds) / fadeSeconds));
    else if (seconds > cue.end) gain = Math.min(gain, 0.62 + 0.38 * ((seconds - cue.end) / fadeSeconds));
    else gain = Math.min(gain, 0.62);
  }
  return gain;
};

export const V6DemoReel: React.FC<{ musicVolume?: number; duckForNarration?: boolean }> = ({ musicVolume = 0.34, duckForNarration = false }) => (
  <AbsoluteFill style={{ backgroundColor: colors.canvas }}>
    <Audio
      src={staticFile("audio/inspired-redeck-81s.mp3")}
      name="Inspired - Kevin MacLeod - CC BY 4.0 - ReDeck edit"
      volume={(frame) => {
        const seconds = frame / FPS;
        return musicVolume * (duckForNarration ? narrationDuck(seconds) : 1);
      }}
    />

    <Sequence from={V6_BOUNDARIES.title} durationInFrames={V6_DURATIONS.title}>
      <V6TitleScene />
    </Sequence>
    <Sequence from={V6_BOUNDARIES.complexity} durationInFrames={V6_DURATIONS.complexity}>
      <V6ComplexityScene />
    </Sequence>
    <Sequence from={V6_BOUNDARIES.turnLevel} durationInFrames={V6_DURATIONS.turnLevel}>
      <V6TurnLevelScene />
    </Sequence>
    <Sequence from={V6_BOUNDARIES.mechanism} durationInFrames={V6_DURATIONS.mechanism}>
      <V6MechanismScene />
    </Sequence>
    <Sequence from={V6_BOUNDARIES.showcase} durationInFrames={V6_DURATIONS.showcase}>
      <V6ShowcaseScene />
    </Sequence>
    <Sequence from={V6_BOUNDARIES.results} durationInFrames={V6_DURATIONS.results}>
      <V6ResultsScene />
    </Sequence>
    <Sequence from={V6_BOUNDARIES.cta} durationInFrames={V6_DURATIONS.cta}>
      <V6CtaScene />
    </Sequence>
    <Sequence from={V6_BOUNDARIES.credits} durationInFrames={V6_DURATIONS.credits}>
      <V6CreditsScene />
    </Sequence>
  </AbsoluteFill>
);