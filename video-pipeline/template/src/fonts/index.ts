import {useEffect, useState} from 'react';
import {continueRender, delayRender} from 'remotion';
import anton from './Anton-Regular.ttf';
import inter from './Inter.ttf';
import devanagari from './NotoSansDevanagari.ttf';
import playfair from './PlayfairDisplay.ttf';
import specialElite from './SpecialElite-Regular.ttf';

// Bundled with the template (SIL Open Font License / Apache 2.0, see OFL-*.txt and LICENSE-*.txt) so every render looks the same
// on any machine, instead of falling back to whatever Helvetica/Arial the system has.
const FACES: [string, string, string][] = [
  ['Anton', anton, '400'],
  ['Inter', inter, '100 900'],
  ['Noto Sans Devanagari', devanagari, '100 900'],
  ['Playfair Display', playfair, '400 900'],
  ['Special Elite', specialElite, '400'],
];

let loading: Promise<unknown> | null = null;

const loadAll = () => {
  loading ??= Promise.all(
    FACES.map(([family, url, weight]) => {
      const face = new FontFace(family, `url(${url})`, {weight});
      (document.fonts as FontFaceSet & {add(f: FontFace): void}).add(face); // missing from this TS lib's typings
      return face.load();
    }),
  );
  return loading;
};

/**
 * Holds the frame until the fonts are in. It must run inside a component: a delayRender() made when the
 * module first loads is created before Remotion is ready, and its continueRender() is then ignored.
 */
export const useFonts = () => {
  const [handle] = useState(() => delayRender('Loading fonts'));
  useEffect(() => {
    loadAll()
      .catch((err) => console.error('font load failed', err)) // render with fallbacks rather than hang
      .finally(() => continueRender(handle));
  }, [handle]);
};

/** Big condensed headline face: captions, stats, headlines. Anton has a single weight; never ask it for bold. */
export const DISPLAY = 'Anton, Impact, "Arial Narrow", sans-serif';
export const SERIF = '"Playfair Display", Georgia, serif';
export const TYPEWRITER = '"Special Elite", "Courier New", monospace';
export const SANS = 'Inter, Helvetica, Arial, sans-serif';
