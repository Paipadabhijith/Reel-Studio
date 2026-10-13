import {createContext, useContext} from 'react';
import {DISPLAY, SANS, SERIF, TYPEWRITER} from './fonts';
import type {Brand, Direction} from './types';

export type Pack = 'broadcast' | 'archival' | 'editorial';
export type TransitionKind = 'cut' | 'wipe-left' | 'wipe-up' | 'zoom' | 'whip' | 'flash' | 'iris' | 'dissolve' | 'slide-up' | 'stinger';

/** Everything a scene needs to look like its pack. Built once per video from the script's `direction`. */
export type Theme = {
  pack: Pack;
  energy: 'calm' | 'steady' | 'punchy';
  bg: string;
  bg2: string;
  surface: string;
  text: string;          // on bg
  muted: string;
  onAccent: string;      // text drawn on an accent fill
  accent: string;
  accent2: string;
  display: string;       // headline face
  displayWeight: number;
  displayUpper: boolean;
  label: string;         // kickers, small labels
  labelUpper: boolean;
  body: string;
  captionFont: string;
  captionWeight: number;
  captionUpper: boolean;
  captionText: string;
  captionActive: string;
  captionBacking: string | null; // a strip behind captions (needed on light paper)
  grade: string;         // CSS filter for photos and clips
  grain: number;
  vignette: number;
  transitions: TransitionKind[];
  transitionFrames: number;
  spring: {damping: number; stiffness: number};
};

const GRADES: Record<string, string> = {
  neutral: 'contrast(1.08) saturate(0.92) brightness(0.97)',
  warm: 'contrast(1.06) saturate(1.04) sepia(0.2) brightness(0.98)',
  cool: 'contrast(1.08) saturate(0.82) hue-rotate(-8deg) brightness(0.96)',
  mono: 'grayscale(1) contrast(1.22) brightness(0.94)',
  sepia: 'grayscale(1) sepia(0.72) contrast(1.12) brightness(0.95)',
};

const ENERGY: Record<Theme['energy'], {transitions: TransitionKind[]; frames: number; spring: Theme['spring']}> = {
  calm: {transitions: ['dissolve', 'slide-up', 'wipe-up'], frames: 18, spring: {damping: 22, stiffness: 70}},
  steady: {transitions: ['wipe-left', 'zoom', 'dissolve', 'iris', 'wipe-up'], frames: 12, spring: {damping: 18, stiffness: 120}},
  punchy: {transitions: ['whip', 'stinger', 'flash', 'zoom', 'wipe-left'], frames: 8, spring: {damping: 13, stiffness: 190}},
};

/** Relative luminance, for checking that a model-chosen accent can actually be read on the pack's background. */
const lum = (hex: string) => {
  const n = parseInt(hex.replace('#', ''), 16);
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
};
const contrast = (a: string, b: string) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};
const readable = (c: string | null | undefined, bg: string, fallback: string) =>
  c && /^#[0-9A-Fa-f]{6}$/.test(c) && contrast(c, bg) >= 3 ? c : fallback;
const inkFor = (fill: string) => (lum(fill) > 0.35 ? '#111111' : '#FFFFFF');

export const makeTheme = (direction: Direction | null | undefined, brand: Brand): Theme => {
  const d = direction ?? {pack: 'editorial', energy: 'steady', grade: 'neutral', accent: null, accent2: null};
  const pack: Pack = (['broadcast', 'archival', 'editorial'] as const).includes(d.pack as Pack) ? (d.pack as Pack) : 'editorial';
  const energy = (['calm', 'steady', 'punchy'] as const).includes(d.energy as Theme['energy']) ? (d.energy as Theme['energy']) : 'steady';
  const motion = ENERGY[energy];
  // archival never whips, flashes or irises: it is paper, not television
  const transitions = pack === 'archival'
    ? motion.transitions.map((k) => (['whip', 'flash', 'stinger', 'iris', 'zoom'].includes(k) ? 'dissolve' : k))
    : motion.transitions;
  const base = {
    energy,
    grade: GRADES[d.grade ?? 'neutral'] ?? GRADES.neutral,
    transitions: Array.from(new Set(transitions)) as TransitionKind[],
    transitionFrames: motion.frames,
    spring: motion.spring,
  };

  if (pack === 'broadcast') {
    const bg = '#06080E';
    const accent = readable(d.accent, bg, '#FFD23F');
    const accent2 = readable(d.accent2, bg, '#2F7BFF');
    return {
      ...base, pack, bg, bg2: '#121A2E', surface: '#161E33', text: '#FFFFFF', muted: '#97A1B8', onAccent: inkFor(accent),
      accent, accent2, display: DISPLAY, displayWeight: 400, displayUpper: true, label: DISPLAY, labelUpper: true, body: SANS,
      captionFont: DISPLAY, captionWeight: 400, captionUpper: true, captionText: '#FFFFFF', captionActive: accent, captionBacking: null,
      grain: 0.06, vignette: 0.5,
    };
  }
  if (pack === 'archival') {
    const bg = '#E8DDC4';
    const accent = readable(d.accent, bg, '#9E2B25');
    const accent2 = readable(d.accent2, bg, '#2E4756');
    return {
      ...base, pack, bg, bg2: '#D6C6A4', surface: '#F3ECDB', text: '#1E1914', muted: '#5C5145', onAccent: inkFor(accent),
      accent, accent2, display: SERIF, displayWeight: 800, displayUpper: false, label: TYPEWRITER, labelUpper: true, body: SERIF,
      captionFont: SERIF, captionWeight: 800, captionUpper: false, captionText: '#F3ECDB', captionActive: '#E9C46A',
      captionBacking: 'rgba(24, 19, 14, 0.82)', grain: 0.12, vignette: 0.3,
    };
  }
  const bg = brand.colors.background;
  const accent = readable(d.accent, bg, brand.colors.accent);
  const accent2 = readable(d.accent2, bg, '#7C8CF8');
  return {
    ...base, pack, bg, bg2: '#1C1C2B', surface: '#191A26', text: brand.colors.text, muted: '#A3A6B8', onAccent: inkFor(accent),
    accent, accent2, display: DISPLAY, displayWeight: 400, displayUpper: true, label: SANS, labelUpper: true, body: SANS,
    captionFont: DISPLAY, captionWeight: 400, captionUpper: true, captionText: brand.colors.captionInactive, captionActive: accent,
    captionBacking: null, grain: 0.09, vignette: 0.55,
  };
};

export const ThemeContext = createContext<Theme | null>(null);

export const useTheme = (): Theme => {
  const t = useContext(ThemeContext);
  if (!t) throw new Error('useTheme outside ThemeContext');
  return t;
};
