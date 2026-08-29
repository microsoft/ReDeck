import React from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";
import { SceneHeading, clamp } from "../components/VideoUI";
import { colors, fonts, shadows } from "../styles";

type Pane = "inspect" | "code" | "render" | "facts" | "verify" | "submit";

type MechanismPhase = {
  label: string;
  start: number;
  end: number;
  pane: Pane;
  image: number;
  targetImage?: number;
  selector: string;
  before: string[];
  after: string[];
  facts: Array<[string, string]>;
  decision: string;
  focus?: { left: string; top: string; width: string; height: string; label: string };
};

const images = [
  "trajectory/d78_00.png",
  "trajectory/d78_12.png",
  "trajectory/d78_15.png",
  "trajectory/d78_final.png",
];

const phases: MechanismPhase[] = [
  {
    label: "CHOOSE",
    start: 0,
    end: 54,
    pane: "inspect",
    image: 0,
    selector: "choose the next element",
    before: ["render checkpoint: d78_00", "viewport: 1280 × 720"],
    after: ["persistent issue: fit the full narrative"],
    facts: [["Hard issues", "32"], ["Overflow", "+129px"], ["Out of bounds", "14"], ["Overlaps", "8"], ["Focus", "bottom 42%"], ["Gate", "soft"]],
    decision: "Choose one part of the slide to fix first.",
    focus: { left: "1%", top: "57%", width: "98%", height: "41%", label: "32 ISSUES · BOTTOM 42%" },
  },
  {
    label: "EDIT 1",
    start: 54,
    end: 132,
    pane: "code",
    image: 0,
    selector: "tbody td",
    before: ["padding: 14px 10px 14px 0;", "font-size: 20px;", "line-height: 1.15;"],
    after: ["padding: 4px 8px 4px 0;", "font-size: 14px;", "line-height: 1;"],
    facts: [["Evidence", "endpoint diff"], ["Owner", "tbody td"], ["Scope", "table rows"], ["Protected", "all claims"], ["Policy", "bounded patch"], ["Next", "render"]],
    decision: "Change only the table, then render.",
    focus: { left: "1%", top: "45%", width: "65%", height: "42%", label: "EDIT TARGET · TABLE ROWS" },
  },
  {
    label: "RENDER 1",
    start: 132,
    end: 198,
    pane: "render",
    image: 0,
    targetImage: 1,
    selector: "tbody td",
    before: ["padding: 14px 10px 14px 0;"],
    after: ["padding: 4px 8px 4px 0;"],
    facts: [["Renderer", "Chromium"], ["Checkpoint", "d78_12"], ["Viewport", "1280 × 720"], ["Measure", "pending"], ["Evidence", "archived PNG"], ["Gate", "soft"]],
    decision: "Render the updated slide before making another change.",
    focus: { left: "1%", top: "45%", width: "65%", height: "42%", label: "CHECKPOINT 12 · CHANGED REGION" },
  },
  {
    label: "CHECK 1",
    start: 198,
    end: 270,
    pane: "facts",
    image: 1,
    selector: ".overflow-box",
    before: ["table density reduced"],
    after: ["fixed owner still clips content"],
    facts: [["Hard issues", "32 → 20"], ["Resolved", "12"], ["Overflow", "+129px"], ["Overflow Δ", "0px"], ["Causality", "partial repair"], ["Next owner", ".overflow-box"]],
    decision: "The table improved, but another box still clips text.",
    focus: { left: "55%", top: "59%", width: "43%", height: "36%", label: "REMAINING CLIP OWNER" },
  },
  {
    label: "EDIT 2",
    start: 270,
    end: 348,
    pane: "code",
    image: 1,
    selector: ".overflow-box",
    before: ["position: absolute;", "height: 72px;", "overflow: hidden;"],
    after: ["margin-top: 6px;", "height: auto;", "overflow: visible;"],
    facts: [["Evidence", "endpoint diff"], ["Owner", ".overflow-box"], ["Failure", "clipped text"], ["Position", "absolute → flow"], ["Height", "72px → auto"], ["Next", "render"]],
    decision: "Fix that box without changing the table.",
    focus: { left: "55%", top: "59%", width: "43%", height: "36%", label: "EDIT TARGET · .overflow-box" },
  },
  {
    label: "RENDER 2",
    start: 348,
    end: 414,
    pane: "render",
    image: 1,
    targetImage: 2,
    selector: ".overflow-box",
    before: ["height: 72px;", "overflow: hidden;"],
    after: ["height: auto;", "overflow: visible;"],
    facts: [["Renderer", "Chromium"], ["Checkpoint", "d78_15"], ["Viewport", "1280 × 720"], ["Measure", "pending"], ["Evidence", "archived PNG"], ["Gate", "soft"]],
    decision: "Render again before deciding what to do next.",
    focus: { left: "55%", top: "59%", width: "43%", height: "36%", label: "CHECKPOINT 15 · OWNER RELEASED" },
  },
  {
    label: "CHECK 2",
    start: 414,
    end: 486,
    pane: "facts",
    image: 2,
    selector: "full detector suite",
    before: ["owner released into flow"],
    after: ["small residual overflow remains"],
    facts: [["Hard issues", "20 → 6"], ["Resolved", "14"], ["Overflow", "129 → 25px"], ["Overflow Δ", "−104px"], ["Status", "not clean"], ["Next", "verify"]],
    decision: "Most problems are gone; one small overflow remains.",
    focus: { left: "2%", top: "78%", width: "96%", height: "19%", label: "25PX RESIDUAL · VERIFY REQUIRED" },
  },
  {
    label: "FINAL CHECK",
    start: 486,
    end: 558,
    pane: "verify",
    image: 2,
    targetImage: 3,
    selector: "verify_layout()",
    before: ["overflow · clipping · overlap"],
    after: ["out-of-bounds · text preservation"],
    facts: [["Hard issues", "6 → 0"], ["Overflow", "25 → 0px"], ["Overlaps", "0"], ["Clipping", "0"], ["Out of bounds", "0"], ["Text removed", "0"]],
    decision: "Run the full layout check before saving.",
    focus: { left: "1%", top: "2%", width: "98%", height: "96%", label: "FULL-CANVAS DETECTOR PASS" },
  },
  {
    label: "SAVE",
    start: 558,
    end: 600,
    pane: "submit",
    image: 3,
    selector: "commit_verified_slide()",
    before: ["persistent issue resolved"],
    after: ["render and HTML committed"],
    facts: [["Hard issues", "0"], ["Overflow", "0px"], ["Overlaps", "0"], ["Clipping", "0"], ["Content", "preserved"], ["Status", "accepted"]],
    decision: "Save the slide only after every check passes.",
  },
];

const phaseColor = (pane: Pane) => {
  if (pane === "code") return colors.coral;
  if (pane === "render") return colors.seafoam;
  if (pane === "facts") return colors.ocean;
  if (pane === "verify") return colors.apricot;
  if (pane === "submit") return colors.success;
  return colors.sand;
};

const PaneHeader: React.FC<{ title: string; meta: string; active: boolean; color: string }> = ({ title, meta, active, color }) => (
  <div style={{ height: 48, display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 15px", borderBottom: "1px solid rgba(255,255,255,0.11)", color: active ? colors.white : "rgba(255,255,255,0.46)", backgroundColor: active ? `${color}1d` : "rgba(255,255,255,0.02)" }}>
    <span style={{ fontSize: 12, fontWeight: 800, textTransform: "uppercase" }}>{title}</span>
    <span style={{ color: active ? color : "rgba(255,255,255,0.34)", fontFamily: fonts.mono, fontSize: 10, fontWeight: 800 }}>{meta}</span>
  </div>
);

const AbstractSpaceMap: React.FC<{ phaseIndex: number; color: string }> = ({ phaseIndex, color }) => {
  const cols = 24;
  const rows = 14;
  const clean = phaseIndex >= 7;
  const reduced = phaseIndex >= 5;
  const cells = Array.from({ length: cols * rows }, (_, index) => {
    const row = Math.floor(index / cols);
    const col = index % cols;
    const header = row <= 2 && col >= 1 && col <= 22;
    const leftBody = row >= 4 && row <= (clean ? 10 : 12) && col >= 1 && col <= 14;
    const rightBody = row >= 4 && row <= (clean ? 10 : 11) && col >= 16 && col <= 22;
    const residual = !clean && row >= (reduced ? 11 : 9) && col >= 2 && col <= (reduced ? 18 : 22);
    return { filled: header || leftBody || rightBody || residual, residual };
  });
  return (
    <div style={{ padding: "13px 14px 12px", borderBottom: "1px solid rgba(255,255,255,0.1)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", color: "rgba(255,255,255,0.42)", fontSize: 9, fontWeight: 800, textTransform: "uppercase" }}>
        <span>Layout anchor A_t · filtered DOM geometry</span><span>24 × 14</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${cols}, 1fr)`, gap: 1.5, marginTop: 9, padding: 6, backgroundColor: "rgba(15,23,42,0.75)" }}>
        {cells.map((cell, index) => <div key={index} style={{ height: 5, backgroundColor: cell.filled ? cell.residual ? colors.error : color : "rgba(255,255,255,0.08)", opacity: cell.filled ? 0.9 : 0.6 }} />)}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 7, color: "rgba(255,255,255,0.38)", fontFamily: fonts.mono, fontSize: 9 }}>
        <span>rendered spatial state</span><span style={{ color: clean ? colors.success : colors.error }}>{clean ? "canvas fit recovered" : reduced ? "residual bottom density" : "dense bottom region"}</span>
      </div>
    </div>
  );
};

export const V6MechanismScene: React.FC = () => {
  const frame = useCurrentFrame();
  const activeIndex = phases.findIndex((phase) => frame >= phase.start && frame < phase.end);
  const safeIndex = activeIndex < 0 ? phases.length - 1 : activeIndex;
  const phase = phases[safeIndex];
  const localFrame = frame - phase.start;
  const duration = phase.end - phase.start;
  const color = phaseColor(phase.pane);
  const phaseIn = interpolate(localFrame, [0, 6], [0, 1], clamp);
  const transition = phase.targetImage === undefined
    ? 1
    : interpolate(localFrame, [8, Math.min(30, duration - 8)], [0, 1], clamp);
  const scan = phase.pane === "render" || phase.pane === "verify"
    ? interpolate(localFrame, [7, duration - 7], [0, 1], clamp)
    : 0;

  return (
    <AbsoluteFill style={{ color: colors.white, backgroundColor: "#071b22", backgroundImage: "linear-gradient(rgba(101,189,186,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(101,189,186,0.06) 1px, transparent 1px)", backgroundSize: "44px 44px", fontFamily: fonts.body }}>
      <AbsoluteFill style={{ padding: "38px 58px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <div style={{ flex: 1 }}><SceneHeading index="03" inverse title={<>Our <span style={{ color: colors.seafoam }}>Approach</span></>} subtitle="Observe every edit, then decide what to do next." /></div>
          <div style={{ marginLeft: "auto", color, fontFamily: fonts.mono, fontSize: 15, fontWeight: 800 }}>{String(safeIndex + 1).padStart(2, "0")} / {phases.length}</div>
        </div>

        <div style={{ position: "absolute", left: 58, right: 58, top: 120, height: 48, display: "flex", alignItems: "center", gap: 17, padding: "0 18px", borderTop: `2px solid ${color}`, borderBottom: "1px solid rgba(255,255,255,0.11)", backgroundColor: `${color}10` }}>
          <span style={{ color, fontSize: 11, fontWeight: 800, textTransform: "uppercase" }}>Two scales, separate roles</span>
          <span style={{ width: 1, height: 25, backgroundColor: "rgba(255,255,255,0.16)" }} />
          <span style={{ fontSize: 17, fontWeight: 800 }}>The critic decides what matters; the renderer shows what the last edit did.</span>
          <span style={{ marginLeft: "auto", color: "rgba(255,255,255,0.42)", fontSize: 10, fontWeight: 800 }}>GLOBAL INTENT · LOCAL CAUSALITY · SUBMISSION GATE</span>
        </div>

        <div style={{ position: "absolute", left: 58, right: 58, top: 186, height: 698, display: "grid", gridTemplateColumns: "500px 1fr 450px", gap: 14 }}>
          <div style={{ overflow: "hidden", border: `2px solid ${phase.pane === "code" ? color : "rgba(255,255,255,0.13)"}`, backgroundColor: "rgba(5,20,26,0.92)", boxShadow: phase.pane === "code" ? `0 0 0 7px ${color}15` : "none" }}>
            <PaneHeader title="Atomic edit" meta="slide.html" active={phase.pane === "code"} color={color} />
            <div style={{ padding: "26px 24px", fontFamily: fonts.mono }}>
              <div style={{ height: 34, color: phase.pane === "code" ? color : "rgba(255,255,255,0.52)", fontSize: 21, fontWeight: 800 }}>{phase.selector}</div>
              <div style={{ height: 218, marginTop: 14 }}>
                {phase.before.map((line, index) => (
                  <div key={`before-${line}`} style={{ display: "grid", gridTemplateColumns: "29px 1fr", minHeight: 53, alignItems: "center", padding: "6px 10px", color: "#ef9a9f", backgroundColor: "rgba(197,87,94,0.12)", fontSize: 18, lineHeight: 1.35, opacity: phaseIn }}>
                    <span>{index === 0 ? "−" : " "}</span><span>{line}</span>
                  </div>
                ))}
              </div>
              <div style={{ height: 218, marginTop: 12 }}>
                {phase.after.map((line, index) => (
                  <div key={`after-${line}`} style={{ display: "grid", gridTemplateColumns: "29px 1fr", minHeight: 53, alignItems: "center", padding: "6px 10px", color: "#8bdad0", backgroundColor: "rgba(101,189,186,0.12)", fontSize: 18, lineHeight: 1.35, opacity: phaseIn }}>
                    <span>{index === 0 ? "+" : " "}</span><span>{line}</span>
                  </div>
                ))}
              </div>
              <div style={{ position: "absolute", left: 24, right: 24, bottom: 24, padding: "17px 18px", borderLeft: `6px solid ${color}`, color: colors.white, backgroundColor: `${color}13`, fontSize: 16, lineHeight: 1.38, fontWeight: 800 }}>
                {phase.pane === "code" ? "One action keeps one consequence attributable." : "Compare source and rendered effect."}
              </div>
            </div>
          </div>

          <div style={{ position: "relative", overflow: "hidden", border: `5px solid ${phase.pane === "render" || phase.pane === "verify" ? color : colors.white}`, backgroundColor: colors.white, boxShadow: shadows.slide }}>
            <div style={{ position: "absolute", zIndex: 5, left: 0, right: 0, top: 0 }}>
              <PaneHeader title="Rendered consequence" meta="Chromium · 1280 × 720" active={phase.pane === "render" || phase.pane === "verify"} color={color} />
            </div>
            {images.map((src, index) => {
              let opacity = index === phase.image ? 1 : 0;
              if (phase.targetImage !== undefined) {
                opacity = index === phase.image ? 1 - transition : index === phase.targetImage ? transition : 0;
              }
              if (opacity <= 0) return null;
              return <Img key={src} src={staticFile(src)} style={{ position: "absolute", left: 0, right: 0, top: 48, width: "100%", height: "calc(100% - 48px)", objectFit: "contain", opacity }} />;
            })}
            {phase.focus ? (
              <div style={{ position: "absolute", zIndex: 7, left: 0, right: 0, top: 48, bottom: 0 }}>
                <div style={{ position: "absolute", left: phase.focus.left, top: phase.focus.top, width: phase.focus.width, height: phase.focus.height, border: `5px solid ${phase.pane === "verify" ? colors.apricot : phase.pane === "submit" ? colors.success : colors.error}`, backgroundColor: phase.pane === "verify" ? "rgba(250,162,111,0.07)" : "rgba(197,87,94,0.07)", boxShadow: `0 0 0 8px ${phase.pane === "verify" ? "rgba(250,162,111,0.12)" : "rgba(197,87,94,0.11)"}`, opacity: phaseIn }}>
                  <div style={{ position: "absolute", left: -3, top: -32, padding: "7px 10px", color: colors.white, backgroundColor: phase.pane === "verify" ? colors.apricot : colors.error, fontSize: 11, fontWeight: 800, whiteSpace: "nowrap" }}>{phase.focus.label}</div>
                </div>
              </div>
            ) : null}
            {scan > 0 ? <div style={{ position: "absolute", zIndex: 6, left: 0, right: 0, top: `${48 + scan * 642}px`, height: 4, backgroundColor: color, boxShadow: `0 -20px 45px ${color}75` }} /> : null}
            <div style={{ position: "absolute", zIndex: 7, left: 14, bottom: 14, padding: "8px 11px", borderLeft: `5px solid ${color}`, color: colors.ink, backgroundColor: "rgba(255,255,255,0.94)", fontFamily: fonts.mono, fontSize: 12, fontWeight: 800 }}>
              {images[phase.targetImage !== undefined && transition > 0.5 ? phase.targetImage : phase.image].replace("trajectory/", "")}
            </div>
          </div>

          <div style={{ overflow: "hidden", border: `2px solid ${phase.pane === "facts" || phase.pane === "verify" || phase.pane === "submit" ? color : "rgba(255,255,255,0.13)"}`, backgroundColor: "rgba(5,20,26,0.92)", boxShadow: phase.pane === "facts" ? `0 0 0 7px ${color}15` : "none" }}>
            <PaneHeader title="Causal observation" meta={phase.label} active={phase.pane === "facts" || phase.pane === "verify" || phase.pane === "submit"} color={color} />
            <AbstractSpaceMap phaseIndex={safeIndex} color={phase.pane === "submit" ? colors.success : color} />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gridTemplateRows: "repeat(3, 76px)", gap: 7, padding: "13px 14px" }}>
              {phase.facts.map(([label, value], index) => (
                <div key={label} style={{ minWidth: 0, padding: "10px 11px", border: "1px solid rgba(255,255,255,0.1)", backgroundColor: "rgba(255,255,255,0.035)", opacity: interpolate(localFrame, [index * 2, index * 2 + 6], [0, 1], clamp) }}>
                  <div style={{ color: "rgba(255,255,255,0.4)", fontSize: 9, fontWeight: 800, textTransform: "uppercase" }}>{label}</div>
                  <div style={{ marginTop: 7, overflow: "hidden", color: phase.pane === "submit" ? colors.success : colors.white, fontFamily: value.match(/[0-9.+→×−]/) ? fonts.mono : fonts.body, fontSize: value.length > 14 ? 15 : 20, lineHeight: 1.1, fontWeight: 800, whiteSpace: "nowrap", textOverflow: "ellipsis" }}>{value}</div>
                </div>
              ))}
            </div>
            <div style={{ margin: "0 14px", padding: "14px 15px", borderTop: `3px solid ${color}`, color: colors.white, backgroundColor: `${color}13` }}>
              <div style={{ color, fontSize: 9, fontWeight: 800, textTransform: "uppercase" }}>Decision grounded in this render</div>
              <div style={{ marginTop: 7, fontSize: 15, lineHeight: 1.3, fontWeight: 800 }}>{phase.decision}</div>
            </div>
          </div>
        </div>

        <div style={{ position: "absolute", left: 58, right: 58, bottom: 31, height: 122, padding: "17px 25px", borderTop: "1px solid rgba(255,255,255,0.14)", backgroundColor: "rgba(5,20,26,0.88)" }}>
          <div style={{ position: "absolute", left: 70, right: 70, top: 43, height: 2, backgroundColor: "rgba(255,255,255,0.15)" }} />
          <div style={{ position: "absolute", left: 70, top: 43, width: `${safeIndex / (phases.length - 1) * 92}%`, height: 2, backgroundColor: colors.success }} />
          <div style={{ display: "grid", gridTemplateColumns: `repeat(${phases.length}, 1fr)` }}>
            {phases.map((item, index) => {
              const active = index === safeIndex;
              const complete = index < safeIndex;
              const itemColor = phaseColor(item.pane);
              return (
                <div key={item.label} style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                  <div style={{ width: active ? 18 : 12, height: active ? 18 : 12, marginTop: active ? 17 : 20, border: `3px solid ${active ? itemColor : complete ? colors.success : "rgba(255,255,255,0.22)"}`, borderRadius: "50%", backgroundColor: active ? itemColor : complete ? colors.success : "#071b22", boxShadow: active ? `0 0 0 7px ${itemColor}20` : "none" }} />
                  <div style={{ marginTop: 10, color: active ? itemColor : complete ? colors.success : "rgba(255,255,255,0.36)", fontSize: 10, fontWeight: 800, whiteSpace: "nowrap" }}>{item.label}</div>
                </div>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const V6_MECHANISM_FRAMES = 20 * 30;