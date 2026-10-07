export type Word = {w: string; t: number; end?: number | null};

export type VisualKind = 'photo' | 'video' | 'chart' | 'stat' | 'blender' | 'text_card';

export type Overlay = {type: string; value?: string | null; label?: string | null};

export type SceneProps = {
  id: number;
  text: string;
  startS: number;
  endS: number;
  visual: {
    type: VisualKind;
    file: string | null;
    motion: string;
    placeholder?: string | null;
    clipFrames?: number | null;
    params?: Record<string, any> | null;
  };
  emphasis: string[];
  words: Word[];
  overlay: Overlay | null;
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

export type VideoProps = {
  reelId: string;
  kind: 'reel' | 'long';
  fps: number;
  width: number;
  height: number;
  durationInFrames: number;
  audioSrc: string | null;
  draft?: boolean;
  captions?: boolean;
  chapterTitle?: string | null;
  brand: Brand;
  scenes: SceneProps[];
  emphasisMarks: {scene_id: number; word_index: number; kind: string}[];
};

// kept so older imports keep compiling
export type ReelProps = VideoProps;
