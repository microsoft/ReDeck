import React from "react";
import {
  AbsoluteFill,
  interpolate,
  useCurrentFrame,
} from "remotion";
import { CoastBackdrop, Wordmark, clamp } from "../components/VideoUI";
import { colors, fonts } from "../styles";

const authorRows = [
  ["Muzhao Tian⁴*†", "Zezi Zeng³*", "Yifan Yang¹", "Xin Gao⁴", "Yan Li²", "Zisu Huang⁴"],
  ["Xiaohua Wang⁴", "Changze Lv⁴", "Mingxi Cheng¹", "Bei Liu¹", "Kai Qiu¹", "Qi Dai¹"],
  ["Dong Chen¹", "Yue Dong¹", "Xiaoqing Zheng⁴", "Ji Li¹‡", "Chong Luo¹‡"],
];

const affiliations = [
  "¹ Microsoft Corporation",
  "² Shanghai Jiao Tong University",
  "³ Xi'an Jiaotong University",
  "⁴ Fudan University",
];

export const V6CreditsScene: React.FC = () => {
  const frame = useCurrentFrame();
  const enter = interpolate(frame, [0, 12], [0, 1], clamp);
  const exit = interpolate(frame, [72, 89], [1, 0], clamp);
  const opacity = Math.min(enter, exit);

  return (
    <AbsoluteFill style={{ color: colors.white, backgroundColor: colors.ink, fontFamily: fonts.body }}>
      <CoastBackdrop variant="dark" />
      <AbsoluteFill style={{ padding: "68px 104px 58px", opacity }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingBottom: 26, borderBottom: "1px solid rgba(255,255,255,0.16)" }}>
          <Wordmark inverse fontSize={54} />
          <div style={{ color: colors.sand, fontSize: 15, fontWeight: 800, textTransform: "uppercase" }}>Microsoft Research · Academic Partners</div>
        </div>

        <div style={{ marginTop: 46, display: "flex", alignItems: "center", gap: 24 }}>
          <div style={{ flex: "0 0 auto", fontFamily: fonts.heading, fontSize: 54, lineHeight: 1, fontWeight: 800 }}>Authors</div>
          <div style={{ width: 2, height: 42, backgroundColor: "rgba(255,255,255,0.22)" }} />
          <div style={{ color: "rgba(255,255,255,0.84)", fontSize: 28, lineHeight: 1.2, fontWeight: 700 }}>Microsoft Research and academic collaborators.</div>
        </div>

        <div style={{ marginTop: 34, display: "grid", gap: 20 }}>
          {authorRows.map((row, rowIndex) => (
            <div key={rowIndex} style={{ display: "flex", justifyContent: "center", alignItems: "baseline", gap: 34, opacity: interpolate(frame, [8 + rowIndex * 4, 20 + rowIndex * 4], [0, 1], clamp) }}>
              {row.map((name) => <span key={name} style={{ fontFamily: fonts.heading, fontSize: 29, lineHeight: 1.12, fontWeight: 700, whiteSpace: "nowrap" }}>{name}</span>)}
            </div>
          ))}
        </div>

        <div style={{ marginTop: 50, paddingTop: 28, borderTop: "1px solid rgba(255,255,255,0.16)" }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 22 }}>
            {affiliations.map((affiliation, index) => (
              <div key={affiliation} style={{ paddingLeft: 15, borderLeft: `4px solid ${[colors.ocean, colors.apricot, colors.coral, colors.seafoam][index]}`, color: "rgba(255,255,255,0.75)", fontSize: 15, lineHeight: 1.3, fontWeight: 700 }}>{affiliation}</div>
            ))}
          </div>
          <div style={{ marginTop: 27, display: "flex", justifyContent: "space-between", color: "rgba(255,255,255,0.45)", fontSize: 12 }}>
            <span>* Equal contribution · † Work done during an internship at Microsoft · ‡ Corresponding authors</span>
            <span>microsoft.github.io/ReDeck</span>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const V6_CREDITS_FRAMES = 3 * 30;