import React from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { SceneHeading, Wordmark, clamp } from "../components/VideoUI";
import { colors, fonts, shadows } from "../styles";

const GridBackground: React.FC<{ dark?: boolean }> = ({ dark = false }) => (
  <AbsoluteFill
    style={{
      backgroundColor: dark ? "#071b22" : "#f7f8f3",
      backgroundImage: dark
        ? "linear-gradient(rgba(113,198,185,0.07) 1px, transparent 1px), linear-gradient(90deg, rgba(113,198,185,0.07) 1px, transparent 1px)"
        : "linear-gradient(rgba(49,141,181,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(49,141,181,0.04) 1px, transparent 1px)",
      backgroundSize: "44px 44px",
    }}
  />
);

const sceneEnter = (frame: number) => interpolate(frame, [0, 10], [0, 1], clamp);

const HomepageAurora: React.FC<{ frame: number }> = ({ frame }) => {
  const drift = interpolate(frame, [0, 150], [0, 14], clamp);
  return (
    <AbsoluteFill style={{ overflow: "hidden", backgroundColor: "#fffaf8" }}>
      <AbsoluteFill
        style={{
          transform: `translateX(${drift}px) scale(1.03)`,
          backgroundImage: "linear-gradient(180deg, #ffd8dc 0%, #ffe9dc 38%, #fff3d9 60%, #dcf2f4 100%)",
        }}
      />
      <AbsoluteFill
        style={{
          backgroundImage: [
            "linear-gradient(163deg, transparent 0%, transparent 58%, rgba(60,155,201,0.13) 58%, rgba(60,155,201,0.13) 66%, transparent 66%)",
            "linear-gradient(198deg, transparent 0%, transparent 64%, rgba(101,189,186,0.15) 64%, rgba(101,189,186,0.15) 72%, transparent 72%)",
            "linear-gradient(24deg, transparent 0%, transparent 70%, rgba(252,117,123,0.12) 70%, rgba(252,117,123,0.12) 76%, transparent 76%)",
          ].join(","),
        }}
      />
      <AbsoluteFill style={{ opacity: 0.22, backgroundImage: "radial-gradient(rgba(48,77,88,0.16) 0.65px, transparent 0.65px)", backgroundSize: "7px 7px" }} />
    </AbsoluteFill>
  );
};

const MicrosoftIdentity: React.FC = () => (
  <Img src={staticFile("branding/microsoft.svg")} style={{ width: 154, height: "auto" }} />
);

export const V6TitleScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const titleIn = spring({ frame, fps, config: { damping: 18, stiffness: 105 } });
  const draftIn = spring({ frame, fps, delay: 18, config: { damping: 17, stiffness: 100 } });
  const verifiedIn = spring({ frame, fps, delay: 48, config: { damping: 16, stiffness: 112 } });
  const pathIn = interpolate(frame, [52, 76], [0, 1], clamp);

  return (
    <AbsoluteFill style={{ color: "#263b49", fontFamily: fonts.body }}>
      <HomepageAurora frame={frame} />
      <AbsoluteFill>
        <div style={{ position: "absolute", left: 48, top: 29 }}><MicrosoftIdentity /></div>
        <div style={{ position: "absolute", left: 218, top: 35, width: 1, height: 31, backgroundColor: "#efdfda" }} />
        <div style={{ position: "absolute", left: 242, top: 35, color: "#c94f5a", fontFamily: fonts.heading, fontSize: 25, fontWeight: 800 }}>ReDeck</div>
        <div style={{ position: "absolute", right: 48, top: 39, color: "#8d9aa0", fontSize: 13, fontWeight: 800, textTransform: "uppercase" }}>
          Microsoft Research · Paper · Code · Demo
        </div>

        <div
          style={{
            position: "absolute",
            left: 96,
            right: 96,
            top: 112,
            textAlign: "center",
            opacity: titleIn,
            transform: `translateY(${interpolate(titleIn, [0, 1], [-24, 0])}px)`,
          }}
        >
          <div style={{ display: "flex", justifyContent: "center", fontFamily: fonts.heading, fontSize: 137, lineHeight: 0.9, fontWeight: 800, letterSpacing: 0, textShadow: "4px 5px 0 rgba(60,155,201,0.18)" }}>
            <span style={{ color: "#c94f5a" }}>Re</span><span style={{ color: "#304d58" }}>Deck</span>
          </div>
          <div style={{ margin: "26px auto 0", color: "#304d58", fontFamily: fonts.heading, fontSize: 41, lineHeight: 1.18, fontWeight: 650 }}>
            Agentic Slide Generation and<br /><span style={{ color: "#c94f5a", fontWeight: 800 }}>Render-Grounded Refinement</span>
          </div>
        </div>

        <div
          style={{
            position: "absolute",
            left: 115,
            right: 115,
            top: 445,
            display: "grid",
            gridTemplateColumns: "1fr 86px 1fr",
            alignItems: "center",
          }}
        >
          <div style={{ position: "relative", overflow: "hidden", aspectRatio: "16 / 9", border: "9px solid #ffffff", borderRadius: 14, backgroundColor: "#ffffff", boxShadow: "0 22px 58px rgba(48,77,88,0.16)", opacity: draftIn, transform: `translateX(${interpolate(draftIn, [0, 1], [-48, 0])}px)` }}>
            <Img src={staticFile("trajectory/d78_00.png")} style={{ width: "100%", height: "100%", objectFit: "contain" }} />
            <div style={{ position: "absolute", left: 16, top: 16, padding: "9px 13px", color: "#ffffff", backgroundColor: "#d95660", fontSize: 13, fontWeight: 800, textTransform: "uppercase" }}>Generated draft</div>
          </div>
          <div style={{ color: "#c94f5a", fontFamily: fonts.heading, fontSize: 54, fontWeight: 900, textAlign: "center", opacity: pathIn }}>→</div>
          <div style={{ position: "relative", overflow: "hidden", aspectRatio: "16 / 9", border: "9px solid #ffffff", borderRadius: 14, backgroundColor: "#ffffff", boxShadow: "0 22px 58px rgba(48,77,88,0.16)", opacity: verifiedIn, transform: `translateX(${interpolate(verifiedIn, [0, 1], [48, 0])}px)` }}>
            <Img src={staticFile("trajectory/d78_final.png")} style={{ width: "100%", height: "100%", objectFit: "contain" }} />
            <div style={{ position: "absolute", right: 16, top: 16, padding: "9px 13px", color: "#ffffff", backgroundColor: "#559b83", fontSize: 13, fontWeight: 800, textTransform: "uppercase" }}>Verified slide ✓</div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const issueCards = [
  { src: "crops/text_overflow.png", label: "Overflow" },
  { src: "crops/overlap.png", label: "Overlap" },
  { src: "crops/clipping.png", label: "Clipping" },
  { src: "crops/low_contrast.png", label: "Contrast" },
];

export const V6ComplexityScene: React.FC = () => {
  const frame = useCurrentFrame();
  const categories = [
    { ...issueCards[0], title: "Overflow", color: "#d95660" },
    { ...issueCards[1], title: "Overlap", color: "#f97f5f" },
    { ...issueCards[2], title: "Clipping", color: "#3c9bc9" },
    { ...issueCards[3], title: "Low contrast", color: "#faa26f" },
  ];

  return (
    <AbsoluteFill style={{ color: "#263b49", fontFamily: fonts.body }}>
      <HomepageAurora frame={frame} />
      <AbsoluteFill style={{ padding: "44px 62px" }}>
        <SceneHeading index="01" title={<>Existing <span style={{ color: "#c94f5a" }}>Problems</span></>} subtitle="AI-generated slides contain many issues; reliable refinement is essential." />

        <div style={{ position: "absolute", left: 62, right: 62, top: 150, bottom: 72, display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 24 }}>
          {categories.map((category, index) => {
            const progress = spring({ frame, fps: 30, delay: 18 + index * 20, config: { damping: 18, stiffness: 102 } });
            return (
              <div key={category.title} style={{ position: "relative", display: "flex", flexDirection: "column", overflow: "hidden", border: "8px solid #ffffff", borderRadius: 12, backgroundColor: "#ffffff", boxShadow: "0 24px 60px rgba(48,77,88,0.16)", opacity: progress, transform: `translateY(${interpolate(progress, [0, 1], [36, 0])}px)` }}>
                <div style={{ position: "relative", flex: 1, minHeight: 0, overflow: "hidden", backgroundColor: "#f7f4f1" }}>
                  <Img src={staticFile(category.src)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                  <div style={{ position: "absolute", inset: 0, border: `5px solid ${category.color}` }} />
                </div>
                <div style={{ flex: "0 0 104px", display: "flex", alignItems: "center", padding: "0 24px", borderTop: `8px solid ${category.color}`, backgroundColor: "#ffffff" }}>
                  <div style={{ color: category.color, fontFamily: fonts.heading, fontSize: 32, fontWeight: 800 }}>{category.title}</div>
                </div>
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const V6TurnLevelScene: React.FC = () => {
  const frame = useCurrentFrame();
  const reflectionIn = spring({ frame, fps: 30, delay: 12, config: { damping: 18, stiffness: 105 } });
  const batchIn = interpolate(frame, [44, 92], [0, 1], clamp);
  const renderIn = spring({ frame, fps: 30, delay: 94, config: { damping: 18, stiffness: 102 } });
  const feedbackIn = spring({ frame, fps: 30, delay: 158, config: { damping: 17, stiffness: 115 } });
  const batchEdits = [
    "e1′ · Narrow bullets + raise callout",
    "e2′ · Widen chart after next critique",
    "e3′ · Add metrics after next critique",
  ];

  return (
    <AbsoluteFill style={{ color: "#263b49", fontFamily: fonts.body }}>
      <HomepageAurora frame={frame} />
      <AbsoluteFill style={{ padding: "44px 62px" }}>
        <SceneHeading index="02" title={<span style={{ color: "#c94f5a" }}>Motivation</span>} subtitle="Without timely observation, the spatial effect of each edit remains unknown." />

        <div style={{ position: "absolute", left: 62, right: 62, top: 150, height: 735, display: "grid", gridTemplateColumns: "500px 88px 720px 88px 1fr", alignItems: "center" }}>
          <div style={{ alignSelf: "stretch", padding: "30px 30px", borderTop: "7px solid #3c9bc9", color: "#ffffff", backgroundColor: "#263b49", boxShadow: "0 22px 58px rgba(48,77,88,0.18)", opacity: reflectionIn, transform: `translateX(${interpolate(reflectionIn, [0, 1], [-30, 0])}px)` }}>
            <div style={{ color: "#8fd4d1", fontSize: 12, fontWeight: 800, textTransform: "uppercase" }}>One version, one feedback</div>
            <div style={{ marginTop: 17, fontFamily: fonts.heading, fontSize: 33, lineHeight: 1.15, fontWeight: 800 }}>Several regions change before the slide is rendered again.</div>
            <div style={{ marginTop: 24, display: "grid", gap: 11 }}>
              {batchEdits.map((edit, index) => {
                const progress = interpolate(batchIn, [index * 0.24, index * 0.24 + 0.5], [0, 1], clamp);
                return <div key={edit} style={{ display: "flex", alignItems: "center", gap: 13, padding: "13px 15px", border: "1px solid rgba(255,255,255,0.12)", backgroundColor: "rgba(255,255,255,0.06)", opacity: progress, transform: `translateX(${interpolate(progress, [0, 1], [-18, 0])}px)` }}><span style={{ width: 25, color: "#8fd4d1", fontFamily: fonts.mono, fontSize: 12, fontWeight: 800 }}>{String(index + 1).padStart(2, "0")}</span><span style={{ fontSize: 18, fontWeight: 800 }}>{edit}</span></div>;
              })}
            </div>
            <div style={{ marginTop: 25, paddingTop: 19, borderTop: "1px solid rgba(255,255,255,0.15)", color: "#f7a6aa", fontSize: 14, lineHeight: 1.4, fontWeight: 800, textTransform: "uppercase", opacity: batchIn }}>No render check between changes</div>
          </div>

          <div style={{ color: "#c94f5a", fontSize: 54, fontWeight: 900, textAlign: "center", opacity: renderIn }}>→</div>

          <div style={{ position: "relative", overflow: "hidden", aspectRatio: "8 / 5", border: "9px solid #ffffff", borderRadius: 12, backgroundColor: "#ffffff", boxShadow: "0 24px 62px rgba(48,77,88,0.18)", opacity: renderIn, transform: `translateY(${interpolate(renderIn, [0, 1], [30, 0])}px)` }}>
            <Img src={staticFile("paper-assets/monolithic-turn-trajectory.png")} style={{ width: "100%", height: "100%", objectFit: "contain" }} />
            <div style={{ position: "absolute", left: 15, top: 15, padding: "8px 11px", color: "#ffffff", backgroundColor: "#d95660", fontSize: 12, fontWeight: 800, textTransform: "uppercase" }}>One delayed observation · 3 → 5 issues</div>
            <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, padding: "15px 20px", color: "#ffffff", backgroundColor: "rgba(38,59,73,0.94)", fontFamily: fonts.heading, fontSize: 22, fontWeight: 800, textAlign: "center" }}>New failures persist until the next turn.</div>
          </div>

          <div style={{ color: "#8d9aa0", fontSize: 54, fontWeight: 900, textAlign: "center", opacity: feedbackIn }}>⇢</div>

          <div style={{ alignSelf: "stretch", display: "flex", flexDirection: "column", justifyContent: "center", opacity: feedbackIn, transform: `translateX(${interpolate(feedbackIn, [0, 1], [30, 0])}px)` }}>
            <div style={{ position: "relative", padding: "36px 30px", border: "3px solid #c94f5a", borderRadius: 12, color: "#263b49", backgroundColor: "#ffffff", boxShadow: "0 22px 58px rgba(48,77,88,0.15)" }}>
              <div style={{ position: "absolute", left: 30, top: -16, padding: "7px 11px", color: "#ffffff", backgroundColor: "#c94f5a", fontSize: 12, fontWeight: 800, textTransform: "uppercase" }}>Feedback after the rewrite</div>
              <div style={{ fontFamily: fonts.heading, fontSize: 30, lineHeight: 1.22, fontWeight: 800 }}>Multiple regions now fail.</div>
              <div style={{ marginTop: 24, paddingTop: 20, borderTop: "1px solid #efdfda", color: "#d95660", fontFamily: fonts.heading, fontSize: 25, lineHeight: 1.25, fontWeight: 800 }}>The responsible edit is unclear.</div>
            </div>
          </div>
        </div>

        <div style={{ position: "absolute", left: 62, right: 62, bottom: 34, color: "#c94f5a", fontFamily: fonts.heading, fontSize: 30, fontWeight: 800, textAlign: "center", opacity: feedbackIn }}>
          Feedback delay → weak attribution
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const OPENING_V6_FRAMES = {
  title: 5 * 30,
  complexity: 7 * 30,
  turnLevel: 8 * 30,
};

export const V6SceneFade: React.FC<{ durationInFrames: number; children: React.ReactNode }> = ({ durationInFrames, children }) => {
  const frame = useCurrentFrame();
  const opacity = Math.min(
    sceneEnter(frame),
    interpolate(frame, [durationInFrames - 7, durationInFrames - 1], [1, 0], clamp),
  );
  return <AbsoluteFill style={{ opacity }}>{children}</AbsoluteFill>;
};