import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { CoastBackdrop, SceneProps, Wordmark, clamp, sceneOpacity } from "../components/VideoUI";
import { colors, fonts } from "../styles";

export const Outro: React.FC<SceneProps> = ({ durationInFrames }) => {
  const frame = useCurrentFrame();
  const opacity = 1;

  return (
    <AbsoluteFill style={{ opacity: sceneOpacity(frame, durationInFrames) }}>
      <CoastBackdrop variant="dark" />
      <AbsoluteFill style={{ fontFamily: fonts.body, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ width: 1280, opacity, transform: `translateY(${interpolate(opacity, [0, 1], [28, 0])}px)` }}>
          <Wordmark inverse fontSize={150} />
          <div style={{ marginTop: 34, color: colors.white, fontFamily: fonts.heading, fontSize: 48, lineHeight: 1.15, fontWeight: 700 }}>
            One edit. One rendered observation.
          </div>
          <div style={{ width: 940, marginTop: 24, color: "rgba(255,255,255,0.70)", fontSize: 25, lineHeight: 1.45 }}>
            Step-level render-grounded refinement for document-to-slide generation
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 22,
              marginTop: 72,
              paddingTop: 28,
              borderTop: `3px solid ${colors.seafoam}`,
              color: colors.sand,
              fontSize: 25,
              fontWeight: 750,
            }}
          >
            microsoft.github.io/ReDeck
            <span style={{ color: "rgba(255,255,255,0.36)" }}>·</span>
            Paper
            <span style={{ color: "rgba(255,255,255,0.36)" }}>·</span>
            Code
          </div>
          <div
            style={{
              marginTop: 22,
              color: "rgba(255,255,255,0.52)",
              fontSize: 15,
              lineHeight: 1.4,
            }}
          >
            Music: “Bassa Island Game Loop” by Kevin MacLeod · CC BY 4.0 · edited for this demo
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
