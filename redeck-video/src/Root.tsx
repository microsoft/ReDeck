import React from "react";
import { AbsoluteFill, Audio, Composition, Sequence, staticFile } from "remotion";
import { Intro } from "./scenes/Intro";
import { Problem } from "./scenes/Problem";
import { AgentWorkflow } from "./scenes/AgentWorkflow";
import { ImpactResults } from "./scenes/ImpactResults";
import { Outro } from "./scenes/Outro";
import { colors } from "./styles";

const FPS = 30;

const INTRO = 5;
const PROBLEM = 6;
const WORKFLOW = 33;
const RESULTS = 12;
const OUTRO = 4;

const TOTAL = INTRO + PROBLEM + WORKFLOW + RESULTS + OUTRO; // 60s

const DemoReel: React.FC = () => {
  let offset = 0;
  const scene = (duration: number) => {
    const from = offset;
    offset += duration * FPS;
    return from;
  };

  const introFrom = scene(INTRO);
  const problemFrom = scene(PROBLEM);
  const workflowFrom = scene(WORKFLOW);
  const resultsFrom = scene(RESULTS);
  const outroFrom = scene(OUTRO);

  return (
    <AbsoluteFill style={{ backgroundColor: colors.canvas }}>
      <Audio src={staticFile("audio/bassa-redeck-60s.mp3")} name="Bassa Island Game Loop - Kevin MacLeod" />
      <Sequence from={introFrom} durationInFrames={INTRO * FPS}><Intro durationInFrames={INTRO * FPS} /></Sequence>
      <Sequence from={problemFrom} durationInFrames={PROBLEM * FPS}><Problem durationInFrames={PROBLEM * FPS} /></Sequence>
      <Sequence from={workflowFrom} durationInFrames={WORKFLOW * FPS}><AgentWorkflow durationInFrames={WORKFLOW * FPS} /></Sequence>
      <Sequence from={resultsFrom} durationInFrames={RESULTS * FPS}><ImpactResults durationInFrames={RESULTS * FPS} /></Sequence>
      <Sequence from={outroFrom} durationInFrames={OUTRO * FPS}><Outro durationInFrames={OUTRO * FPS} /></Sequence>
    </AbsoluteFill>
  );
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="DemoReel"
      component={DemoReel}
      durationInFrames={TOTAL * FPS}
      fps={FPS}
      width={1920}
      height={1080}
    />
  );
};
