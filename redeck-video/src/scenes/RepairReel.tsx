import React from "react";
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import {
  CoastBackdrop,
  SceneLabel,
  SceneProps,
  SlideFrame,
  clamp,
  sceneOpacity,
} from "../components/VideoUI";
import { colors, fonts, shadows } from "../styles";

const CASE_FRAMES = 150;
const SUMMARY_START = CASE_FRAMES * 5;

interface StepInfo {
  src: string;
  label: string;
  spatial: number;
  overflow: number;
  issue: string;
  edit: string;
  focus?: { left: string; top: string; width: string; height: string };
}

const repairCases: Array<{
  kind: string; action: string; accent: string; after: string;
  steps: StepInfo[];
}> = [
  {
    kind: "Hierarchy repair",
    action: "Restore text hierarchy",
    accent: colors.coral,
    after: "trajectory/p43_final.png",
    steps: [
      { src: "trajectory/p43_00.png", label: "Detect", spatial: 5, overflow: 0, issue: "PROBLEM: Text overlap\n• Title block overlaps body copy\n• 5 spatial conflicts found", edit: "WAITING FOR EDIT", focus: { left: "1%", top: "15%", width: "51%", height: "55%" } },
      { src: "trajectory/p43_01.png", label: "Edit 1", spatial: 5, overflow: 0, issue: "FINDING: Heading too large\n• .research-tab padding causes collision\n• Font exceeds allocated height", edit: "ACTION: Reduce padding\n• padding: 20px → 12px\n• font-size: 28px → 24px", focus: { left: "1%", top: "15%", width: "51%", height: "55%" } },
      { src: "trajectory/p43_06.png", label: "Edit 6", spatial: 0, overflow: 0, issue: "FINDING: Body text too tall\n• line-height causes content overflow\n• 3 lines exceed container", edit: "ACTION: Tighten line spacing\n• line-height: 1.35 → 1.20\n• All overlaps resolved ✓", focus: undefined },
      { src: "trajectory/p43_final.png", label: "Verify", spatial: 0, overflow: 0, issue: "RESULT: 0 issues remaining\n• No overlap\n• No clipping\n• No overflow", edit: "STATUS: Verified ✓\n• All content visible\n• Layout clean → Submit", focus: undefined },
    ],
  },
  {
    kind: "Content fitting",
    action: "Fit the full narrative",
    accent: colors.ocean,
    after: "trajectory/d78_final.png",
    steps: [
      { src: "trajectory/d78_00.png", label: "Detect", spatial: 32, overflow: 129, issue: "PROBLEM: Canvas overflow\n• Content extends 129px past canvas\n• 32 elements out of bounds", edit: "WAITING FOR EDIT", focus: { left: "0%", top: "60%", width: "100%", height: "40%" } },
      { src: "trajectory/d78_12.png", label: "Edit 12", spatial: 20, overflow: 129, issue: "FINDING: Table rows too tall\n• td padding 15px × 12 cells\n• Highest leverage target", edit: "ACTION: Compress table cells\n• td padding: 15px → 6px\n• Saves: 9px × 12 = 108px", focus: { left: "0%", top: "45%", width: "65%", height: "40%" } },
      { src: "trajectory/d78_15.png", label: "Edit 15", spatial: 6, overflow: 25, issue: "FINDING: Fixed container clips text\n• .overflow-box height:fixed\n• Content needs more space", edit: "ACTION: Release container height\n• height: 180px → auto\n• Overflow: 129px → 25px", focus: { left: "55%", top: "60%", width: "44%", height: "35%" } },
      { src: "trajectory/d78_final.png", label: "Verify", spatial: 0, overflow: 0, issue: "RESULT: 0 issues remaining\n• Overflow eliminated\n• All rows visible\n• No clipping", edit: "STATUS: Verified ✓\n• Full narrative fits canvas\n• Submit", focus: undefined },
    ],
  },
  {
    kind: "Table recovery",
    action: "Recover the full comparison",
    accent: colors.apricot,
    after: "trajectory/d181_final.png",
    steps: [
      { src: "trajectory/d181_00.png", label: "Detect", spatial: 24, overflow: 54, issue: "PROBLEM: Content clipped\n• Table + KPI stack cut off at edge\n• 54px overflow, 24 issues", edit: "WAITING FOR EDIT", focus: { left: "0%", top: "50%", width: "100%", height: "50%" } },
      { src: "trajectory/d181_03.png", label: "Edit 3", spatial: 10, overflow: 4, issue: "FINDING: Subtitle too large\n• font-size: 32px in tight space\n• line-height pushes content down", edit: "ACTION: Reduce subtitle scale\n• font-size: 32px → 22px\n• line-height: 1.35 → 1.2\n• Saves: 42px", focus: { left: "0%", top: "10%", width: "100%", height: "25%" } },
      { src: "trajectory/d181_09.png", label: "Edit 9", spatial: 6, overflow: 0, issue: "FINDING: Note text too spread\n• .note-copy line-height 1.35\n• 4 lines × excess = 85px waste", edit: "ACTION: Tighten note spacing\n• line-height: 1.35 → 1.18\n• Overflow: 54px → 0px ✓", focus: { left: "0%", top: "75%", width: "100%", height: "24%" } },
      { src: "trajectory/d181_final.png", label: "Verify", spatial: 0, overflow: 0, issue: "RESULT: 0 issues remaining\n• Table fully visible\n• KPIs intact\n• No clipping", edit: "STATUS: Verified ✓\n• All data readable\n• Submit", focus: undefined },
    ],
  },
  {
    kind: "Annotation cleanup",
    action: "Separate chart annotations",
    accent: colors.coral,
    after: "trajectory/d120_final.png",
    steps: [
      { src: "trajectory/d120_00.png", label: "Detect", spatial: 16, overflow: 212, issue: "PROBLEM: Severe overflow\n• 212px past canvas bottom\n• Annotation collides with table", edit: "WAITING FOR EDIT", focus: { left: "60%", top: "40%", width: "38%", height: "35%" } },
      { src: "trajectory/d120_13.png", label: "Edit 13", spatial: 11, overflow: 173, issue: "FINDING: Insight text too spread\n• paragraph line-height 1.4\n• Multiple blocks add up", edit: "ACTION: Compress text blocks\n• line-height: 1.4 → 1.2\n• Saves: 39px across 3 blocks", focus: { left: "0%", top: "55%", width: "55%", height: "40%" } },
      { src: "trajectory/d120_18.png", label: "Edit 18", spatial: 8, overflow: 0, issue: "FINDING: Chart container too tall\n• Fixed height holds empty space\n• Content only needs 60%", edit: "ACTION: Shrink container\n• .chart-wrap height → auto\n• Overflow: 212px → 0px ✓", focus: { left: "55%", top: "20%", width: "44%", height: "50%" } },
      { src: "trajectory/d120_final.png", label: "Verify", spatial: 0, overflow: 0, issue: "RESULT: 0 issues remaining\n• Chart + table separated\n• Annotations visible\n• No collision", edit: "STATUS: Verified ✓\n• Clean layout\n• Submit", focus: undefined },
    ],
  },
  {
    kind: "Layout compression",
    action: "Rebalance dense panels",
    accent: colors.deepOcean,
    after: "trajectory/d171_final.png",
    steps: [
      { src: "trajectory/d171_00.png", label: "Detect", spatial: 128, overflow: 130, issue: "PROBLEM: Massive overflow\n• 130px past canvas, 128 issues\n• Roadmap panels exceed bounds", edit: "WAITING FOR EDIT", focus: { left: "0%", top: "35%", width: "100%", height: "65%" } },
      { src: "trajectory/d171_04.png", label: "Edit 4", spatial: 135, overflow: 62, issue: "FINDING: Hero row wastes space\n• height: 220px but content is 140px\n• Free space to reclaim", edit: "ACTION: Shrink hero container\n• height: 220px → 140px\n• Reclaimed: 80px for free", focus: { left: "0%", top: "10%", width: "100%", height: "25%" } },
      { src: "trajectory/d171_19.png", label: "Edit 19", spatial: 47, overflow: 91, issue: "FINDING: Phase cards too padded\n• font 14px + gap 12px × many cards\n• High leverage target", edit: "ACTION: Compress card grid\n• font: 14px → 11px\n• gap: 12px → 6px\n• −81 issues", focus: { left: "0%", top: "40%", width: "60%", height: "55%" } },
      { src: "trajectory/d171_final.png", label: "Verify", spatial: 0, overflow: 0, issue: "RESULT: 0 issues remaining\n• All panels within canvas\n• Roadmap readable\n• Cards balanced", edit: "STATUS: Verified ✓\n• 128 → 0 issues\n• Submit", focus: undefined },
    ],
  },
];

export const RepairReel: React.FC<SceneProps> = ({ durationInFrames }) => {
  const frame = useCurrentFrame();
  const summary = frame >= SUMMARY_START;
  const caseIndex = Math.min(repairCases.length - 1, Math.floor(frame / CASE_FRAMES));
  const localFrame = frame - caseIndex * CASE_FRAMES;
  const activeCase = repairCases[caseIndex];

  // 4 steps — each gets ~35 frames with smooth opacity transition
  const stepDuration = 34;
  const rawStep = (localFrame - 8) / stepDuration;
  const activeStep = Math.min(3, Math.max(0, Math.floor(rawStep)));
  const stepLocalFrame = localFrame - 8 - activeStep * stepDuration;
  // Fade in at start of each step
  const stepOpacity = interpolate(stepLocalFrame, [0, 8], [0, 1], clamp);

  const stepData = activeCase.steps[activeStep];

  return (
    <AbsoluteFill style={{ opacity: sceneOpacity(frame, durationInFrames) }}>
      <CoastBackdrop />
      {!summary ? (
        <AbsoluteFill style={{ padding: "50px 68px", fontFamily: fonts.body }}>
          <SceneLabel index="03">Repair trajectory · {caseIndex + 1} / 5</SceneLabel>
          <div style={{ marginTop: 20, display: "flex", alignItems: "baseline", gap: 20 }}>
            <div style={{ color: activeCase.accent, fontFamily: fonts.heading, fontSize: 24, fontWeight: 800, textTransform: "uppercase" }}>
              {activeCase.kind}
            </div>
            <div style={{ color: colors.ink, fontFamily: fonts.heading, fontSize: 46, fontWeight: 800 }}>
              {activeCase.action}
            </div>
          </div>

          {/* Slide — smooth crossfade between steps */}
          <div style={{
            position: "absolute", left: 68, top: 168, width: 1180, height: 664,
            overflow: "hidden", backgroundColor: colors.white,
            border: `8px solid ${colors.white}`, outline: `1px solid ${colors.line}`,
            boxShadow: shadows.slide,
          }}>
            {/* Render all step images, only active one is visible */}
            {activeCase.steps.map((step, i) => {
              const isActive = i === activeStep;
              const isPrev = i === activeStep - 1;
              const imgOp = isActive ? stepOpacity : isPrev ? (1 - stepOpacity) : 0;
              if (imgOp <= 0) return null;
              return (
                <Img key={i} src={staticFile(step.src)} style={{
                  position: i === 0 ? "relative" as const : "absolute" as const,
                  inset: 0, width: "100%", height: "100%", objectFit: "contain" as const,
                  opacity: imgOp,
                }} />
              );
            })}
            {/* Red focus box — fades with step */}
            {stepData.focus && (
              <div style={{
                position: "absolute", ...stepData.focus,
                border: `4px solid ${colors.error}`,
                backgroundColor: "rgba(197,87,94,0.08)",
                opacity: stepOpacity * 0.85,
              }} />
            )}
            {/* Step label pill */}
            <div style={{
              position: "absolute", top: 14, left: 14, padding: "7px 14px",
              backgroundColor: colors.white,
              borderLeft: `5px solid ${activeStep === 3 ? colors.success : activeStep === 0 ? colors.error : activeCase.accent}`,
              fontSize: 15, fontWeight: 800,
              color: activeStep === 3 ? colors.success : activeStep === 0 ? colors.error : activeCase.accent,
            }}>
              {stepData.label}
            </div>
          </div>

          {/* Right panel — equal thirds, large text, smooth content transition */}
          <div style={{ position: "absolute", left: 1290, top: 168, width: 560, height: 664, display: "flex", flexDirection: "column", gap: 12 }}>

            {/* Top: Detection — 1/3 height */}
            <div style={{
              flex: 1, padding: "20px 22px", display: "flex", flexDirection: "column",
              border: `1px solid ${colors.line}`,
              borderLeft: `5px solid ${stepData.spatial === 0 ? colors.success : colors.error}`,
              opacity: stepOpacity,
            }}>
              <div style={{ fontSize: 13, fontWeight: 800, color: stepData.spatial === 0 ? colors.success : colors.error, textTransform: "uppercase", letterSpacing: 2, marginBottom: 10 }}>
                Detection
              </div>
              <div style={{ fontSize: 20, fontWeight: 700, color: colors.ink, lineHeight: 1.45, whiteSpace: "pre-line", flex: 1 }}>
                {stepData.issue}
              </div>
            </div>

            {/* Middle: Edit action — 1/3 height */}
            <div style={{
              flex: 1, padding: "20px 22px", display: "flex", flexDirection: "column",
              border: `1px solid ${colors.line}`,
              borderLeft: `5px solid ${activeCase.accent}`,
              opacity: stepOpacity,
            }}>
              <div style={{ fontSize: 13, fontWeight: 800, color: activeCase.accent, textTransform: "uppercase", letterSpacing: 2, marginBottom: 10 }}>
                Edit
              </div>
              <div style={{ fontSize: 20, fontWeight: 700, color: colors.ink, lineHeight: 1.45, whiteSpace: "pre-line", flex: 1 }}>
                {stepData.edit}
              </div>
            </div>

            {/* Bottom: Metrics + progress — 1/3 height */}
            <div style={{
              flex: 1, padding: "20px 22px", display: "flex", flexDirection: "column", justifyContent: "center",
              border: `1px solid ${colors.line}`,
              borderLeft: `5px solid ${activeStep === 3 ? colors.success : colors.ink}`,
            }}>
              <div style={{ display: "flex", gap: 24, alignItems: "baseline", marginBottom: 16 }}>
                <div>
                  <span style={{ fontSize: 13, color: colors.inkSoft, fontWeight: 700, textTransform: "uppercase", letterSpacing: 1, marginRight: 8 }}>Issues</span>
                  <span style={{ fontSize: 42, fontWeight: 800, color: stepData.spatial === 0 ? colors.success : colors.ink }}>{stepData.spatial}</span>
                </div>
                <div>
                  <span style={{ fontSize: 13, color: colors.inkSoft, fontWeight: 700, textTransform: "uppercase", letterSpacing: 1, marginRight: 8 }}>Overflow</span>
                  <span style={{ fontSize: 42, fontWeight: 800, color: stepData.overflow === 0 ? colors.success : colors.ink }}>{stepData.overflow}</span>
                  <span style={{ fontSize: 18, color: colors.inkSoft }}>px</span>
                </div>
              </div>
              {/* Progress */}
              <div style={{ display: "flex", gap: 6 }}>
                {activeCase.steps.map((_, i) => (
                  <div key={i} style={{
                    flex: 1, height: 8,
                    backgroundColor: i <= activeStep ? (i === 3 ? colors.success : activeCase.accent) : colors.line,
                  }} />
                ))}
              </div>
            </div>
          </div>

          {/* Case dots */}
          <div style={{ position: "absolute", right: 78, bottom: 54, display: "flex", gap: 8 }}>
            {repairCases.map((_, index) => (
              <div key={index} style={{
                width: index === caseIndex ? 110 : 36, height: 6,
                backgroundColor: index === caseIndex ? activeCase.accent : colors.line,
              }} />
            ))}
          </div>
        </AbsoluteFill>
      ) : (
        <AbsoluteFill style={{ padding: "56px 76px", fontFamily: fonts.body }}>
          <SceneLabel index="03">Repair trajectories · final renders</SceneLabel>
          <div style={{ marginTop: 24, color: colors.ink, fontFamily: fonts.heading, fontSize: 62, fontWeight: 800 }}>
            Five step-by-step refinement trajectories.
          </div>
          <div style={{
            position: "absolute", left: 76, right: 76, top: 285,
            display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 18,
          }}>
            {repairCases.map((repair) => (
              <div key={repair.after}>
                <SlideFrame src={repair.after} label="Final render" labelColor={colors.success} style={{ width: "100%", aspectRatio: "16 / 9" }} />
                <div style={{ marginTop: 15, paddingTop: 13, borderTop: `4px solid ${repair.accent}` }}>
                  <div style={{ color: repair.accent, fontSize: 15, fontWeight: 800, textTransform: "uppercase" }}>{repair.kind}</div>
                  <div style={{ marginTop: 6, color: colors.ink, fontSize: 21, lineHeight: 1.18, fontWeight: 800 }}>{repair.action}</div>
                </div>
              </div>
            ))}
          </div>
          <div style={{
            position: "absolute", left: 76, right: 76, bottom: 82, padding: "24px 30px",
            color: colors.white, backgroundColor: colors.ink,
            fontFamily: fonts.heading, fontSize: 30, fontWeight: 750, textAlign: "center",
          }}>
            Each trajectory shows the agent detecting, compressing, and verifying spatial issues step by step.
          </div>
        </AbsoluteFill>
      )}
    </AbsoluteFill>
  );
};

