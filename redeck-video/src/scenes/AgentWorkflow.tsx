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

/*
  Merged Pipeline + RepairReel into one unified scene.
  Structure:
    - d78 detailed walkthrough (0–360f = 12s): full detect→edit→verify loop
    - 4 fast cases (360–960f = 20s, 5s each): before → edit → final
    - Summary grid (960–1110f = 5s)
*/

interface StepData {
  src: string;
  label: string;
  spatial: number;
  overflow: number;
  detection: string;
  action: string;
  focus?: { left: string; top: string; width: string; height: string };
}

interface CaseData {
  kind: string;
  title: string;
  accent: string;
  after: string;
  steps: StepData[];
}

const cases: CaseData[] = [
  {
    kind: "Content fitting",
    title: "Fit the full narrative",
    accent: colors.ocean,
    after: "trajectory/d78_final.png",
    steps: [
      {
        src: "trajectory/d78_00.png", label: "Render", spatial: 32, overflow: 129,
        detection: "OVERFLOW  129px past 720px canvas\nISSUES    32 (14 out-of-bounds, 8 overlap)\nREGION    Bottom 42% — findings table + metrics\nCAUSE     Table rows too tall for available space",
        action: "LEVERAGE ANALYSIS:\n  td padding  15px × 12 cells = 180px total\n  th padding  14px × 6 cells  = 84px total\n  .pill font   12px × 8 pills  = 40px total\n\nSTRATEGY: Compress td first (highest leverage)",
        focus: { left: "0%", top: "58%", width: "100%", height: "42%" },
      },
      {
        src: "trajectory/d78_12.png", label: "Edit", spatial: 20, overflow: 129,
        detection: "TARGET    tbody td (appears 12 times)\nBEFORE    padding: 15px 14px\nAFTER     padding: 6px 8px\nSAVED     (15−6)×2 × 6 rows = 108px vertical",
        action: "APPLIED:\n  tbody td { padding: 15px 14px → 6px 8px }\n  thead th { padding: 14px → 7px 8px }\n  .pill   { padding: 4px 10px → 3px 8px }\n\nRESULT: Issues 32 → 20 (−12 resolved)",
        focus: { left: "0%", top: "45%", width: "65%", height: "40%" },
      },
      {
        src: "trajectory/d78_15.png", label: "Edit", spatial: 6, overflow: 25,
        detection: "REMAINING  overflow 129px (table in hidden container)\nFINDING   .overflow-box has height: 180px\nCONTENT   Needs 240px to show all text\nBLOCKER   overflow:hidden clips last 3 lines",
        action: "APPLIED:\n  .overflow-box { height: 180px → auto }\n  .overflow-box { overflow: hidden → visible }\n\nRESULT: Overflow 129 → 25px\n         Issues 20 → 6 (−14 unclipped)",
        focus: { left: "55%", top: "60%", width: "44%", height: "35%" },
      },
      {
        src: "trajectory/d78_final.png", label: "Verify", spatial: 0, overflow: 0,
        detection: "OVERFLOW    0px ✓\nISSUES      0 ✓\nOVERLAP     0 ✓\nCLIPPING    0 ✓\nOUT-OF-BOUNDS  0 ✓",
        action: "VERIFICATION PASSED\n\nAll content visible within 720px canvas.\nNo regressions introduced.\nNo protected text removed.\n\n→ Submit accepted repair.",
        focus: undefined,
      },
    ],
  },
  {
    kind: "Table recovery",
    title: "Recover clipped table",
    accent: colors.apricot,
    after: "trajectory/d181_final.png",
    steps: [
      {
        src: "trajectory/d181_00.png", label: "Render", spatial: 24, overflow: 54,
        detection: "Overflow: 54px\nTable + KPIs clipped\n24 spatial issues",
        action: "Scanning leverage targets...",
        focus: { left: "0%", top: "50%", width: "100%", height: "50%" },
      },
      {
        src: "trajectory/d181_03.png", label: "Edit", spatial: 10, overflow: 4,
        detection: "Subtitle too large\nfont-size 32px in tight area",
        action: ".subtitle { font: 32→22px }\nline-height: 1.35 → 1.2\nSaved: 42px",
        focus: { left: "0%", top: "8%", width: "100%", height: "22%" },
      },
      {
        src: "trajectory/d181_final.png", label: "Verify", spatial: 0, overflow: 0,
        detection: "Overflow: 0px ✓\nAll rows visible ✓",
        action: "Verified → Submit",
        focus: undefined,
      },
    ],
  },
  {
    kind: "Hierarchy repair",
    title: "Restore text hierarchy",
    accent: colors.coral,
    after: "trajectory/p43_final.png",
    steps: [
      {
        src: "trajectory/p43_00.png", label: "Render", spatial: 5, overflow: 0,
        detection: "5 overlapping elements\nHeading collides with body",
        action: "Scanning overlap region...",
        focus: { left: "1%", top: "15%", width: "51%", height: "55%" },
      },
      {
        src: "trajectory/p43_06.png", label: "Edit", spatial: 0, overflow: 0,
        detection: "line-height: 1.35 too tall\n3 lines exceed container",
        action: "line-height: 1.35 → 1.20\nOverlaps resolved ✓",
        focus: undefined,
      },
      {
        src: "trajectory/p43_final.png", label: "Verify", spatial: 0, overflow: 0,
        detection: "Spatial issues: 0 ✓\nHierarchy clean",
        action: "Verified → Submit",
        focus: undefined,
      },
    ],
  },
  {
    kind: "Annotation cleanup",
    title: "Separate annotations",
    accent: colors.coral,
    after: "trajectory/d120_final.png",
    steps: [
      {
        src: "trajectory/d120_00.png", label: "Render", spatial: 16, overflow: 212,
        detection: "Overflow: 212px\nAnnotation collides with table",
        action: "Large deficit — need container shrink",
        focus: { left: "60%", top: "40%", width: "38%", height: "35%" },
      },
      {
        src: "trajectory/d120_18.png", label: "Edit", spatial: 8, overflow: 0,
        detection: "Chart container has free space\nheight: fixed > content",
        action: ".chart-wrap { height: auto }\nOverflow: 212 → 0px",
        focus: { left: "55%", top: "20%", width: "44%", height: "50%" },
      },
      {
        src: "trajectory/d120_final.png", label: "Verify", spatial: 0, overflow: 0,
        detection: "Overflow: 0px ✓\nAnnotations separated ✓",
        action: "Verified → Submit",
        focus: undefined,
      },
    ],
  },
  {
    kind: "Layout compression",
    title: "Rebalance dense panels",
    accent: colors.deepOcean,
    after: "trajectory/d171_final.png",
    steps: [
      {
        src: "trajectory/d171_00.png", label: "Render", spatial: 128, overflow: 130,
        detection: "Overflow: 130px\n128 spatial issues\nCards exceed canvas",
        action: "Hero region has 80px free space",
        focus: { left: "0%", top: "35%", width: "100%", height: "65%" },
      },
      {
        src: "trajectory/d171_19.png", label: "Edit", spatial: 47, overflow: 91,
        detection: "Phase cards: font 14px × many\ngap 12px adds up",
        action: "font: 14→11px, gap: 12→6px\n−81 issues",
        focus: { left: "0%", top: "40%", width: "60%", height: "55%" },
      },
      {
        src: "trajectory/d171_final.png", label: "Verify", spatial: 0, overflow: 0,
        detection: "Overflow: 0px ✓\nAll panels fit ✓",
        action: "Verified → Submit",
        focus: undefined,
      },
    ],
  },
];

// Timing: first case gets 360 frames (12s detailed), others get 150f (5s each), summary 150f
const FIRST_CASE_FRAMES = 300;
const FAST_CASE_FRAMES = 150;
const SUMMARY_FRAMES = 90;

export const AgentWorkflow: React.FC<SceneProps> = ({ durationInFrames }) => {
  const frame = useCurrentFrame();

  // Determine which case and step we're in
  let caseIndex = 0;
  let localFrame = frame;

  if (frame < FIRST_CASE_FRAMES) {
    caseIndex = 0;
    localFrame = frame;
  } else if (frame < FIRST_CASE_FRAMES + 4 * FAST_CASE_FRAMES) {
    const fastFrame = frame - FIRST_CASE_FRAMES;
    caseIndex = 1 + Math.min(3, Math.floor(fastFrame / FAST_CASE_FRAMES));
    localFrame = fastFrame - (caseIndex - 1) * FAST_CASE_FRAMES;
  } else {
    // Summary
    caseIndex = -1;
    localFrame = frame - FIRST_CASE_FRAMES - 4 * FAST_CASE_FRAMES;
  }

  const isSummary = caseIndex === -1;
  const activeCase = isSummary ? cases[0] : cases[caseIndex];
  const isDetailed = caseIndex === 0;
  const totalSteps = activeCase.steps.length;
  const caseDuration = isDetailed ? FIRST_CASE_FRAMES : FAST_CASE_FRAMES;

  // Step timing
  const stepDuration = Math.floor((caseDuration - 10) / totalSteps);
  const activeStep = Math.min(totalSteps - 1, Math.max(0, Math.floor((localFrame - 5) / stepDuration)));
  const stepLocal = localFrame - 5 - activeStep * stepDuration;
  const fadeIn = interpolate(stepLocal, [0, 12], [0, 1], clamp);
  const fadeOut = interpolate(stepLocal, [stepDuration - 12, stepDuration], [1, 0], clamp);
  const contentOpacity = Math.min(fadeIn, fadeOut);

  const stepData = activeCase.steps[activeStep];

  if (isSummary) {
    return (
      <AbsoluteFill style={{ opacity: sceneOpacity(frame, durationInFrames) }}>
        <CoastBackdrop />
        <AbsoluteFill style={{ padding: "56px 76px", fontFamily: fonts.body }}>
          <SceneLabel index="02">Repair results</SceneLabel>
          <div style={{ marginTop: 24, color: colors.ink, fontFamily: fonts.heading, fontSize: 54, fontWeight: 800 }}>
            Five slides repaired — zero spatial issues.
          </div>
          <div style={{
            position: "absolute", left: 76, right: 76, top: 260,
            display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 18,
          }}>
            {cases.map((c) => (
              <div key={c.after}>
                <SlideFrame src={c.after} label="0 issues" labelColor={colors.success} style={{ width: "100%", aspectRatio: "16 / 9" }} />
                <div style={{ marginTop: 12, paddingTop: 10, borderTop: `4px solid ${c.accent}` }}>
                  <div style={{ color: c.accent, fontSize: 14, fontWeight: 800, textTransform: "uppercase" }}>{c.kind}</div>
                  <div style={{ marginTop: 5, color: colors.ink, fontSize: 20, lineHeight: 1.18, fontWeight: 800 }}>{c.title}</div>
                </div>
              </div>
            ))}
          </div>
        </AbsoluteFill>
      </AbsoluteFill>
    );
  }

  return (
    <AbsoluteFill style={{ opacity: sceneOpacity(frame, durationInFrames) }}>
      <CoastBackdrop />
      <AbsoluteFill style={{ padding: "44px 60px", fontFamily: fonts.body }}>
        {/* Header */}
        <SceneLabel index="02">Repair loop{isDetailed ? " — detailed" : ` · ${caseIndex + 1}/5`}</SceneLabel>
        <div style={{ marginTop: 16, display: "flex", alignItems: "baseline", gap: 18 }}>
          <div style={{ color: activeCase.accent, fontFamily: fonts.heading, fontSize: 22, fontWeight: 800, textTransform: "uppercase" }}>
            {activeCase.kind}
          </div>
          <div style={{ color: colors.ink, fontFamily: fonts.heading, fontSize: 42, fontWeight: 800 }}>
            {activeCase.title}
          </div>
        </div>

        {/* Main area: slide left, info right */}
        <div style={{ position: "absolute", left: 60, top: 155, right: 60, bottom: 60, display: "flex", gap: 28 }}>

          {/* Slide panel */}
          <div style={{
            flex: 2, position: "relative", overflow: "hidden",
            backgroundColor: colors.white, border: `6px solid ${colors.white}`,
            outline: `1px solid ${colors.line}`, boxShadow: shadows.slide,
          }}>
            {/* Crossfade images */}
            {activeCase.steps.map((step, i) => {
              const isActive = i === activeStep;
              const isPrev = i === activeStep - 1;
              const imgOp = isActive ? fadeIn : isPrev ? (1 - fadeIn) : 0;
              if (imgOp <= 0) return null;
              return (
                <Img key={i} src={staticFile(step.src)} style={{
                  position: i === 0 ? ("relative" as const) : ("absolute" as const),
                  inset: 0, width: "100%", height: "100%",
                  objectFit: "contain" as const, opacity: imgOp,
                }} />
              );
            })}
            {/* Focus box */}
            {stepData.focus && (
              <div style={{
                position: "absolute", ...stepData.focus,
                border: `4px solid ${colors.error}`,
                backgroundColor: "rgba(197,87,94,0.08)",
                opacity: contentOpacity * 0.8,
              }} />
            )}
            {/* Label */}
            <div style={{
              position: "absolute", top: 12, left: 12, padding: "6px 12px",
              backgroundColor: colors.white,
              borderLeft: `6px solid ${activeStep === totalSteps - 1 ? colors.success : activeStep === 0 ? colors.error : activeCase.accent}`,
              fontSize: 14, fontWeight: 800,
              color: activeStep === totalSteps - 1 ? colors.success : activeStep === 0 ? colors.error : activeCase.accent,
            }}>
              {stepData.label}
            </div>
          </div>

          {/* Right info panel — two boxes + metrics, solid backgrounds, dense text */}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 10, minWidth: 460 }}>

            {/* Detection */}
            <div style={{
              flex: 1, padding: "16px 20px", display: "flex", flexDirection: "column",
              backgroundColor: stepData.spatial === 0 ? "#e8faf4" : "#fef2f2",
              borderLeft: `6px solid ${stepData.spatial === 0 ? colors.success : colors.error}`,
              opacity: contentOpacity,
            }}>
              <div style={{ fontSize: 15, fontWeight: 800, color: stepData.spatial === 0 ? colors.success : colors.error, textTransform: "uppercase", letterSpacing: 2, marginBottom: 8 }}>
                Detection
              </div>
              <div style={{ fontSize: isDetailed ? 18 : 16, fontWeight: 600, color: colors.ink, lineHeight: 1.55, whiteSpace: "pre-line", flex: 1, fontFamily: "monospace" }}>
                {stepData.detection}
              </div>
            </div>

            {/* Action */}
            <div style={{
              flex: 1, padding: "16px 20px", display: "flex", flexDirection: "column",
              backgroundColor: "#f0f7ff",
              borderLeft: `6px solid ${activeCase.accent}`,
              opacity: contentOpacity,
            }}>
              <div style={{ fontSize: 15, fontWeight: 800, color: activeCase.accent, textTransform: "uppercase", letterSpacing: 2, marginBottom: 8 }}>
                Action
              </div>
              <div style={{ fontSize: isDetailed ? 18 : 16, fontWeight: 600, color: colors.ink, lineHeight: 1.55, whiteSpace: "pre-line", flex: 1, fontFamily: "monospace" }}>
                {stepData.action}
              </div>
            </div>

            {/* Metrics bar */}
            <div style={{
              padding: "12px 20px", display: "flex", alignItems: "center", gap: 20,
              backgroundColor: activeStep === totalSteps - 1 ? "#e8faf4" : "#f8f9fa",
              borderLeft: `6px solid ${activeStep === totalSteps - 1 ? colors.success : colors.ink}`,
            }}>
              <div>
                <span style={{ fontSize: 13, color: colors.inkSoft, fontWeight: 700, marginRight: 6 }}>ISSUES</span>
                <span style={{ fontSize: 34, fontWeight: 800, color: stepData.spatial === 0 ? colors.success : colors.ink }}>{stepData.spatial}</span>
              </div>
              <div>
                <span style={{ fontSize: 13, color: colors.inkSoft, fontWeight: 700, marginRight: 6 }}>OVERFLOW</span>
                <span style={{ fontSize: 34, fontWeight: 800, color: stepData.overflow === 0 ? colors.success : colors.ink }}>{stepData.overflow}</span>
                <span style={{ fontSize: 13, color: colors.inkSoft }}>px</span>
              </div>
              {/* Mini progress */}
              <div style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
                {activeCase.steps.map((_, i) => (
                  <div key={i} style={{ width: 28, height: 8, backgroundColor: i <= activeStep ? activeCase.accent : colors.line }} />
                ))}
              </div>
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
