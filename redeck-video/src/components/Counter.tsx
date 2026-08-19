import React from "react";
import { interpolate, useCurrentFrame } from "remotion";

export const Counter: React.FC<{
  value: number;
  suffix?: string;
  prefix?: string;
  decimals?: number;
  delay?: number;
  duration?: number;
  style?: React.CSSProperties;
}> = ({ value, suffix = "", prefix = "", decimals = 0, delay = 0, duration = 30, style = {} }) => {
  const frame = useCurrentFrame();
  const current = interpolate(frame, [delay, delay + duration], [0, value], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <span style={style}>
      {prefix}{current.toFixed(decimals)}{suffix}
    </span>
  );
};
