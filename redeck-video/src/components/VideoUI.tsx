import React from "react";
import { AbsoluteFill, Img, interpolate, staticFile } from "remotion";
import { colors, fonts, shadows } from "../styles";

export const clamp = {
  extrapolateLeft: "clamp" as const,
  extrapolateRight: "clamp" as const,
};

export type SceneProps = {
  durationInFrames: number;
};

export const sceneOpacity = (_frame: number, _durationInFrames: number) => 1;

export const CoastBackdrop: React.FC<{
  variant?: "light" | "hero" | "dark";
}> = ({ variant = "light" }) => {
  const dark = variant === "dark";
  const background = dark
    ? colors.ink
    : variant === "hero"
      ? "#fff5f2"
      : colors.canvas;

  return (
    <AbsoluteFill style={{ backgroundColor: background, overflow: "hidden" }}>
      <div
        style={{
          position: "absolute",
          top: -90,
          right: -160,
          width: 920,
          height: 250,
          backgroundColor: dark ? colors.coral : "#ffd9dc",
          transform: "rotate(8deg)",
        }}
      />
      <div
        style={{
          position: "absolute",
          top: 60,
          right: -190,
          width: 780,
          height: 90,
          backgroundColor: dark ? colors.apricot : colors.sand,
          transform: "rotate(8deg)",
        }}
      />
      <div
        style={{
          position: "absolute",
          right: -180,
          bottom: -110,
          width: 1180,
          height: 280,
          backgroundColor: dark ? colors.deepOcean : "#dff2f1",
          transform: "rotate(-7deg)",
        }}
      />
      <div
        style={{
          position: "absolute",
          right: -80,
          bottom: 38,
          width: 840,
          height: 52,
          backgroundColor: dark ? colors.ocean : colors.seafoam,
          transform: "rotate(-7deg)",
          opacity: dark ? 0.95 : 0.5,
        }}
      />
    </AbsoluteFill>
  );
};

export const SceneLabel: React.FC<{
  index: string;
  children: React.ReactNode;
  inverse?: boolean;
}> = ({ index, children, inverse = false }) => (
  <div
    style={{
      display: "flex",
      alignItems: "center",
      gap: 14,
      color: inverse ? "rgba(255,255,255,0.76)" : colors.inkSoft,
      fontFamily: fonts.body,
      fontSize: 18,
      fontWeight: 700,
      textTransform: "uppercase",
    }}
  >
    <span style={{ color: inverse ? colors.sand : colors.coral }}>{index}</span>
    <span style={{ width: 44, height: 2, backgroundColor: inverse ? colors.seafoam : colors.coral }} />
    <span>{children}</span>
  </div>
);

export const SlideFrame: React.FC<{
  src: string;
  style?: React.CSSProperties;
  imageStyle?: React.CSSProperties;
  label?: string;
  labelColor?: string;
  children?: React.ReactNode;
}> = ({ src, style, imageStyle, label, labelColor = colors.ink, children }) => (
  <div
    style={{
      position: "relative",
      overflow: "hidden",
      border: `10px solid ${colors.white}`,
      outline: `1px solid ${colors.line}`,
      borderRadius: 8,
      backgroundColor: colors.white,
      boxShadow: shadows.slide,
      ...style,
    }}
  >
    <Img
      src={staticFile(src)}
      style={{
        width: "100%",
        height: "100%",
        display: "block",
        objectFit: "contain",
        ...imageStyle,
      }}
    />
    {label ? (
      <div
        style={{
          position: "absolute",
          top: 18,
          left: 18,
          padding: "8px 14px",
          backgroundColor: colors.white,
          borderLeft: `5px solid ${labelColor}`,
          color: labelColor,
          fontFamily: fonts.body,
          fontSize: 16,
          fontWeight: 800,
          textTransform: "uppercase",
          boxShadow: shadows.soft,
        }}
      >
        {label}
      </div>
    ) : null}
    {children}
  </div>
);

export const Wordmark: React.FC<{ inverse?: boolean; fontSize?: number }> = ({
  inverse = false,
  fontSize = 118,
}) => (
  <div
    style={{
      display: "flex",
      alignItems: "baseline",
      fontFamily: fonts.heading,
      fontSize,
      lineHeight: 0.92,
      fontWeight: 800,
      letterSpacing: 0,
    }}
  >
    <span style={{ color: colors.coral }}>Re</span>
    <span style={{ color: inverse ? colors.white : colors.ink }}>Deck</span>
  </div>
);