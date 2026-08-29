import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { CoastBackdrop, SceneHeading, Wordmark, clamp } from "../components/VideoUI";
import { colors, fonts } from "../styles";

const metrics = [
  { label: "Content fidelity", short: "FID", before: 80.4, after: 88.6, delta: "+8.2", color: colors.ocean, max: 100 },
  { label: "Spatial clean rate", short: "SCR", before: 64.1, after: 91.5, delta: "+27.4 pp", color: colors.coral, max: 100 },
  { label: "Aesthetics", short: "AES", before: 2.95, after: 3.64, delta: "+0.69", color: colors.apricot, max: 5 },
  { label: "Deck design", short: "DES", before: 62.8, after: 71.2, delta: "+8.4", color: colors.deepOcean, max: 100 },
];

const MetricRow: React.FC<{ item: typeof metrics[number]; frame: number; index: number }> = ({ item, frame, index }) => {
  const enter = interpolate(frame, [10 + index * 8, 24 + index * 8], [0, 1], clamp);
  const travel = interpolate(frame, [28 + index * 5, 92 + index * 5], [0, 1], clamp);
  const before = item.before / item.max * 100;
  const after = item.after / item.max * 100;
  const current = interpolate(travel, [0, 1], [before, after]);
  const format = (value: number) => item.short === "AES" ? value.toFixed(2) : value.toFixed(1);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "210px 1fr 150px", alignItems: "center", gap: 24, minHeight: 142, opacity: enter, transform: `translateY(${interpolate(enter, [0, 1], [18, 0])}px)` }}>
      <div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 9 }}><span style={{ color: item.color, fontFamily: fonts.heading, fontSize: 21, fontWeight: 800 }}>{item.short}</span><span style={{ fontSize: 18, fontWeight: 800 }}>{item.label}</span></div>
        <div style={{ marginTop: 7, color: colors.inkSoft, fontFamily: fonts.mono, fontSize: 12 }}>{format(item.before)} → {format(item.after)}</div>
      </div>
      <div style={{ position: "relative", height: 68 }}>
        <div style={{ position: "absolute", left: 0, right: 0, top: 31, height: 4, backgroundColor: colors.line }} />
        <div style={{ position: "absolute", left: `${before}%`, top: 24, width: 17, height: 17, border: `4px solid ${colors.inkSoft}`, borderRadius: "50%", backgroundColor: colors.canvas, transform: "translateX(-50%)" }} />
        <div style={{ position: "absolute", left: `${before}%`, top: 31, width: `${Math.max(0, current - before)}%`, height: 4, backgroundColor: item.color }} />
        <div style={{ position: "absolute", left: `${current}%`, top: 21, width: 24, height: 24, borderRadius: "50%", backgroundColor: item.color, boxShadow: `0 0 0 8px ${item.color}20`, transform: "translateX(-50%)" }} />
        <div style={{ position: "absolute", left: `${current}%`, top: 51, color: item.color, fontFamily: fonts.mono, fontSize: 14, fontWeight: 800, transform: "translateX(-50%)" }}>{format(interpolate(travel, [0, 1], [item.before, item.after]))}</div>
      </div>
      <div style={{ paddingLeft: 19, borderLeft: `5px solid ${item.color}` }}><div style={{ color: item.color, fontFamily: fonts.heading, fontSize: item.short === "SCR" ? 38 : 31, lineHeight: 1, fontWeight: 800 }}>{item.delta}</div><div style={{ marginTop: 6, color: colors.inkSoft, fontSize: 11, fontWeight: 800, textTransform: "uppercase" }}>T0 → ReDeck</div></div>
    </div>
  );
};

const FeedbackLevelsDiagram: React.FC<{ frame: number; delay: number }> = ({ frame, delay }) => {
  const enter = interpolate(frame, [delay, delay + 16], [0, 1], clamp);
  const merge = interpolate(frame, [delay + 18, delay + 48], [0, 1], clamp);
  const branches = [
    { title: "Turn-level critic", role: "What is worth improving across the deck", value: 60.8, color: colors.apricot },
    { title: "Step-level render feedback", role: "What the last edit changed in the layout", value: 80.2, color: colors.ocean },
  ];
  return (
    <div style={{ position: "relative", display: "flex", flexDirection: "column", minHeight: 0, padding: "26px 28px 24px", borderTop: `8px solid ${colors.success}`, backgroundColor: colors.white, boxShadow: "0 14px 38px rgba(38,59,73,0.10)", opacity: enter, transform: `translateY(${interpolate(enter, [0, 1], [20, 0])}px)` }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 20 }}><div><div style={{ fontFamily: fonts.heading, fontSize: 31, fontWeight: 800 }}>Separated responsibilities</div><div style={{ marginTop: 7, color: colors.inkSoft, fontSize: 15 }}>The critic protects intent; the renderer explains each edit.</div></div><div style={{ color: colors.inkSoft, fontFamily: fonts.mono, fontSize: 12, fontWeight: 800 }}>SCR ↑</div></div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 20 }}>
        {branches.map((branch, index) => {
          const progress = interpolate(frame, [delay + 8 + index * 6, delay + 24 + index * 6], [0, 1], clamp);
          return <div key={branch.title} style={{ minWidth: 0, padding: "18px 18px 16px", borderTop: `6px solid ${branch.color}`, backgroundColor: `${branch.color}10`, opacity: progress }}><div style={{ color: branch.color, fontFamily: fonts.heading, fontSize: 21, fontWeight: 800 }}>{branch.title}</div><div style={{ minHeight: 39, marginTop: 7, color: colors.inkSoft, fontSize: 13, lineHeight: 1.35 }}>{branch.role}</div><div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginTop: 13 }}><span style={{ color: branch.color, fontFamily: fonts.heading, fontSize: 39, lineHeight: 1, fontWeight: 800 }}>{branch.value.toFixed(1)}</span><span style={{ color: colors.inkSoft, fontSize: 10, fontWeight: 800 }}>ALONE</span></div></div>;
        })}
      </div>
      <div style={{ position: "relative", height: 55, opacity: merge }}><div style={{ position: "absolute", left: "25%", top: 0, width: "50%", height: 24, borderLeft: `3px solid ${colors.success}`, borderRight: `3px solid ${colors.success}`, borderBottom: `3px solid ${colors.success}` }} /><div style={{ position: "absolute", left: "50%", top: 24, width: 3, height: 25, backgroundColor: colors.success, transform: "translateX(-50%)" }} /><div style={{ position: "absolute", left: "50%", top: 15, padding: "3px 9px", color: colors.success, backgroundColor: colors.white, fontSize: 10, fontWeight: 800, transform: "translateX(-50%)" }}>TOGETHER</div></div>
      <div style={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "1fr 210px", alignItems: "center", gap: 28, padding: "25px 28px", color: colors.white, backgroundColor: colors.success, opacity: merge }}>
        <div><div style={{ fontFamily: fonts.heading, fontSize: 34, fontWeight: 800 }}>Complementary feedback</div><div style={{ marginTop: 8, color: "rgba(255,255,255,0.8)", fontSize: 16 }}>Deck-wide intent + per-edit rendered facts</div><div style={{ display: "flex", gap: 10, marginTop: 22 }}><span style={{ padding: "8px 11px", border: "1px solid rgba(255,255,255,0.32)", backgroundColor: "rgba(255,255,255,0.1)", fontSize: 11, fontWeight: 800 }}>TURN-LEVEL</span><span style={{ padding: "8px 11px", border: "1px solid rgba(255,255,255,0.32)", backgroundColor: "rgba(255,255,255,0.1)", fontSize: 11, fontWeight: 800 }}>STEP-LEVEL</span></div><div style={{ height: 22, marginTop: 25, backgroundColor: "rgba(255,255,255,0.2)" }}><div style={{ width: "91.5%", height: "100%", backgroundColor: colors.white }} /></div></div><div style={{ paddingLeft: 25, borderLeft: "2px solid rgba(255,255,255,0.38)", textAlign: "right" }}><div style={{ fontFamily: fonts.heading, fontSize: 76, lineHeight: 0.9, fontWeight: 800 }}>91.5</div><div style={{ marginTop: 10, fontSize: 11, fontWeight: 800 }}>SPATIAL CLEAN RATE</div><div style={{ marginTop: 9, color: "rgba(255,255,255,0.7)", fontSize: 11 }}>Higher is better ↑</div></div>
      </div>
    </div>
  );
};

const ObservationTimingDiagram: React.FC<{ frame: number; delay: number }> = ({ frame, delay }) => {
  const enter = interpolate(frame, [delay, delay + 16], [0, 1], clamp);
  const rows = [
    { label: "After 8 edits", interval: 8, value: 82.1, color: colors.apricot },
    { label: "After 4 edits", interval: 4, value: 87.4, color: colors.ocean },
    { label: "After every edit", interval: 1, value: 91.5, color: colors.success },
  ];
  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0, padding: "26px 28px 24px", borderTop: `8px solid ${colors.ocean}`, backgroundColor: colors.white, boxShadow: "0 14px 38px rgba(38,59,73,0.10)", opacity: enter, transform: `translateY(${interpolate(enter, [0, 1], [20, 0])}px)` }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 20 }}><div><div style={{ fontFamily: fonts.heading, fontSize: 31, fontWeight: 800 }}>Feedback delay</div><div style={{ marginTop: 7, color: colors.inkSoft, fontSize: 15 }}>Longer delays let local errors compound.</div></div><div style={{ color: colors.inkSoft, fontFamily: fonts.mono, fontSize: 12, fontWeight: 800 }}>SCR ↑</div></div>
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 19, marginTop: 17, color: colors.inkSoft, fontSize: 10, fontWeight: 800, textTransform: "uppercase" }}><span><b style={{ color: colors.ink }}>●</b> edit</span><span><b style={{ color: colors.ocean }}>■</b> render observation</span></div>
      <div style={{ flex: 1, display: "grid", gridTemplateRows: "repeat(3, 1fr)", gap: 13, marginTop: 14 }}>
        {rows.map((row, rowIndex) => {
          const progress = interpolate(frame, [delay + 8 + rowIndex * 8, delay + 32 + rowIndex * 8], [0, 1], clamp);
          return <div key={row.label} style={{ display: "grid", gridTemplateColumns: "122px 1fr 66px", alignItems: "center", gap: 14, padding: "12px 14px", border: `1px solid ${colors.line}`, backgroundColor: row.interval === 1 ? `${colors.success}0d` : "#f8faf9", opacity: progress }}><div><div style={{ fontSize: 15, fontWeight: 800 }}>{row.label}</div><div style={{ marginTop: 5, color: colors.inkSoft, fontSize: 10 }}>{8 / row.interval} observations</div></div><div style={{ display: "grid", gridTemplateColumns: "repeat(8, 1fr)", gap: 5 }}>{Array.from({ length: 8 }, (_, index) => {const observed = (index + 1) % row.interval === 0;return <div key={index} style={{ position: "relative", height: 52 }}><div style={{ position: "absolute", left: 0, right: -5, top: 15, height: 2, backgroundColor: colors.line }} /><div style={{ position: "absolute", left: "50%", top: 9, width: 14, height: 14, borderRadius: "50%", backgroundColor: colors.inkSoft, transform: "translateX(-50%)" }} />{observed ? <div style={{ position: "absolute", left: "50%", top: 29, width: 20, height: 18, display: "grid", placeItems: "center", color: colors.white, border: `2px solid ${row.color}`, backgroundColor: row.color, fontFamily: fonts.mono, fontSize: 9, fontWeight: 800, transform: "translateX(-50%)" }}>R</div> : null}</div>;})}</div><div style={{ color: row.color, fontFamily: fonts.heading, fontSize: 31, fontWeight: 800, textAlign: "right" }}>{row.value.toFixed(1)}</div></div>;
        })}
      </div>
    </div>
  );
};

export const V6ResultsScene: React.FC = () => {
  const frame = useCurrentFrame();
  const mainOpacity = interpolate(frame, [138, 158], [1, 0], clamp);
  const ablationOpacity = interpolate(frame, [145, 166], [0, 1], clamp);

  return (
    <AbsoluteFill style={{ color: colors.ink, backgroundColor: colors.canvas, fontFamily: fonts.body }}>
      <AbsoluteFill style={{ opacity: mainOpacity }}>
        <CoastBackdrop />
        <AbsoluteFill style={{ padding: "48px 70px" }}>
          <SceneHeading index="05" title={<span style={{ color: colors.coral }}>Results</span>} subtitle="ReDeck improves all four DeckQuiz dimensions." />
          <div style={{ position: "absolute", right: 70, top: 128, color: colors.inkSoft, fontFamily: fonts.mono, fontSize: 13, fontWeight: 700 }}>GPT-5.4 · 100 tasks × 3 seeds · matched cap</div>
          <div style={{ position: "absolute", left: 70, top: 160, width: 430, bottom: 60, paddingTop: 26, borderTop: `7px solid ${colors.coral}` }}><div style={{ color: colors.coral, fontSize: 14, fontWeight: 800, textTransform: "uppercase" }}>Primary lift</div><div style={{ marginTop: 22, fontFamily: fonts.heading, fontSize: 115, lineHeight: 0.86, fontWeight: 800 }}>+27.4<span style={{ marginLeft: 8, color: colors.coral, fontSize: 40 }}>pp</span></div><div style={{ marginTop: 22, fontFamily: fonts.heading, fontSize: 31, fontWeight: 800 }}>Spatial Clean Rate</div><div style={{ marginTop: 12, color: colors.inkSoft, fontSize: 19, lineHeight: 1.45 }}>From <b>64.1</b> at initial generation to <b style={{ color: colors.coral }}>91.5</b> after the full feedback loop.</div><div style={{ position: "absolute", left: 0, right: 20, bottom: 32, paddingTop: 17, borderTop: `2px solid ${colors.line}`, color: colors.inkSoft, fontSize: 13, lineHeight: 1.45 }}>Each rail uses its native published scale.</div></div>
          <div style={{ position: "absolute", left: 560, right: 70, top: 150, bottom: 42 }}>{metrics.map((item, index) => <MetricRow key={item.short} item={item} frame={frame} index={index} />)}</div>
        </AbsoluteFill>
      </AbsoluteFill>

      <AbsoluteFill style={{ opacity: ablationOpacity, backgroundColor: "#f3f7f5" }}>
        <AbsoluteFill style={{ padding: "48px 70px" }}>
          <SceneHeading index="05" title={<>Ablation <span style={{ color: colors.ocean }}>Study</span></>} subtitle="Step-level observation and turn-level critique play complementary roles." />
          <div style={{ position: "absolute", left: 70, right: 70, top: 150, bottom: 72, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
            <FeedbackLevelsDiagram frame={frame} delay={158} />
            <ObservationTimingDiagram frame={frame} delay={166} />
          </div>
          <div style={{ position: "absolute", left: 70, right: 70, bottom: 34, display: "flex", justifyContent: "space-between", color: colors.inkSoft, fontFamily: fonts.mono, fontSize: 12 }}><span>Source: paper component and observation-frequency ablations</span><span>Spatial Clean Rate · higher is better</span></div>
        </AbsoluteFill>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const V6CtaScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 17, stiffness: 105 } });
  return (
    <AbsoluteFill style={{ color: colors.white, backgroundColor: colors.ink, fontFamily: fonts.body }}>
      <CoastBackdrop variant="dark" />
      <AbsoluteFill style={{ padding: "82px 108px", transform: `translateY(${interpolate(enter, [0, 1], [14, 0])}px)` }}>
        <SceneHeading index="06" inverse title={<>Open <span style={{ color: colors.seafoam }}>Source</span></>} subtitle="Code, benchmark, and repair examples available online." />
        <div style={{ marginTop: 58 }}><Wordmark inverse fontSize={138} /></div>
        <div style={{ marginTop: 56, padding: "27px 30px", borderLeft: `9px solid ${colors.seafoam}`, color: colors.white, backgroundColor: "rgba(255,255,255,0.09)", fontFamily: fonts.mono, fontSize: 30, fontWeight: 700 }}>python scripts/redeck_repair.py my_slide.html -o repaired/</div>
        <div style={{ marginTop: 45, display: "flex", alignItems: "center", gap: 22, color: colors.sand, fontSize: 26, fontWeight: 800 }}>microsoft.github.io/ReDeck <span style={{ color: "rgba(255,255,255,0.34)" }}>·</span> MIT <span style={{ color: "rgba(255,255,255,0.34)" }}>·</span> Paper <span style={{ color: "rgba(255,255,255,0.34)" }}>·</span> Demo</div>
        <div style={{ position: "absolute", left: 108, right: 108, bottom: 48, display: "flex", justifyContent: "space-between", color: "rgba(255,255,255,0.42)", fontSize: 13 }}><span>AI narration · Fun-CosyVoice3 · emotion-directed synthetic voice</span><span>Music: “Inspired” · Kevin MacLeod · CC BY 4.0 · edited</span></div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const V6_RESULTS_FRAMES = 11 * 30;
export const V6_CTA_FRAMES = 5 * 30;