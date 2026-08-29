import React from "react";
import { Composition } from "remotion";
import { V6_DEMO_FRAMES } from "./v6/V6DemoReel";
import {
  V6DemoReelEnglish,
  V6_ENGLISH_HEIGHT,
} from "./v6/V6NarratedDemoReel";

const FPS = 30;

export const RemotionRoot: React.FC = () => (
  <Composition
    id="ReDeckDemo"
    component={V6DemoReelEnglish}
    durationInFrames={V6_DEMO_FRAMES}
    fps={FPS}
    width={1920}
    height={V6_ENGLISH_HEIGHT}
  />
);