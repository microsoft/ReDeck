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
import { CoastBackdrop, SceneHeading, clamp } from "../components/VideoUI";
import { colors, fonts, shadows } from "../styles";

type TrajectoryAction = "start" | "edit" | "css" | "rollback";

type TrajectoryFrame = {
  src: string;
  action: TrajectoryAction;
  label: string;
  accepted?: boolean;
};

type OverlayKind = "error" | "change" | "verified";

type OverlayRegion = {
  left: string;
  top: string;
  width: string;
  height: string;
  label: string;
  kind: OverlayKind;
};

type ShowcaseCase = {
  id: string;
  kind: string;
  title: string;
  color: string;
  run: string;
  rollbacks: number;
  summary: string;
  frames: TrajectoryFrame[];
};

const makeActions = (
  count: number,
  rollbackIndices: number[] = [],
  cssIndices: number[] = [],
): TrajectoryAction[] => Array.from({ length: count }, (_, index) => {
  if (rollbackIndices.includes(index)) return "rollback";
  if (cssIndices.includes(index)) return "css";
  return "edit";
});

const makeRunFrames = (id: string, actions: TrajectoryAction[]): TrajectoryFrame[] => [
  {
    src: `trajectory/${id}_run_before.png`,
    action: "start",
    label: "INITIAL RENDER",
  },
  ...actions.map((action, index) => ({
    src: `trajectory/${id}_run_step_${String(index).padStart(2, "0")}.png`,
    action,
    label: index === actions.length - 1
      ? `ACTION ${String(index + 1).padStart(2, "0")} · ACCEPTED`
      : action === "rollback"
        ? `ACTION ${String(index + 1).padStart(2, "0")} · ROLLBACK`
        : action === "css"
          ? `ACTION ${String(index + 1).padStart(2, "0")} · CSS PATCH`
          : `ACTION ${String(index + 1).padStart(2, "0")} · APPLY EDITS`,
    accepted: index === actions.length - 1,
  })),
];

const cases: ShowcaseCase[] = [
  {
    id: "d181",
    kind: "Shared layout budget",
    title: "Fix the shared budget, not just the clipped element.",
    color: colors.apricot,
    run: "full_v3_simplified",
    rollbacks: 1,
    summary: "The table, notes, and KPI rail share one spatial budget.",
    frames: makeRunFrames("d181", makeActions(10, [4])),
  },
  {
    id: "d120",
    kind: "Layout ownership",
    title: "Give every annotation a clear layout owner.",
    color: colors.sunset,
    run: "directional_guidance_v11",
    rollbacks: 0,
    summary: "Explicit ownership separates the table, KPI, and callout.",
    frames: makeRunFrames("d120", makeActions(12)),
  },
  {
    id: "d171",
    kind: "Shared-rule leverage",
    title: "Repair repeated failures through one shared rule.",
    color: colors.deepOcean,
    run: "full_v3_simplified",
    rollbacks: 0,
    summary: "A repeated defect becomes one shared-rule repair.",
    frames: makeRunFrames("d171", makeActions(7)),
  },
];

const CASE_FRAMES = 210;
const TRAJECTORY_PLAYBACK_FRAMES = 184;
const SUMMARY_START = CASE_FRAMES * cases.length;

const actionColor = (frame: TrajectoryFrame, color: string) => {
  if (frame.accepted) return colors.success;
  if (frame.action === "rollback") return colors.error;
  return color;
};

const actionTitle = (frame: TrajectoryFrame) => {
  if (frame.action === "start") return "Establish a rendered baseline.";
  if (frame.accepted) return "Only validated progress becomes persistent.";
  if (frame.action === "rollback") return "Rendered evidence rejects a harmful direction.";
  return "One action produces one attributable observation.";
};

const actionDetail = (frame: TrajectoryFrame) => {
  if (frame.action === "start") return "The run starts from the generated slide and a localized failure hypothesis.";
  if (frame.accepted) return "This same-run output passes validation and becomes the next saved state.";
  if (frame.action === "rollback") return "The observed regression is reverted before another action is chosen.";
  return "The agent sees the rendered consequence before choosing its next action.";
};

const getOverlayRegions = (
  caseId: string,
  stateIndex: number,
  frame: TrajectoryFrame,
): OverlayRegion[] => {
  if (frame.accepted) {
    return [{ left: "2%", top: "7%", width: "96%", height: "88%", label: "VERIFIED · ACCEPTED OUTPUT", kind: "verified" }];
  }

  if (frame.action === "rollback") {
    return caseId === "d181"
      ? [{ left: "72%", top: "27%", width: "26%", height: "68%", label: "REGRESSION · RIGHT-COLUMN REFLOW", kind: "error" }]
      : [{ left: "65%", top: "42%", width: "33%", height: "52%", label: "REGRESSION · NOTE / FOOTER", kind: "error" }];
  }

  if (caseId === "d181") {
    if (stateIndex === 0) {
      return [
        { left: "2%", top: "32%", width: "69%", height: "63%", label: "ERROR · TABLE OVERFLOW", kind: "error" },
        { left: "72%", top: "27%", width: "26%", height: "68%", label: "ERROR · CLIPPED KPI", kind: "error" },
      ];
    }
    if (stateIndex <= 4) {
      return [
        { left: "2%", top: "8%", width: "96%", height: "87%", label: "CHANGED · SHARED BODY FIT", kind: "change" },
        { left: "2%", top: "78%", width: "69%", height: "17%", label: "TRACKED · FOOTER PRESSURE", kind: "error" },
      ];
    }
    if (stateIndex <= 8) {
      return [
        { left: "2%", top: "31%", width: "69%", height: "64%", label: "CHANGED · TABLE + NOTES", kind: "change" },
        { left: "2%", top: "79%", width: "69%", height: "16%", label: "TRACKED · NOTE OVERFLOW", kind: "error" },
      ];
    }
    return [{ left: "2%", top: "70%", width: "96%", height: "25%", label: "CHANGED · NOTE / METRIC CLOSURE", kind: "change" }];
  }

  if (caseId === "d120") {
    if (stateIndex === 0) {
      return [
        { left: "74%", top: "6%", width: "24%", height: "22%", label: "ERROR · CLIPPED HERO", kind: "error" },
        { left: "65%", top: "33%", width: "33%", height: "62%", label: "ERROR · NOTE / CALLOUT OVERLAP", kind: "error" },
      ];
    }
    if (stateIndex <= 4) {
      return [
        { left: "74%", top: "6%", width: "24%", height: "22%", label: "CHANGED · HERO FIT", kind: "change" },
        { left: "65%", top: "33%", width: "33%", height: "62%", label: "TRACKED · RIGHT REGION", kind: "error" },
      ];
    }
    if (stateIndex <= 10) {
      return [{ left: "65%", top: "35%", width: "33%", height: "60%", label: "CHANGED · NOTE / CALLOUT", kind: "change" }];
    }
    return [{ left: "59%", top: "69%", width: "39%", height: "26%", label: "CHANGED · NOTE / FOOTER", kind: "change" }];
  }

  if (stateIndex === 0) {
    return [
      { left: "69%", top: "6%", width: "29%", height: "23%", label: "ERROR · CLIPPED METRIC", kind: "error" },
      { left: "2%", top: "37%", width: "96%", height: "58%", label: "ERROR · CANVAS OVERFLOW", kind: "error" },
    ];
  }
  if (stateIndex <= 3) {
    return [
      { left: "2%", top: "6%", width: "96%", height: "31%", label: "CHANGED · HEADER BUDGET", kind: "change" },
      { left: "2%", top: "37%", width: "96%", height: "58%", label: "TRACKED · BODY OVERFLOW", kind: "error" },
    ];
  }
  return [{ left: "2%", top: "34%", width: "96%", height: "61%", label: "CHANGED · TIMELINE + RIGHT COLUMN", kind: "change" }];
};

const overlayColor = (kind: OverlayKind, accent: string) => {
  if (kind === "error") return colors.error;
  if (kind === "verified") return colors.success;
  return accent;
};

const V6CaseSummary: React.FC<{ frame: number }> = ({ frame }) => (
  <AbsoluteFill style={{ color: colors.ink, backgroundColor: colors.canvas, fontFamily: fonts.body }}>
    <CoastBackdrop />
    <AbsoluteFill style={{ padding: "54px 70px" }}>
      <SceneHeading index="04" title={<>Case <span style={{ color: colors.success }}>Studies</span></>} subtitle="Three accepted repair traces from real runs." />
      <div style={{ position: "absolute", left: 70, right: 70, top: 160, display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 22 }}>
        {cases.map((item, index) => {
          const progress = interpolate(frame, [index * 8, index * 8 + 16], [0, 1], clamp);
          const actionCount = item.frames.length - 1;
          const editCount = actionCount - item.rollbacks;
          return (
            <div key={item.id} style={{ position: "relative", padding: 12, borderTop: `7px solid ${colors.success}`, backgroundColor: colors.white, boxShadow: shadows.soft, opacity: progress, transform: `translateY(${interpolate(progress, [0, 1], [22, 0])}px)` }}>
              <Img src={staticFile(item.frames[item.frames.length - 1].src)} style={{ width: "100%", aspectRatio: "16 / 9", objectFit: "contain" }} />
              <div style={{ position: "absolute", right: 24, top: 228, width: 78, height: 78, display: "grid", placeItems: "center", borderRadius: "50%", color: colors.white, backgroundColor: colors.success, boxShadow: "0 14px 34px rgba(52,139,117,0.28)", fontSize: 48, fontWeight: 800 }}>✓</div>
              <div style={{ padding: "20px 12px 12px" }}>
                <div style={{ color: item.color, fontSize: 12, fontWeight: 800, textTransform: "uppercase" }}>{item.kind}</div>
                <div style={{ marginTop: 7, fontFamily: fonts.heading, fontSize: 25, lineHeight: 1.12, fontWeight: 800 }}>{item.title}</div>
                <div style={{ marginTop: 14, color: colors.success, fontFamily: fonts.heading, fontSize: 32, fontWeight: 800 }}>Accepted run</div>
                <div style={{ marginTop: 7, color: colors.ink, fontFamily: fonts.mono, fontSize: 14, fontWeight: 800 }}>{editCount} edits{item.rollbacks ? ` · ${item.rollbacks} rollback` : ""}</div>
                <div style={{ marginTop: 9, color: colors.inkSoft, fontSize: 13, lineHeight: 1.35 }}>{item.summary}</div>
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  </AbsoluteFill>
);

export const V6ShowcaseScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (frame >= SUMMARY_START) return <V6CaseSummary frame={frame - SUMMARY_START} />;

  const caseIndex = Math.floor(frame / CASE_FRAMES);
  const localFrame = frame - caseIndex * CASE_FRAMES;
  const currentCase = cases[caseIndex];
  const stepDuration = TRAJECTORY_PLAYBACK_FRAMES / currentCase.frames.length;
  const stateIndex = Math.min(
    currentCase.frames.length - 1,
    Math.floor(localFrame / stepDuration),
  );
  const state = currentCase.frames[stateIndex];
  const previousState = stateIndex > 0 ? currentCase.frames[stateIndex - 1] : null;
  const stateStart = stateIndex * stepDuration;
  const mix = stateIndex === 0 ? 1 : interpolate(localFrame, [stateStart, stateStart + 4], [0, 1], clamp);
  const acceptedIn = state.accepted
    ? spring({ frame: localFrame - stateStart, fps, config: { damping: 14, stiffness: 145 } })
    : 0;
  const currentColor = actionColor(state, currentCase.color);
  const actionCount = currentCase.frames.length - 1;
  const editCount = actionCount - currentCase.rollbacks;
  const progress = stateIndex / (currentCase.frames.length - 1);
  const overlayRegions = getOverlayRegions(currentCase.id, stateIndex, state);

  return (
    <AbsoluteFill style={{ color: colors.ink, backgroundColor: colors.canvas, fontFamily: fonts.body }}>
      <CoastBackdrop />
      <AbsoluteFill style={{ padding: "42px 58px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <div style={{ flex: 1 }}><SceneHeading index="04" title={<>Case <span style={{ color: currentCase.color }}>Studies</span></>} subtitle="Three accepted repair traces from real runs." /></div>
          <div style={{ marginLeft: "auto", color: currentColor, fontFamily: fonts.mono, fontSize: 14, fontWeight: 800 }}>
            {caseIndex + 1} / 3 · {stateIndex === 0 ? "INITIAL" : `ACTION ${String(stateIndex).padStart(2, "0")} / ${String(actionCount).padStart(2, "0")}`}
          </div>
        </div>

        <div style={{ position: "absolute", left: 58, top: 150, width: 1180, height: 704, overflow: "hidden", border: `7px solid ${state.accepted ? colors.success : state.action === "rollback" ? colors.error : colors.white}`, backgroundColor: colors.white, boxShadow: shadows.slide }}>
          {previousState ? <Img src={staticFile(previousState.src)} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "contain", opacity: 1 - mix }} /> : null}
          <Img src={staticFile(state.src)} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "contain", opacity: mix }} />
          {overlayRegions.map((region) => {
            const regionColor = overlayColor(region.kind, currentCase.color);
            return (
              <div key={region.label} style={{ position: "absolute", left: region.left, top: region.top, width: region.width, height: region.height, border: `5px solid ${regionColor}`, backgroundColor: `${regionColor}12`, boxShadow: `0 0 0 8px ${regionColor}18`, opacity: stateIndex === 0 ? 1 : mix }}>
                <div style={{ position: "absolute", left: -5, top: -5, padding: "7px 10px", color: colors.white, backgroundColor: regionColor, fontSize: 10, fontWeight: 800, textTransform: "uppercase" }}>{region.label}</div>
              </div>
            );
          })}
          <div style={{ position: "absolute", left: 14, top: 14, padding: "9px 12px", borderLeft: `6px solid ${currentColor}`, color: currentColor, backgroundColor: "rgba(255,255,255,0.96)", fontSize: 13, fontWeight: 800, textTransform: "uppercase" }}>{state.label}</div>
          {state.action === "rollback" ? (
            <div style={{ position: "absolute", right: 28, top: 24, padding: "12px 16px", color: colors.white, backgroundColor: colors.error, boxShadow: shadows.soft, fontSize: 16, fontWeight: 800 }}>↶ ROLLBACK</div>
          ) : null}
          {state.accepted ? (
            <div style={{ position: "absolute", right: 34, bottom: 34, width: 146, height: 146, display: "grid", placeItems: "center", borderRadius: "50%", color: colors.white, backgroundColor: colors.success, boxShadow: "0 24px 54px rgba(52,139,117,0.34)", fontSize: 92, lineHeight: 1, fontWeight: 800, opacity: acceptedIn, transform: `scale(${interpolate(acceptedIn, [0, 1], [0.48, 1])})` }}>✓</div>
          ) : null}
        </div>

        <div style={{ position: "absolute", left: 1264, right: 58, top: 150, height: 704, overflow: "hidden", borderTop: `9px solid ${currentColor}`, backgroundColor: colors.white, boxShadow: shadows.soft }}>
          <div style={{ padding: "24px 30px 22px", borderBottom: `1px solid ${colors.line}` }}>
            <div style={{ color: currentColor, fontSize: 12, fontWeight: 800, textTransform: "uppercase" }}>{currentCase.kind} · {state.accepted ? "accepted" : state.action === "rollback" ? "rollback" : state.action === "start" ? "input" : "checkpoint"}</div>
            <div style={{ marginTop: 10, fontFamily: fonts.heading, fontSize: 27, lineHeight: 1.08, fontWeight: 800 }}>{currentCase.title}</div>
            <div style={{ marginTop: 12, color: colors.ink, fontSize: 15, lineHeight: 1.35, fontWeight: 750 }}>{actionTitle(state)}</div>
            <div style={{ marginTop: 7, color: colors.inkSoft, fontSize: 14, lineHeight: 1.35 }}>{actionDetail(state)}</div>
          </div>

          <div style={{ padding: "25px 30px 0" }}>
            <div style={{ display: "flex", justifyContent: "space-between", color: colors.inkSoft, fontFamily: fonts.mono, fontSize: 12, fontWeight: 800 }}><span>TRACE PROGRESS</span><span>{Math.round(progress * 100)}%</span></div>
            <div style={{ height: 9, marginTop: 10, overflow: "hidden", backgroundColor: colors.line }}><div style={{ width: `${progress * 100}%`, height: "100%", backgroundColor: currentColor }} /></div>
          </div>

          <div style={{ margin: "30px 30px 0", borderTop: `1px solid ${colors.line}` }}>
            {[
              ["Recorded actions", String(actionCount)],
              ["Edits and patches", String(editCount)],
              ["Rollbacks", String(currentCase.rollbacks)],
              ["Run gate", "Accepted"],
            ].map(([label, value], index) => (
              <div key={label} style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", padding: "17px 0", borderBottom: `1px solid ${colors.line}`, opacity: interpolate(localFrame, [index * 3, index * 3 + 8], [0, 1], clamp) }}>
                <div style={{ color: colors.inkSoft, fontSize: 13, fontWeight: 700 }}>{label}</div>
                <div style={{ color: label === "Run gate" ? colors.success : colors.ink, fontFamily: fonts.mono, fontSize: 18, fontWeight: 800 }}>{value}</div>
              </div>
            ))}
          </div>

          <div style={{ margin: "27px 30px 0", padding: "17px 18px", color: colors.white, backgroundColor: currentColor }}>
            <div style={{ fontSize: 10, fontWeight: 800, textTransform: "uppercase", opacity: 0.72 }}>Recorded run</div>
            <div style={{ marginTop: 7, fontFamily: fonts.mono, fontSize: 14, fontWeight: 800 }}>{currentCase.run}</div>
          </div>
        </div>

        <div style={{ position: "absolute", left: 58, right: 58, bottom: 30, height: 118, padding: "12px 26px", borderTop: `1px solid ${colors.line}`, backgroundColor: "rgba(255,255,255,0.94)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", color: colors.inkSoft, fontSize: 10, fontWeight: 800, textTransform: "uppercase" }}>
            <span>Complete accepted trajectory · every node is a recorded render</span>
            <span>Action {stateIndex} / {actionCount} · {editCount} edits{currentCase.rollbacks ? ` · ${currentCase.rollbacks} rollback` : ""}</span>
          </div>
          <div style={{ position: "relative", marginTop: 8, height: 73 }}>
            <div style={{ position: "absolute", left: 12, right: 12, top: 24, height: 3, backgroundColor: colors.line }} />
            <div style={{ position: "absolute", left: 12, right: 12, top: 24, height: 3, backgroundColor: currentColor, transform: `scaleX(${progress})`, transformOrigin: "left center" }} />
            <div style={{ display: "grid", gridTemplateColumns: `repeat(${currentCase.frames.length}, minmax(0, 1fr))`, height: "100%" }}>
            {currentCase.frames.map((item, index) => {
              const active = index === stateIndex;
              const complete = index < stateIndex;
              const itemColor = actionColor(item, currentCase.color);
              return (
                <div key={item.src} style={{ display: "flex", flexDirection: "column", alignItems: "center", minWidth: 0 }}>
                  <div style={{ zIndex: 1, width: active ? 19 : item.action === "rollback" ? 14 : item.accepted ? 14 : 10, height: active ? 19 : item.action === "rollback" ? 14 : item.accepted ? 14 : 10, marginTop: active ? 16 : item.action === "rollback" || item.accepted ? 18 : 20, border: `${active || item.action === "rollback" || item.accepted ? 3 : 2}px solid ${active ? itemColor : complete ? colors.success : item.action === "rollback" ? colors.error : colors.line}`, borderRadius: item.action === "rollback" ? 3 : "50%", backgroundColor: active ? itemColor : complete ? colors.success : colors.white, boxShadow: active ? `0 0 0 6px ${itemColor}20` : "none" }} />
                  <div style={{ marginTop: active ? 7 : 9, color: active ? itemColor : item.action === "rollback" ? colors.error : complete ? colors.success : colors.inkSoft, textAlign: "center", fontFamily: fonts.mono, fontSize: currentCase.frames.length > 14 ? 8 : 9, fontWeight: 800, whiteSpace: "nowrap" }}>{index === 0 ? "START" : item.action === "rollback" ? `↶ ${index}` : item.accepted ? `✓ ${index}` : String(index).padStart(2, "0")}</div>
                </div>
              );
            })}
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const V6_SHOWCASE_FRAMES = 25 * 30;