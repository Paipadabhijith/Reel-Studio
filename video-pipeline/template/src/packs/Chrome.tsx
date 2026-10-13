import React from 'react';
import {interpolate, random, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {useTheme} from '../theme';

/** Entrance progress 0..1 for something that starts `delay` frames into the scene, at the pack's energy. */
export const useEnter = (delay = 0) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = useTheme();
  return spring({frame: frame - delay, fps, config: t.spring});
};

/** Small label above a headline: a broadcast tag, a typewriter stamp, or an editorial overline. */
export const Kicker: React.FC<{text: string; size: number; delay?: number}> = ({text, size, delay = 0}) => {
  const t = useTheme();
  const p = useEnter(delay);
  const shown = t.labelUpper ? text.toUpperCase() : text;
  if (t.pack === 'broadcast') {
    return (
      <div style={{display: 'inline-block', transform: `skewX(-10deg) translateX(${(1 - p) * -60}px)`, opacity: p, background: t.accent, padding: `${size * 0.12}px ${size * 0.45}px`}}>
        <span style={{display: 'inline-block', transform: 'skewX(10deg)', fontFamily: t.label, fontSize: size, color: t.onAccent, letterSpacing: '0.04em'}}>{shown}</span>
      </div>
    );
  }
  if (t.pack === 'archival') {
    return (
      <div
        style={{
          display: 'inline-block',
          fontFamily: t.label,
          fontSize: size * 0.9,
          color: t.accent,
          border: `${Math.max(3, size * 0.07)}px solid ${t.accent}`,
          padding: `${size * 0.1}px ${size * 0.35}px`,
          transform: `rotate(-3deg) scale(${1.4 - 0.4 * p})`,
          opacity: p * 0.9,
          letterSpacing: '0.08em',
        }}
      >
        {shown}
      </div>
    );
  }
  return (
    <div style={{display: 'flex', alignItems: 'center', gap: size * 0.5, opacity: p}}>
      <div style={{width: size * 2.2 * p, height: Math.max(4, size * 0.12), background: t.accent}} />
      <span style={{fontFamily: t.label, fontWeight: 800, fontSize: size * 0.8, color: t.text, letterSpacing: '0.2em'}}>{shown}</span>
    </div>
  );
};

/**
 * The headline words with the pack's entrance. Broadcast drops each word onto a slab, archival sets serif type
 * with an ink underline, editorial stacks big type. The last word takes the accent colour.
 */
export const Headline: React.FC<{text: string; size: number; maxW: number; align?: 'center' | 'left'; delay?: number}> = ({
  text,
  size,
  maxW,
  align = 'center',
  delay = 0,
}) => {
  const t = useTheme();
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const words = text.split(/\s+/).filter(Boolean);
  const gap = size * (t.pack === 'archival' ? 0.24 : 0.2);
  const line = interpolate(frame - delay, [fps * 0.35, fps * 0.9], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <div style={{display: 'flex', flexDirection: 'column', alignItems: align === 'center' ? 'center' : 'flex-start', maxWidth: maxW}}>
      <div style={{display: 'flex', flexWrap: 'wrap', justifyContent: align === 'center' ? 'center' : 'flex-start', columnGap: gap, rowGap: size * 0.08}}>
        {words.map((w, i) => {
          const p = spring({frame: frame - delay - i * 4, fps, config: t.spring});
          const last = i === words.length - 1 && words.length > 1;
          const shown = t.displayUpper ? w.toUpperCase() : w;
          if (t.pack === 'broadcast') {
            return (
              <span key={i} style={{display: 'inline-block', background: last ? t.accent : 'rgba(255,255,255,0.08)', padding: `0 ${size * 0.12}px`,
                                    transform: `skewX(-8deg) translateY(${(1 - p) * 50}px)`, opacity: Math.min(p * 1.6, 1)}}>
                <span style={{display: 'inline-block', transform: 'skewX(8deg)', fontFamily: t.display, fontWeight: t.displayWeight, fontSize: size,
                              lineHeight: 1.08, color: last ? t.onAccent : t.text}}>{shown}</span>
              </span>
            );
          }
          return (
            <span key={i} style={{display: 'inline-block', fontFamily: t.display, fontWeight: t.displayWeight, fontSize: size,
                                  lineHeight: t.pack === 'archival' ? 1.12 : 1.02, color: last ? t.accent : t.text,
                                  fontStyle: t.pack === 'archival' && last ? 'italic' : 'normal',
                                  transform: `translateY(${(1 - p) * (t.pack === 'archival' ? 18 : 40)}px)`, opacity: Math.min(p * 1.5, 1)}}>
              {shown}
            </span>
          );
        })}
      </div>
      {t.pack === 'archival' ? (
        <svg width={maxW * 0.5} height={size * 0.3} style={{marginTop: size * 0.08, overflow: 'visible'}}>
          <path d={`M0 ${size * 0.15} Q ${maxW * 0.25} ${size * 0.05 + random(text) * size * 0.1} ${maxW * 0.5} ${size * 0.14}`}
                stroke={t.accent} strokeWidth={Math.max(4, size * 0.05)} fill="none" strokeLinecap="round"
                strokeDasharray={maxW} strokeDashoffset={maxW * (1 - line)} />
        </svg>
      ) : t.pack === 'editorial' ? (
        <div style={{width: maxW * 0.35 * line, height: Math.max(8, size * 0.06), background: t.accent, marginTop: size * 0.18}} />
      ) : null}
    </div>
  );
};

/** A card that holds a row or a block: a skewed broadcast panel, a paper slip with tape, or a flat editorial block. */
export const Panel: React.FC<{children: React.ReactNode; p: number; highlight?: boolean; seed?: number; style?: React.CSSProperties}> = ({
  children,
  p,
  highlight = false,
  seed = 0,
  style,
}) => {
  const t = useTheme();
  if (t.pack === 'broadcast') {
    return (
      <div style={{position: 'relative', background: highlight ? t.accent : t.surface, borderLeft: `10px solid ${highlight ? t.onAccent : t.accent}`,
                   transform: `skewX(-6deg) translateX(${(1 - p) * 120}px)`, opacity: Math.min(p * 1.4, 1), ...style}}>
        <div style={{transform: 'skewX(6deg)'}}>{children}</div>
      </div>
    );
  }
  if (t.pack === 'archival') {
    const tilt = (random(`tilt-${seed}`) - 0.5) * 3;
    return (
      <div style={{position: 'relative', background: highlight ? '#FBF6E9' : t.surface, boxShadow: '0 6px 18px rgba(60,40,20,0.28)',
                   transform: `rotate(${tilt}deg) translateY(${(1 - p) * 30}px)`, opacity: Math.min(p * 1.4, 1), ...style}}>
        <div style={{position: 'absolute', top: -14, left: '42%', width: 110, height: 30, background: 'rgba(230,214,170,0.75)', transform: 'rotate(-4deg)'}} />
        {children}
      </div>
    );
  }
  return (
    <div style={{background: highlight ? t.accent : t.surface, transform: `translateY(${(1 - p) * 40}px)`, opacity: Math.min(p * 1.4, 1), ...style}}>
      {children}
    </div>
  );
};
