import "./index.css";
import { Composition } from "remotion";
import { RedeckPromo } from "./Promo";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="RedeckPromo"
        component={RedeckPromo}
        durationInFrames={1320}
        fps={30}
        width={1920}
        height={1080}
      />
    </>
  );
};
