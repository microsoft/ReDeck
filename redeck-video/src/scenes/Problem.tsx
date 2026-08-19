import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { CoastBackdrop, SceneLabel, SceneProps, SlideFrame, clamp, sceneOpacity } from "../components/VideoUI";
import { colors, fonts } from "../styles";

export const Problem: React.FC<SceneProps> = ({ durationInFrames }) => {
  const frame = useCurrentFrame();
  const markerOpacity = interpolate(frame, [42, 62], [0, 1], clamp);
  const secondMarkerOpacity = interpolate(frame, [82, 102], [0, 1], clamp);
  const slideScale = interpolate(frame, [0, 80], [0.96, 1], clamp);

  return (
    <AbsoluteFill style={{ opacity: sceneOpacity(frame, durationInFrames) }}>
      <CoastBackdrop />
      <AbsoluteFill style={{ padding: "66px 84px", fontFamily: fonts.body }}>
        <SceneLabel index="01">The problem</SceneLabel>
        <div style={{ position: "absolute", left: 84, top: 180, width: 500 }}>
          <div style={{ color: colors.ink, fontFamily: fonts.heading, fontSize: 58, lineHeight: 1.08, fontWeight: 800 }}>
            The agent edits source code.
          </div>
          <div style={{ marginTop: 28, color: colors.inkSoft, fontSize: 27, lineHeight: 1.42 }}>
            Its spatial consequences appear only after rendering.
          </div>
          <div style={{ marginTop: 60, paddingTop: 24, borderTop: `3px solid ${colors.coral}` }}>
            <div style={{ color: colors.error, fontSize: 21, fontWeight: 800, textTransform: "uppercase" }}>
              Turn-boundary feedback
            </div>
            <div style={{ marginTop: 10, color: colors.ink, fontSize: 30, lineHeight: 1.3, fontWeight: 700 }}>
              Multiple edits can accumulate before a turn-boundary critique arrives.
            </div>
          </div>
        </div>
        <SlideFrame
          src="trajectory/d78_00.png"
          label="Draft"
          labelColor={colors.error}
          style={{
            position: "absolute",
            left: 650,
            top: 160,
            width: 1160,
            height: 653,
            transform: `scale(${slideScale})`,
          }}
        >
          <div
            style={{
              position: "absolute",
              left: "0%",
              top: "58%",
              width: "100%",
              height: "42%",
              border: `6px solid ${colors.error}`,
              backgroundColor: "rgba(197, 87, 94, 0.10)",
              opacity: markerOpacity,
            }}
          />
          <div
            style={{
              position: "absolute",
              right: 18,
              bottom: 18,
              width: 420,
              padding: "14px 18px",
              color: colors.white,
              backgroundColor: colors.error,
              fontSize: 18,
              fontWeight: 800,
              opacity: secondMarkerOpacity,
            }}
          >
            Content overflows 129px past the 720px canvas
          </div>
        </SlideFrame>
        <div
          style={{
            position: "absolute",
            left: 650,
            bottom: 72,
            width: 1160,
            display: "flex",
            alignItems: "center",
            gap: 18,
            color: colors.inkSoft,
            fontSize: 20,
          }}
        >
          <span style={{ width: 54, height: 4, backgroundColor: colors.error }} />
          The initial render exposes a spatial regression that source code alone cannot show.
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
