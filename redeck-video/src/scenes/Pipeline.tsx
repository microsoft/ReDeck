import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { CoastBackdrop, SceneLabel, SceneProps, SlideFrame, clamp, sceneOpacity } from "../components/VideoUI";
import { colors, fonts } from "../styles";

const nodes = [
  { name: "Edit", note: "one atomic source change", color: colors.coral, start: 22 },
  { name: "Render", note: "materialize the current deck", color: colors.apricot, start: 48 },
  { name: "Observe", note: "report spatial changes and element positions", color: colors.ocean, start: 74 },
  { name: "Decide", note: "continue, correct, or roll back", color: colors.success, start: 100 },
];

export const Pipeline: React.FC<SceneProps> = ({ durationInFrames }) => {
  const frame = useCurrentFrame();

  return (
    <AbsoluteFill style={{ opacity: sceneOpacity(frame, durationInFrames) }}>
      <CoastBackdrop />
      <AbsoluteFill style={{ padding: "56px 84px", fontFamily: fonts.body }}>
        <SceneLabel index="02">The mechanism</SceneLabel>
        <div style={{ marginTop: 26, color: colors.ink, fontFamily: fonts.heading, fontSize: 58, fontWeight: 800 }}>
          Global guidance. Immediate spatial facts.
        </div>
        <div
          style={{
            position: "absolute",
            left: 84,
            top: 250,
            width: 690,
          }}
        >
          <div
            style={{
              padding: "25px 28px",
              color: colors.white,
              backgroundColor: colors.ink,
              borderLeft: `8px solid ${colors.seafoam}`,
            }}
          >
            <div style={{ color: colors.seafoam, fontSize: 17, fontWeight: 800, textTransform: "uppercase" }}>Turn level</div>
            <div style={{ marginTop: 8, fontFamily: fonts.heading, fontSize: 32, fontWeight: 800 }}>Turn-Level Adaptive Deck Critic</div>
            <div style={{ marginTop: 7, color: "rgba(255,255,255,0.70)", fontSize: 19 }}>Maintains a persistent list of deck-wide concerns.</div>
          </div>
          <div style={{ marginTop: 20, color: colors.coral, fontSize: 17, fontWeight: 800, textTransform: "uppercase" }}>Step-Level Render Feedback · after every atomic action</div>
          <div style={{ marginTop: 4 }}>
            {nodes.map((node, index) => {
              const opacity = interpolate(frame, [node.start, node.start + 8], [0, 1], clamp);
              const nextStart = nodes[index + 1]?.start ?? 132;
              const active = frame >= node.start && frame < nextStart;
              return (
                <div
                  key={node.name}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "52px 155px 1fr",
                    alignItems: "center",
                    minHeight: 82,
                    padding: "0 20px",
                    backgroundColor: active ? `${node.color}18` : colors.white,
                    borderBottom: `1px solid ${colors.line}`,
                    borderLeft: `6px solid ${active ? node.color : "transparent"}`,
                    opacity,
                    transform: `translateX(${interpolate(opacity, [0, 1], [-20, 0])}px)`,
                  }}
                >
                  <div style={{ color: node.color, fontFamily: fonts.heading, fontSize: 30, fontWeight: 800 }}>0{index + 1}</div>
                  <div style={{ color: colors.ink, fontSize: 25, fontWeight: 800 }}>{node.name}</div>
                  <div style={{ color: colors.inkSoft, fontSize: 18 }}>{node.note}</div>
                </div>
              );
            })}
          </div>
        </div>
        <SlideFrame
          src="trajectory/d78_00.png"
          label="Current render"
          labelColor={colors.error}
          style={{
            position: "absolute",
            left: 830,
            top: 250,
            width: 1000,
            height: 563,
          }}
        >
          <div
            style={{
              position: "absolute",
              top: `${interpolate(frame, [70, 122], [8, 88], clamp)}%`,
              left: 10,
              right: 10,
              height: 5,
              backgroundColor: colors.ocean,
              boxShadow: `0 0 24px ${colors.ocean}`,
              opacity: interpolate(frame, [66, 74, 122, 130], [0, 1, 1, 0], clamp),
            }}
          />
        </SlideFrame>
        {/* Detection output — shows real spatial info flowing from render */}
        <div
          style={{
            position: "absolute",
            left: 830,
            top: 835,
            width: 1000,
            padding: "16px 22px",
            backgroundColor: colors.white,
            border: `1px solid ${colors.line}`,
            borderLeft: `5px solid ${colors.error}`,
            opacity: interpolate(frame, [74, 88], [0, 1], clamp),
            transform: `translateY(${interpolate(frame, [74, 88], [12, 0], clamp)}px)`,
          }}
        >
          <div style={{ fontSize: 14, fontWeight: 800, color: colors.error, textTransform: "uppercase", letterSpacing: 2, marginBottom: 8 }}>
            Spatial observation
          </div>
          <div style={{ display: "flex", gap: 28, fontSize: 17, color: colors.ink, fontWeight: 700 }}>
            <span>Overflow: <span style={{ color: colors.error }}>129px</span></span>
            <span>Issues: <span style={{ color: colors.error }}>32</span></span>
            <span>Leverage: <span style={{ color: colors.ocean }}>td × 12 = 108px</span></span>
          </div>
        </div>
        {/* Decision output — appears after observe step */}
        <div
          style={{
            position: "absolute",
            left: 830,
            top: 910,
            width: 1000,
            padding: "14px 22px",
            backgroundColor: colors.white,
            border: `1px solid ${colors.line}`,
            borderLeft: `5px solid ${colors.success}`,
            opacity: interpolate(frame, [108, 122], [0, 1], clamp),
            transform: `translateY(${interpolate(frame, [108, 122], [12, 0], clamp)}px)`,
          }}
        >
          <div style={{ fontSize: 14, fontWeight: 800, color: colors.success, textTransform: "uppercase", letterSpacing: 2, marginBottom: 6 }}>
            Agent decision
          </div>
          <div style={{ fontSize: 17, color: colors.ink, fontWeight: 700 }}>
            Compress td padding 15→6px (highest leverage) → expected savings 108px
          </div>
        </div>
        <div
          style={{
            position: "absolute",
            left: 84,
            bottom: 54,
            width: 690,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            paddingTop: 18,
            borderTop: `3px solid ${colors.error}`,
            color: colors.error,
            fontSize: 19,
            fontWeight: 750,
            opacity: interpolate(frame, [128, 140], [0, 1], clamp),
          }}
        >
          <span>If a regression appears</span>
          <span>the agent may correct or roll back</span>
        </div>
        <div
          style={{
            position: "absolute",
            right: 90,
            bottom: 54,
            color: colors.ink,
            fontFamily: fonts.heading,
            fontSize: 38,
            fontWeight: 800,
            opacity: interpolate(frame, [132, 146], [0, 1], clamp),
          }}
        >
          Feedback arrives: turn boundary → every edit
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
