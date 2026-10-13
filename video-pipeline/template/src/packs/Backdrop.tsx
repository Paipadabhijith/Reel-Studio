import React from 'react';
import {AbsoluteFill, random, useCurrentFrame, useVideoConfig} from 'remotion';
import {useTheme} from '../theme';

/** Static paper fibres: drawn once per scene (the seed), so the sheet doesn't shimmer. */
const PaperNoise: React.FC<{seed: number}> = ({seed}) => {
  const {width, height} = useVideoConfig();
  const w = Math.round(width / 2);
  const h = Math.round(height / 2);
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{position: 'absolute', inset: 0, width: '100%', height: '100%', mixBlendMode: 'multiply', opacity: 0.55}}>
      <filter id={`paper-${seed}`}>
        <feTurbulence type="fractalNoise" baseFrequency="0.7 0.35" numOctaves={3} seed={seed % 97} />
        <feColorMatrix type="matrix" values="0 0 0 0 0.45  0 0 0 0 0.38  0 0 0 0 0.28  0 0 0 0.35 0" />
      </filter>
      <rect width="100%" height="100%" filter={`url(#paper-${seed})`} />
    </svg>
  );
};

/**
 * The surface a graphic scene sits on. One per pack, no blobs or floating particles:
 * broadcast is a dark studio panel, archival a sheet of old paper, editorial a flat colour field with one shape.
 */
export const Backdrop: React.FC<{seed: number}> = ({seed}) => {
  const t = useTheme();
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();

  if (t.pack === 'broadcast') {
    const sweep = ((frame / fps) * 0.18 + random(`sw-${seed}`)) % 1.6 - 0.3; // a slow light pass, like a studio set
    return (
      <AbsoluteFill style={{background: `linear-gradient(170deg, ${t.bg2} 0%, ${t.bg} 62%)`}}>
        <AbsoluteFill style={{background: 'repeating-linear-gradient(115deg, rgba(255,255,255,0.035) 0 2px, transparent 2px 26px)'}} />
        <AbsoluteFill
          style={{
            background: `linear-gradient(105deg, transparent ${sweep * 100 - 12}%, rgba(255,255,255,0.07) ${sweep * 100}%, transparent ${sweep * 100 + 12}%)`,
          }}
        />
        <div style={{position: 'absolute', left: 0, right: 0, bottom: 0, height: height * 0.35, background: `linear-gradient(to top, ${t.accent2}26, transparent)`}} />
        <div style={{position: 'absolute', left: 0, top: 0, width: 14, height, background: t.accent}} />
      </AbsoluteFill>
    );
  }

  if (t.pack === 'archival') {
    const foldY = height * (0.3 + random(`fold-${seed}`) * 0.4);
    return (
      <AbsoluteFill style={{background: t.bg}}>
        <PaperNoise seed={seed} />
        {/* a crease across the sheet and burnt edges */}
        <div style={{position: 'absolute', left: 0, right: 0, top: foldY, height: 2, background: 'rgba(80,60,40,0.18)', boxShadow: '0 1px 0 rgba(255,255,255,0.35)'}} />
        <AbsoluteFill style={{background: 'radial-gradient(ellipse at 50% 45%, transparent 65%, rgba(92,64,34,0.28) 100%)'}} />
      </AbsoluteFill>
    );
  }

  // editorial: one confident shape that drifts slowly
  const r = random(`ed-${seed}`);
  const size = Math.max(width, height) * (0.55 + r * 0.2);
  const drift = Math.sin(frame / fps * 0.4 + r * 6) * 30;
  const circle = r > 0.5;
  return (
    <AbsoluteFill style={{background: t.bg}}>
      <div
        style={{
          position: 'absolute',
          width: size,
          height: circle ? size : size * 0.42,
          left: (r > 0.25 && r < 0.75 ? width - size * 0.55 : -size * 0.45) + drift,
          top: height * (0.08 + r * 0.5),
          borderRadius: circle ? '50%' : 0,
          transform: circle ? undefined : 'rotate(-12deg)',
          background: t.accent2,
          opacity: 0.12,
        }}
      />
    </AbsoluteFill>
  );
};
