import React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import cuesData from "../../narration/v6-cues.json";
import { clamp } from "../components/VideoUI";
import { fonts } from "../styles";
import { V6DemoReel } from "./V6DemoReel";

const FPS = 30;
const MUSIC_VOLUME = 0.34;
const ENGLISH_TOP_LETTERBOX_HEIGHT = 16;
const ENGLISH_BOTTOM_LETTERBOX_HEIGHT = 72;
const VIDEO_HEIGHT = 1080;

export const V6_ENGLISH_HEIGHT = ENGLISH_TOP_LETTERBOX_HEIGHT + VIDEO_HEIGHT + ENGLISH_BOTTOM_LETTERBOX_HEIGHT;

type NarrationCue = {
  id: string;
  start: number;
  end: number;
  rate: string;
  en: string;
  tts_en?: string;
};

const cues = cuesData as NarrationCue[];
const startFrame = (cue: NarrationCue) => Math.round(cue.start * FPS);
const endFrame = (cue: NarrationCue) => Math.round(cue.end * FPS);

const V6NarrationTrack: React.FC = () => (
  <>
    {cues.map((cue) => (
      <Sequence key={cue.id} from={startFrame(cue)} durationInFrames={endFrame(cue) - startFrame(cue)}>
        <Audio src={staticFile(`narration-v6/${cue.id}.wav`)} name={`V6 CosyVoice narration: ${cue.id}`} volume={1} />
      </Sequence>
    ))}
  </>
);

const V6EnglishSubtitleBand: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const cue = cues.find((item) => frame >= Math.round(item.start * fps) && frame < Math.round(item.end * fps));
  const opacity = cue
    ? interpolate(frame, [Math.round(cue.start * fps), Math.round(cue.start * fps) + 4, Math.round(cue.end * fps) - 4, Math.round(cue.end * fps)], [0, 1, 1, 0], clamp)
    : 0;

  return (
    <div style={{ position: "absolute", left: 0, top: ENGLISH_TOP_LETTERBOX_HEIGHT + VIDEO_HEIGHT, width: 1920, height: ENGLISH_BOTTOM_LETTERBOX_HEIGHT, display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden", borderTop: "1px solid rgba(255,255,255,0.12)", color: "#fff", backgroundColor: "#050708", fontFamily: fonts.body }}>
      <div style={{ width: "calc(100% - 160px)", opacity, color: "rgba(255,255,255,0.96)", textAlign: "center", fontSize: 36, lineHeight: 1.08, fontWeight: 550, letterSpacing: 0, whiteSpace: "nowrap" }}>{cue?.en ?? ""}</div>
    </div>
  );
};

export const V6DemoReelEnglish: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: "#050708" }}>
    <div style={{ position: "absolute", left: 0, top: 0, width: 1920, height: ENGLISH_TOP_LETTERBOX_HEIGHT, backgroundColor: "#050708" }} />
    <div style={{ position: "absolute", left: 0, top: ENGLISH_TOP_LETTERBOX_HEIGHT, width: 1920, height: VIDEO_HEIGHT, overflow: "hidden", boxShadow: "0 1px 0 rgba(255,255,255,0.1), 0 -1px 0 rgba(255,255,255,0.06)" }}>
      <V6DemoReel musicVolume={MUSIC_VOLUME} duckForNarration />
    </div>
    <V6NarrationTrack />
    <V6EnglishSubtitleBand />
  </AbsoluteFill>
);