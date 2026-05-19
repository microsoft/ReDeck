import React from "react";
import {
  AbsoluteFill,
  Img,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";

/* ===== Color Tokens ===== */
const BG = "#06080f";
const ACCENT = "#7c5cfc";
const ACCENT2 = "#4ae3b5";
const RED = "#f74a6a";
const TEXT = "#e6edf3";
const DIM = "#8b949e";
const MUTED = "#484f58";

const baseFill: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  background: BG,
  fontFamily: "'Outfit', sans-serif",
  color: TEXT,
};

/* ===== Helpers ===== */
const cl = { extrapolateRight: "clamp" as const, extrapolateLeft: "clamp" as const };
const fade = (f: number, s: number, d = 20) => interpolate(f, [s, s + d], [0, 1], cl);
const slideUp = (f: number, s: number, d = 20, dist = 30) => interpolate(f, [s, s + d], [dist, 0], cl);

/* ================================================================
   Scene 1: Hook — 2×2 Defect Grid (0–240f = 0–8s)
   ================================================================ */
const HookScene: React.FC = () => {
  const frame = useCurrentFrame();
  const title1Op = fade(frame, 0, 25);
  const title2Op = fade(frame, 24, 20);

  const defects = [
    { src: staticFile("crops/overlap.png"), label: "Overlap" },
    { src: staticFile("crops/text_overflow.png"), label: "Text Overflow" },
    { src: staticFile("crops/clipping.png"), label: "Clipping" },
    { src: staticFile("crops/low_contrast.png"), label: "Low Contrast" },
  ];

  // Title starts centered, smoothly slides up to become header above grid
  const titleY = interpolate(frame, [50, 85], [0, -460], cl);
  const titleScale = interpolate(frame, [50, 85], [1, 0.55], cl);

  return (
    <AbsoluteFill style={{ ...baseFill, flexDirection: "column" }}>
      {/* Title — slides up and shrinks to become header */}
      <div style={{
        position: "absolute", top: "50%", left: "50%",
        transform: `translate(-50%, ${titleY}px) scale(${titleScale})`,
        textAlign: "center", zIndex: 10, width: "100%",
      }}>
        <p style={{ fontSize: 42, fontWeight: 700, opacity: title1Op, margin: 0 }}>
          LLMs can generate presentation slides...
        </p>
        <p style={{ fontSize: 42, fontWeight: 700, opacity: title2Op, marginTop: 8 }}>
          but many <span style={{ color: RED }}>quality issues</span> remain:
        </p>
      </div>

      {/* 2×2 grid — fades in after title has moved up */}
      {frame >= 78 && (
        <div style={{
          position: "absolute", top: 190, left: "50%", transform: "translateX(-50%)",
          display: "grid", gridTemplateColumns: "repeat(2, 810px)",
          gridTemplateRows: "repeat(2, 380px)", gap: 16,
        }}>
          {defects.map((d, i) => {
            const delay = 82 + i * 12;
            return (
              <div key={i} style={{
                opacity: fade(frame, delay, 18),
                transform: `translateY(${slideUp(frame, delay, 18, 25)}px)`,
                position: "relative", borderRadius: 12, overflow: "hidden",
                border: `2px solid ${RED}`,
              }}>
                <Img src={d.src} style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
                <div style={{
                  position: "absolute", bottom: 0, left: 0, right: 0,
                  background: "rgba(0,0,0,0.75)", padding: "10px 16px",
                  display: "flex", justifyContent: "center", alignItems: "center",
                }}>
                  <span style={{ fontSize: 20, fontWeight: 700, color: "#fff", textTransform: "uppercase", letterSpacing: 1.5 }}>{d.label}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </AbsoluteFill>
  );
};

/* ================================================================
   Scene 2: Solution — Brand Reveal + Core Idea (240–480f = 8–16s)
   ================================================================ */
const SolutionScene: React.FC = () => {
  const frame = useCurrentFrame();
  const logoOp = fade(frame, 0, 30);
  const logoY = slideUp(frame, 0, 30, 50);
  const subOp = fade(frame, 25, 25);
  const ideaOp = fade(frame, 60, 25);
  const ideaY = slideUp(frame, 60, 25, 30);
  const step1Op = fade(frame, 100, 20);
  const step2Op = fade(frame, 130, 20);
  const step3Op = fade(frame, 160, 20);

  const steps = [
    { icon: "🔍", title: "Detect", desc: "Render slide and run spatial probes on the DOM" },
    { icon: "✏️", title: "Edit", desc: "Apply targeted fix to the identified element" },
    { icon: "✅", title: "Verify", desc: "Re-render and confirm no regressions" },
  ];
  const stepOps = [step1Op, step2Op, step3Op];

  return (
    <AbsoluteFill style={{ ...baseFill, flexDirection: "column" }}>
      <div style={{
        position: "absolute", width: "120%", height: "120%",
        background: "radial-gradient(ellipse 80% 60% at 50% 40%, rgba(124,92,252,0.15), transparent 70%)",
      }} />
      <div style={{
        textAlign: "center", position: "relative", zIndex: 1,
        transform: `translateY(${logoY}px)`, opacity: logoOp, marginBottom: 40,
      }}>
        <h1 style={{ fontSize: 96, fontWeight: 900, letterSpacing: -3, lineHeight: 1.05, margin: 0 }}>
          Re<span style={{
            background: `linear-gradient(135deg, ${ACCENT}, ${ACCENT2})`,
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
          }}>Deck</span>
        </h1>
      </div>

      <div style={{
        textAlign: "center", position: "relative", zIndex: 1,
        opacity: ideaOp, transform: `translateY(${ideaY}px)`, marginBottom: 50,
      }}>
        <p style={{ fontSize: 28, color: TEXT, fontWeight: 600, margin: "0 0 8px" }}>
          Render-grounded refinement for <span style={{ color: ACCENT2 }}>reliable slide generation</span>
        </p>
        <p style={{ fontSize: 18, color: DIM, margin: 0 }}>
          An edit–render–verify loop that detects and repairs spatial defects automatically.
        </p>
      </div>

      <div style={{ display: "flex", gap: 40, position: "relative", zIndex: 1 }}>
        {steps.map((s, i) => (
          <div key={i} style={{
            flex: 1, opacity: stepOps[i],
            transform: `translateY(${slideUp(useCurrentFrame(), 100 + i * 30, 20, 25)}px)`,
            background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: 16, padding: "28px 24px", textAlign: "center",
          }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>{s.icon}</div>
            <div style={{ fontSize: 22, fontWeight: 700, color: ACCENT2, marginBottom: 8 }}>{s.title}</div>
            <div style={{ fontSize: 15, color: DIM, lineHeight: 1.5 }}>{s.desc}</div>
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};

/* ================================================================
   Scene 3: Before/After Showcase (side-by-side comparison)
   ================================================================ */
const ShowcaseScene: React.FC<{ beforeSrc: string; afterSrc: string; caption: string }> = ({ beforeSrc, afterSrc, caption }) => {
  const frame = useCurrentFrame();
  const leftOp = fade(frame, 5, 20);
  const leftX = slideUp(frame, 5, 20, 30);
  const arrowOp = fade(frame, 30, 15);
  const rightOp = fade(frame, 40, 20);
  const rightX = slideUp(frame, 40, 20, 30);
  const captionOp = fade(frame, 55, 15);

  const cardStyle: React.CSSProperties = {
    flex: 1, position: "relative", borderRadius: 14, overflow: "hidden",
  };

  return (
    <AbsoluteFill style={{ ...baseFill, flexDirection: "column", padding: "50px 60px 40px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 0, flex: 1 }}>
        {/* Before */}
        <div style={{ ...cardStyle, opacity: leftOp, transform: `translateX(-${slideUp(frame, 5, 20, 30)}px)`, border: `2px solid ${RED}` }}>
          <div style={{ position: "absolute", top: 12, left: 14, zIndex: 5, padding: "5px 16px", borderRadius: 999, background: "rgba(247,74,106,0.9)", color: "#fff", fontSize: 13, fontWeight: 700, textTransform: "uppercase", letterSpacing: 1.5 }}>Before</div>
          <Img src={staticFile(beforeSrc)} style={{ width: "100%", height: "100%", objectFit: "contain", display: "block", background: "#0a0e18" }} />
        </div>

        {/* Arrow */}
        <div style={{ opacity: arrowOp, padding: "0 20px", display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
          <svg width="48" height="48" viewBox="0 0 48 48" fill="none" stroke={ACCENT2} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10 24h28M30 16l8 8-8 8" />
          </svg>
          <span style={{ fontSize: 12, fontWeight: 700, color: ACCENT2, textTransform: "uppercase", letterSpacing: 2 }}>ReDeck</span>
        </div>

        {/* After */}
        <div style={{ ...cardStyle, opacity: rightOp, transform: `translateX(${slideUp(frame, 40, 20, 30)}px)`, border: `2px solid ${ACCENT2}` }}>
          <div style={{ position: "absolute", top: 12, right: 14, zIndex: 5, padding: "5px 16px", borderRadius: 999, background: "rgba(74,227,181,0.9)", color: "#06080f", fontSize: 13, fontWeight: 700, textTransform: "uppercase", letterSpacing: 1.5 }}>After</div>
          <Img src={staticFile(afterSrc)} style={{ width: "100%", height: "100%", objectFit: "contain", display: "block", background: "#0a0e18" }} />
        </div>
      </div>

      <div style={{ textAlign: "center", opacity: captionOp, marginTop: 16 }}>
        <p style={{ fontSize: 20, fontWeight: 600, color: DIM, margin: 0 }}>{caption}</p>
      </div>
    </AbsoluteFill>
  );
};

/* ================================================================
   Scene 4: Results — Paper Data (900–1200f = 30–40s)
   ================================================================ */
const ResultsScene: React.FC = () => {
  const frame = useCurrentFrame();

  const metrics = [
    { label: "Fidelity", value: "88.6", delta: "+11.8", vs: "DeepPresenter" },
    { label: "Spatial Clean\nRate", value: "91.5%", delta: "+3.3", vs: "SlideTailor" },
    { label: "Aesthetics", value: "3.64", delta: "+0.17", vs: "DeepPresenter" },
    { label: "Design", value: "71.2", delta: "+14.8", vs: "SlideTailor" },
  ];

  const systems = [
    { name: "ReDeck", rate: 0.72, ours: true },
    { name: "DeepPresenter", rate: 0.59, ours: false },
    { name: "SlideTailor", rate: 0.51, ours: false },
    { name: "SlideGen", rate: 0.43, ours: false },
  ];

  const humanPrefs = [
    { vs: "SlideGen", rate: "87%", n: "13/15" },
    { vs: "SlideTailor", rate: "80%", n: "12/15" },
    { vs: "DeepPresenter", rate: "73%", n: "11/15" },
  ];

  return (
    <AbsoluteFill style={{ ...baseFill, flexDirection: "column", padding: "0 80px" }}>
      <div style={{ opacity: fade(frame, 0, 15), marginBottom: 8 }}>
        <p style={{ fontSize: 14, fontWeight: 600, textTransform: "uppercase", letterSpacing: 4, color: ACCENT, margin: 0 }}>Results</p>
      </div>
      <h2 style={{ fontSize: 40, fontWeight: 800, letterSpacing: -1, margin: "0 0 10px", opacity: fade(frame, 5, 15) }}>
        DeckQuiz Benchmark
      </h2>
      <p style={{ fontSize: 16, color: DIM, margin: "0 0 28px", opacity: fade(frame, 10, 15) }}>
        GPT-5.4 · 100 tasks × 3 seeds · matched per-task call budget
      </p>

      <div style={{ display: "flex", gap: 16, marginBottom: 28 }}>
        {metrics.map((m, i) => {
          const delay = 20 + i * 12;
          return (
            <div key={i} style={{
              flex: 1, opacity: fade(frame, delay, 18), transform: `translateY(${slideUp(frame, delay, 18, 20)}px)`,
              background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: 14, padding: "22px 16px", textAlign: "center",
              display: "flex", flexDirection: "column", alignItems: "center",
            }}>
              <div style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: 2, color: DIM, height: 36, display: "flex", alignItems: "center", whiteSpace: "pre-line" }}>{m.label}</div>
              <div style={{ fontSize: 52, fontWeight: 800, color: ACCENT2, lineHeight: 1.1, margin: "8px 0" }}>{m.value}</div>
              <div style={{ fontSize: 13, color: DIM, lineHeight: 1.4 }}>
                vs {m.vs} <span style={{ color: ACCENT2, fontWeight: 700 }}>{m.delta}</span>
              </div>
            </div>
          );
        })}
      </div>

      <div style={{ display: "flex", gap: 20, opacity: fade(frame, 80, 20) }}>
        <div style={{ flex: 1.2, background: "rgba(255,255,255,0.03)", borderRadius: 14, border: "1px solid rgba(255,255,255,0.08)", padding: "18px 24px" }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: DIM, textTransform: "uppercase", letterSpacing: 2, marginBottom: 6 }}>Cross-Domain Win Rate</div>
          <div style={{ fontSize: 11, color: MUTED, marginBottom: 12 }}>PresentBench · 5 domains · 3 models × 2 seeds</div>
          {systems.map((s, i) => {
            const delay = 90 + i * 8;
            const barW = interpolate(frame, [delay, delay + 25], [0, s.rate * 100], cl);
            return (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
                <span style={{ minWidth: 130, fontSize: 14, fontWeight: 600, color: s.ours ? ACCENT2 : TEXT }}>{s.name}</span>
                <div style={{ flex: 1, height: 22, background: "rgba(255,255,255,0.06)", borderRadius: 6, overflow: "hidden" }}>
                  <div style={{
                    width: `${barW}%`, height: "100%", borderRadius: 6,
                    background: s.ours ? `linear-gradient(90deg, rgba(74,227,181,0.4), ${ACCENT2})` : "rgba(255,255,255,0.12)",
                    display: "flex", alignItems: "center", justifyContent: "flex-end", paddingRight: 8,
                    fontSize: 11, fontWeight: 700, color: s.ours ? "#06080f" : DIM,
                  }}>{s.rate.toFixed(2)}</div>
                </div>
              </div>
            );
          })}
        </div>

        <div style={{ flex: 1, background: "rgba(255,255,255,0.03)", borderRadius: 14, border: "1px solid rgba(255,255,255,0.08)", padding: "18px 24px" }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: DIM, textTransform: "uppercase", letterSpacing: 2, marginBottom: 6 }}>Human Pairwise Preference</div>
          <div style={{ fontSize: 11, color: MUTED, marginBottom: 16 }}>GPT-5.4 · 15 tasks · 3 blinded annotators</div>
          <div style={{ display: "flex", gap: 12 }}>
            {humanPrefs.map((h, i) => {
              const delay = 110 + i * 10;
              return (
                <div key={i} style={{
                  flex: 1, opacity: fade(frame, delay, 15), textAlign: "center",
                  background: "rgba(74,227,181,0.06)", border: "1px solid rgba(74,227,181,0.15)",
                  borderRadius: 10, padding: "14px 8px",
                }}>
                  <div style={{ fontSize: 11, color: DIM, textTransform: "uppercase", letterSpacing: 1, marginBottom: 6 }}>vs {h.vs}</div>
                  <div style={{ fontSize: 32, fontWeight: 800, color: ACCENT2 }}>{h.rate}</div>
                  <div style={{ fontSize: 12, color: MUTED, marginTop: 4 }}>({h.n})</div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

/* ================================================================
   Scene 5: Outro (1200–1320f = 40–44s)
   ================================================================ */
const OutroScene: React.FC = () => {
  const frame = useCurrentFrame();
  const op = fade(frame, 0, 30);
  const scale = interpolate(frame, [0, 30], [0.92, 1], cl);

  return (
    <AbsoluteFill style={baseFill}>
      <div style={{ position: "absolute", width: "120%", height: "120%", background: "radial-gradient(ellipse 80% 60% at 50% 40%, rgba(124,92,252,0.2), transparent 70%)" }} />
      <div style={{ textAlign: "center", opacity: op, transform: `scale(${scale})`, position: "relative", zIndex: 1 }}>
        <h1 style={{ fontSize: 84, fontWeight: 900, letterSpacing: -3, margin: "0 0 16px" }}>
          Re<span style={{ background: `linear-gradient(135deg, ${ACCENT}, ${ACCENT2})`, WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>Deck</span>
        </h1>
        <p style={{ fontSize: 22, color: DIM, margin: "0 0 8px" }}>Step-Level Render-Grounded Refinement</p>
        <p style={{ fontSize: 16, color: MUTED, margin: "0 0 32px" }}>Research preview · Code · Demo</p>
        <div style={{ display: "inline-flex", gap: 16 }}>
          {["Paper", "Code", "Demo"].map((l) => (
            <div key={l} style={{ padding: "12px 32px", borderRadius: 999, background: l === "Paper" ? ACCENT : "transparent", border: l === "Paper" ? "none" : "1px solid rgba(255,255,255,0.3)", color: "white", fontSize: 18, fontWeight: 600 }}>{l}</div>
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};

/* ================================================================
   Main: 44s @ 30fps = 1320 frames
   Scene 1: Hook           0-240    (8s)
   Scene 2: Solution       240-480  (8s)
   Scene 3a: Verdict       480-585  (3.5s)
   Scene 3b: Table overlap 585-690  (3.5s)
   Scene 3c: Box overlap   690-795  (3.5s)
   Scene 3d: Shattered     795-900  (3.5s)
   Scene 4: Results        900-1200 (10s)
   Scene 5: Outro          1200-1320 (4s)
   ================================================================ */
export const RedeckPromo: React.FC = () => {
  return (
    <AbsoluteFill style={{ background: BG }}>
      <Sequence from={0} durationInFrames={240}><HookScene /></Sequence>
      <Sequence from={240} durationInFrames={240}><SolutionScene /></Sequence>
      <Sequence from={480} durationInFrames={105}>
        <ShowcaseScene beforeSrc="slides/case1_before.png" afterSrc="slides/case1_after.png" caption="Verdict boxes overlap → Clean two-column comparison" />
      </Sequence>
      <Sequence from={585} durationInFrames={105}>
        <ShowcaseScene beforeSrc="slides/case2_before.png" afterSrc="slides/case2_after.png" caption="Table rows overlap at bottom → Complete benchmark table" />
      </Sequence>
      <Sequence from={690} durationInFrames={105}>
        <ShowcaseScene beforeSrc="slides/case3_before.png" afterSrc="slides/case3_after.png" caption="Content boxes overlap bullets → Clean dual-column layout" />
      </Sequence>
      <Sequence from={795} durationInFrames={105}>
        <ShowcaseScene beforeSrc="slides/case4_before.png" afterSrc="slides/case4_after.png" caption="Shattered table fragments → Coherent analysis text" />
      </Sequence>
      <Sequence from={900} durationInFrames={300}><ResultsScene /></Sequence>
      <Sequence from={1200} durationInFrames={120}><OutroScene /></Sequence>
    </AbsoluteFill>
  );
};
