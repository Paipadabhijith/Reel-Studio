import React, {useMemo} from 'react';
import {AbsoluteFill, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import type {Brand, ReelProps} from '../types';
import {REEL_SAFE, clamp} from '../utils/safeZones';

type Flat = {w: string; t: number; end: number; emph: boolean};

const norm = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
const CHUNK = 3;

const flatten = (scenes: ReelProps['scenes'], marks: ReelProps['emphasisMarks']): Flat[] => {
  const out: Flat[] = [];
  for (const sc of scenes) {
    const targets = new Set(sc.emphasis.flatMap((e) => e.split(/\s+/)).map(norm));
    const peaks = new Set(
      marks.filter((m) => m.scene_id === sc.id && m.kind === 'loudness_peak').map((m) => m.word_index),
    );
    sc.words.forEach((w, i) => {
      out.push({
        w: w.w,
        t: w.t,
        end: w.end ?? w.t + 0.3,
        emph: peaks.has(i) || targets.has(norm(w.w)),
      });
    });
  }
  return out;
};

/** Groups words into short chunks, breaking early after sentence punctuation. */
const chunkWords = (words: Flat[]): Flat[][] => {
  const chunks: Flat[][] = [];
  let cur: Flat[] = [];
  for (const w of words) {
    cur.push(w);
    if (cur.length >= CHUNK || /[.!?,;:]$/.test(w.w)) {
      chunks.push(cur);
      cur = [];
    }
  }
  if (cur.length) chunks.push(cur);
  return chunks;
};

export const WordCaptions: React.FC<{
  scenes: ReelProps['scenes'];
  marks: ReelProps['emphasisMarks'];
  brand: Brand;
}> = ({scenes, marks, brand}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const now = frame / fps;

  const chunks = useMemo(() => chunkWords(flatten(scenes, marks)), [scenes, marks]);

  let idx = -1;
  for (let i = 0; i < chunks.length; i++) {
    if (chunks[i][0].t <= now) idx = i;
    else break;
  }
  if (idx < 0) return null;
  const chunk = chunks[idx];
  const last = chunk[chunk.length - 1];
  const next = chunks[idx + 1];
  const hideAt = Math.min(last.end + 0.35, next ? next[0].t : Infinity);
  if (now > hideAt) return null;

  const fontSize = 88;
  // vertical center sits in the lower-middle of the frame, clamped inside the safe zone
  const boxHeight = fontSize * 2.4;
  const top = clamp(height * 0.62, REEL_SAFE.top, height - REEL_SAFE.bottom - boxHeight);

  return (
    <AbsoluteFill>
      <div
        style={{
          position: 'absolute',
          top,
          left: REEL_SAFE.left,
          width: width - REEL_SAFE.left - REEL_SAFE.right,
          minHeight: boxHeight,
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'center',
          alignContent: 'center',
          fontFamily: brand.fonts.latin,
          fontWeight: 900,
          fontSize,
          lineHeight: 1.2,
          textAlign: 'center',
          textTransform: 'uppercase',
          textShadow: '0 4px 14px rgba(0,0,0,0.85), 0 0 3px rgba(0,0,0,0.9)',
        }}
      >
        {chunk.map((w, i) => {
          const active = now >= w.t;
          const pop = active
            ? spring({frame: frame - Math.round(w.t * fps), fps, config: {damping: 14, stiffness: 220}})
            : 0;
          const scale = 1 + 0.12 * pop + (w.emph && active ? 0.1 : 0);
          const color = w.emph
            ? brand.colors.accent
            : now >= w.t && now <= w.end + 0.05
              ? brand.colors.captionActive
              : brand.colors.captionInactive;
          return (
            <span
              key={`${idx}-${i}`}
              style={{
                display: 'inline-block',
                margin: '0 24px',
                color,
                opacity: active ? 1 : 0.55,
                transform: `scale(${scale})`,
              }}
            >
              {w.w}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
