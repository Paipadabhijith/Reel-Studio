export type Word = {w: string; t: number; end?: number | null};

export type SceneProps = {
  id: number;
  text: string;
  startS: number;
  endS: number;
  visual: {
    type: 'photo' | 'video' | 'text_card';
    file: string | null;
    motion: string;
    placeholder?: string | null;
    clipFrames?: number | null;
  };
  emphasis: string[];
  words: Word[];
  overlay: {type: string; value?: string | null; label?: string | null} | null;
};

export type Brand = {
  fonts: {latin: string; devanagari: string};
  colors: {
    background: string;
    text: string;
    accent: string;
    captionActive: string;
    captionInactive: string;
  };
};

export type ReelProps = {
  reelId: string;
  fps: number;
  width: number;
  height: number;
  durationInFrames: number;
  audioSrc: string | null;
  draft?: boolean;
  brand: Brand;
  scenes: SceneProps[];
  emphasisMarks: {scene_id: number; word_index: number; kind: string}[];
};
