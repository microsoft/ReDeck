import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import {
  CoastBackdrop,
  SceneLabel,
  SceneProps,
  clamp,
  sceneOpacity,
} from "../components/VideoUI";
import { colors, fonts } from "../styles";

const secondaryMetrics = [
  { value: "73%", label: "potential regressions rolled back before issue-list entry", color: colors.success },
  { value: "+0.69", label: "aesthetics gain", color: colors.coral },
  { value: "+8.2", label: "content fidelity", color: colors.ocean },
];

export const ImpactResults: React.FC<SceneProps> = ({ durationInFrames }) => {
  const frame = useCurrentFrame();
  const finalRate = interpolate(frame, [24, 126], [64.1, 91.5], clamp);
  const crossOpacity = interpolate(frame, [190, 212], [0, 1], clamp);

  return (
    <AbsoluteFill style={{ opacity: sceneOpacity(frame, durationInFrames) }}>
      <CoastBackdrop />
      <AbsoluteFill style={{ padding: "56px 84px", fontFamily: fonts.body }}>
        <SceneLabel index="04">The result</SceneLabel>
        <div
          style={{
            marginTop: 24,
            color: colors.ink,
            fontFamily: fonts.heading,
            fontSize: 58,
            fontWeight: 800,
          }}
        >
          Spatial Clean Rate rises from <span style={{ color: colors.error }}>64.1</span> to <span style={{ color: colors.success }}>91.5</span>
        </div>

        <div style={{ position: "absolute", left: 84, top: 260, width: 760 }}>
          <div
            style={{
              color: colors.inkSoft,
              fontSize: 19,
              fontWeight: 800,
              textTransform: "uppercase",
            }}
          >
            Spatial Clean Rate · GPT-5.4
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 22, marginTop: 16 }}>
            <div
              style={{
                color: "#a8b4b6",
                fontFamily: fonts.heading,
                fontSize: 92,
                fontWeight: 800,
              }}
            >
              64.1
            </div>
            <div style={{ color: colors.coral, fontSize: 58, fontWeight: 800 }}>→</div>
            <div
              style={{
                color: colors.success,
                fontFamily: fonts.heading,
                fontSize: 150,
                lineHeight: 0.9,
                fontWeight: 800,
                transform: `scale(${interpolate(frame, [24, 50, 126], [0.86, 1.06, 1], clamp)})`,
                transformOrigin: "left center",
              }}
            >
              {finalRate.toFixed(1)}
            </div>
          </div>
          <div
            style={{
              marginTop: 24,
              display: "inline-block",
              padding: "15px 22px",
              color: colors.white,
              backgroundColor: colors.coral,
              fontFamily: fonts.heading,
              fontSize: 38,
              fontWeight: 800,
              transform: `translateX(${interpolate(frame, [18, 38], [-90, 0], clamp)}px)`,
              opacity: interpolate(frame, [18, 34], [0, 1], clamp),
            }}
          >
            +27.4 percentage points
          </div>
          <div
            style={{
              marginTop: 25,
              width: 650,
              color: colors.inkSoft,
              fontSize: 22,
              lineHeight: 1.4,
            }}
          >
            Equivalent to about 13 → 18 slides without hard layout issues per 20 (illustrative).
          </div>
        </div>

        <div style={{ position: "absolute", left: 990, top: 250, width: 840 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 18,
            }}
          >
            <div style={{ color: colors.ink, fontSize: 24, fontWeight: 800 }}>
              Illustrative SCR conversion · 20 slides
            </div>
            <div style={{ display: "flex", gap: 18, color: colors.inkSoft, fontSize: 16 }}>
              <span><b style={{ color: colors.error }}>■</b> hard issue</span>
              <span><b style={{ color: colors.success }}>■</b> no hard issue</span>
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 17 }}>
            {Array.from({ length: 20 }, (_, index) => {
              const initiallyClean = index < 13;
              const flips = index >= 13 && index < 18;
              const flipIndex = index - 13;
              const flip = flips
                ? interpolate(frame, [42 + flipIndex * 14, 56 + flipIndex * 14], [0, 1], clamp)
                : 0;
              const clean = initiallyClean || (flips && flip > 0.5);
              const bounce = flips ? interpolate(flip, [0, 0.5, 1], [1, 1.12, 1]) : 1;

              return (
                <div
                  key={index}
                  style={{
                    height: 92,
                    padding: "16px 18px",
                    backgroundColor: clean ? colors.success : colors.error,
                    transform: `scale(${bounce})`,
                    boxShadow: clean
                      ? "0 10px 22px rgba(52,139,117,0.16)"
                      : "0 10px 22px rgba(197,87,94,0.16)",
                  }}
                >
                  <div style={{ width: "68%", height: 7, backgroundColor: "rgba(255,255,255,0.82)" }} />
                  <div
                    style={{
                      width: "90%",
                      height: 5,
                      marginTop: 12,
                      backgroundColor: "rgba(255,255,255,0.48)",
                    }}
                  />
                  <div
                    style={{
                      width: "54%",
                      height: 5,
                      marginTop: 8,
                      backgroundColor: "rgba(255,255,255,0.48)",
                    }}
                  />
                </div>
              );
            })}
          </div>
          <div
            style={{
              marginTop: 25,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              color: colors.inkSoft,
              fontSize: 18,
            }}
          >
            <span>T0 · 64.1</span>
            <span style={{ width: 440, height: 5, backgroundColor: colors.seafoam }} />
            <span style={{ color: colors.success, fontWeight: 800 }}>ReDeck · 91.5</span>
          </div>
        </div>

        <div
          style={{
            position: "absolute",
            left: 84,
            right: 84,
            bottom: 72,
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 16,
          }}
        >
          {secondaryMetrics.map((metric, index) => {
            const opacity = interpolate(frame, [150 + index * 12, 162 + index * 12], [0, 1], clamp);
            return (
              <div
                key={metric.label}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "24px 28px",
                  color: colors.white,
                  backgroundColor: metric.color,
                  opacity,
                  transform: `translateY(${interpolate(opacity, [0, 1], [34, 0])}px)`,
                }}
              >
                <div style={{ fontFamily: fonts.heading, fontSize: 56, fontWeight: 800 }}>
                  {metric.value}
                </div>
                <div style={{ fontSize: 19, fontWeight: 800, textTransform: "uppercase" }}>
                  {metric.label}
                </div>
              </div>
            );
          })}
        </div>
        <div style={{ position: "absolute", right: 90, bottom: 32, color: colors.inkSoft, fontSize: 16 }}>
          DeckQuiz · 100 tasks · 3 seeds
        </div>

        <div
          style={{
            position: "absolute",
            inset: 0,
            opacity: crossOpacity,
            backgroundColor: colors.canvas,
          }}
        >
          <CoastBackdrop />
          <AbsoluteFill style={{ padding: "56px 84px", fontFamily: fonts.body }}>
            <SceneLabel index="04">Across agent models</SceneLabel>
            <div
              style={{
                marginTop: 24,
                color: colors.ink,
                fontFamily: fonts.heading,
                fontSize: 62,
                fontWeight: 800,
              }}
            >
              SCR improves by about 27 points with <span style={{ color: colors.ocean }}>all three agent models</span>
            </div>
            <div style={{ position: "absolute", left: 130, right: 130, top: 270 }}>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "250px 1fr 130px 150px",
                  gap: 24,
                  marginBottom: 16,
                  color: colors.inkSoft,
                  fontSize: 15,
                  fontWeight: 800,
                  textTransform: "uppercase",
                }}
              >
                <span>Agent model</span><span></span><span style={{ textAlign: "right" }}>Final SCR</span><span style={{ textAlign: "center" }}>Δ from T0</span>
              </div>
              {[
                { name: "GPT-5.4", score: 91.5, delta: "+27.4pp", color: colors.success },
                { name: "Gemini-3.1", score: 88.2, delta: "+27.0pp", color: colors.coral },
                { name: "Claude-4.6", score: 89.6, delta: "+27.1pp", color: colors.ocean },
              ].map((model, index) => {
                const progress = interpolate(
                  frame,
                  [205 + index * 18, 239 + index * 18],
                  [0, 1],
                  clamp,
                );
                return (
                  <div
                    key={model.name}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "250px 1fr 130px 150px",
                      alignItems: "center",
                      gap: 24,
                      marginBottom: 42,
                    }}
                  >
                    <div style={{ color: colors.ink, fontSize: 29, fontWeight: 800 }}>
                      {model.name}
                    </div>
                    <div style={{ height: 72, backgroundColor: "#e4ebea", overflow: "hidden" }}>
                      <div
                        style={{
                          width: `${model.score * progress}%`,
                          height: "100%",
                          backgroundColor: model.color,
                        }}
                      />
                    </div>
                    <div
                      style={{
                        color: model.color,
                        fontFamily: fonts.heading,
                        fontSize: 55,
                        fontWeight: 800,
                        textAlign: "right",
                      }}
                    >
                      {model.score}
                    </div>
                    <div
                      style={{
                        padding: "11px 15px",
                        color: colors.white,
                        backgroundColor: model.color,
                        fontSize: 21,
                        fontWeight: 800,
                        textAlign: "center",
                        opacity: progress,
                      }}
                    >
                      {model.delta}
                    </div>
                  </div>
                );
              })}
            </div>
            <div
              style={{
                position: "absolute",
                left: 130,
                right: 130,
                bottom: 84,
                paddingTop: 24,
                borderTop: `4px solid ${colors.seafoam}`,
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                color: colors.ink,
                fontSize: 23,
                fontWeight: 750,
              }}
            >
              <span>Final ReDeck SCR is at least 88.2 with every agent model.</span>
              <span style={{ color: colors.inkSoft }}>DeckQuiz · 100 tasks · 3 seeds</span>
            </div>
          </AbsoluteFill>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
