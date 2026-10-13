import React, {useMemo} from 'react';
import {AbsoluteFill, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {useTheme} from '../theme';
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
  const t = useTheme();
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

  const fontSize = t.captionUpper ? 96 : 76;
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
          // the gap grows with the type, and words only grow a little, so neighbours never touch
          columnGap: '0.3em',
          rowGap: '0.08em',
          fontFamily: t.captionFont,
          fontWeight: t.captionWeight,
          fontSize,
          letterSpacing: '0.01em',
          lineHeight: 1.15,
          // on light paper the captions need a strip behind them to stay readable
          background: t.captionBacking ?? undefined,
          padding: t.captionBacking ? '18px 28px' : undefined,
          boxSizing: 'border-box',
          textAlign: 'center',
          textTransform: t.captionUpper ? 'uppercase' : 'none',
          textShadow: '0 4px 14px rgba(0,0,0,0.85), 0 0 3px rgba(0,0,0,0.9)',
        }}
      >
        {chunk.map((w, i) => {
          const active = now >= w.t;
          const pop = active
            ? spring({frame: frame - Math.round(w.t * fps), fps, config: {damping: 14, stiffness: 220}})
            : 0;
          const speaking = now >= w.t && now <= w.end + 0.05;
          const scale = 1 + 0.06 * pop;
          const boxed = w.emph && active; // stressed words get a highlight box instead of growing
          const color = boxed ? brand.colors.background : speaking ? brand.colors.captionActive : brand.colors.captionInactive;
          return (
            <span
              key={`${idx}-${i}`}
              style={{
                display: 'inline-block',
                padding: boxed ? '0 0.14em' : 0,
                margin: boxed ? '0 -0.14em' : 0,
                borderRadius: '0.08em',
                background: boxed ? brand.colors.accent : 'transparent',
                textShadow: boxed ? 'none' : undefined,
                color,
                opacity: active ? 1 : 0.55,
                transform: `scale(${scale}) rotate(${boxed ? -2 : 0}deg)`,
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
