import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { CoastBackdrop, SceneLabel, SceneProps, SlideFrame, Wordmark, clamp, sceneOpacity } from "../components/VideoUI";
import { colors, fonts } from "../styles";

export const Intro: React.FC<SceneProps> = ({ durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 18, stiffness: 95 } });
  const copyOpacity = interpolate(frame, [8, 28], [0, 1], clamp);
  const featuredSlides = [
    { src: "demo-pairs/after/d78.png", x: 1030, y: 98, rotate: -4, delay: 10 },
    { src: "demo-pairs/after/d181.png", x: 1115, y: 332, rotate: 4, delay: 18 },
    { src: "demo-pairs/after/p43.png", x: 925, y: 548, rotate: -2, delay: 26 },
  ];

  return (
    <AbsoluteFill style={{ opacity: sceneOpacity(frame, durationInFrames) }}>
      <CoastBackdrop variant="hero" />
      <AbsoluteFill style={{ padding: "78px 92px", fontFamily: fonts.body }}>
        <SceneLabel index="00">60-second research demo</SceneLabel>
        <div
          style={{
            position: "absolute",
            left: 92,
            top: 250,
            width: 820,
            opacity: copyOpacity,
            transform: `translateX(${interpolate(enter, [0, 1], [-44, 0])}px)`,
          }}
        >
          <Wordmark fontSize={148} />
          <div
            style={{
              marginTop: 34,
              color: colors.ink,
              fontFamily: fonts.heading,
              fontSize: 50,
              lineHeight: 1.12,
              fontWeight: 700,
            }}
          >
            One edit.
            <br />
            One rendered observation.
          </div>
          <div
            style={{
              width: 650,
              marginTop: 30,
              color: colors.inkSoft,
              fontSize: 24,
              lineHeight: 1.45,
            }}
          >
            Step-level render-grounded refinement for document-to-slide generation
          </div>
        </div>
        {featuredSlides.map((item) => {
          const progress = spring({
            frame,
            fps,
            delay: item.delay,
            config: { damping: 17, stiffness: 105 },
          });
          return (
            <SlideFrame
              key={item.src}
              src={item.src}
              style={{
                position: "absolute",
                left: item.x,
                top: item.y,
                width: 690,
                height: 388,
                opacity: progress,
                transform: `translateY(${interpolate(progress, [0, 1], [80, 0])}px) rotate(${item.rotate}deg) scale(${interpolate(progress, [0, 1], [0.93, 1])})`,
              }}
            />
          );
        })}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
