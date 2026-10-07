import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import type {Brand} from '../types';
import {formatStat, parseStat} from '../utils/format';
import {safeFor} from '../utils/safeZones';

/** One big number that counts up, with a label under it. */
export const StatScene: React.FC<{
  value: string;
  label?: string | null;
  brand: Brand;
  kind: 'reel' | 'long';
}> = ({value, label, brand, kind}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const safe = safeFor(kind);
  const parsed = parseStat(value);
  const enter = spring({frame, fps, config: {damping: 16, stiffness: 120}});
  const count = interpolate(frame, [4, fps * 1.4], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const shown = parsed ? formatStat(parsed, 1 - Math.pow(1 - count, 3)) : value;
  const size = kind === 'reel' ? (shown.length > 6 ? 200 : 280) : shown.length > 6 ? 240 : 340;

  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(circle at 50% 40%, #232638, ${brand.colors.background})`,
        justifyContent: 'center',
        alignItems: 'center',
        paddingTop: safe.top,
        paddingBottom: safe.bottom,
        paddingLeft: safe.left,
        paddingRight: safe.right,
      }}
    >
      <div
        style={{
          fontFamily: brand.fonts.latin,
          fontWeight: 900,
          fontSize: size,
          lineHeight: 1,
          color: brand.colors.accent,
          transform: `scale(${0.85 + 0.15 * enter})`,
          opacity: enter,
          fontVariantNumeric: 'tabular-nums',
          textShadow: '0 8px 40px rgba(0,0,0,.5)',
        }}
      >
        {shown}
      </div>
      {label ? (
        <div
          style={{
            marginTop: 28,
            fontFamily: brand.fonts.latin,
            fontWeight: 700,
            fontSize: kind === 'reel' ? 64 : 56,
            color: brand.colors.text,
            textAlign: 'center',
            opacity: interpolate(frame, [fps * 0.4, fps * 0.9], [0, 1], {extrapolateRight: 'clamp'}),
          }}
        >
          {label}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

/** Small stat chip placed over a photo or clip, kept inside the safe zone. */
export const StatOverlay: React.FC<{
  value: string;
  label?: string | null;
  brand: Brand;
  kind: 'reel' | 'long';
}> = ({value, label, brand, kind}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const safe = safeFor(kind);
  const parsed = parseStat(value);
  const pop = spring({frame: frame - Math.round(fps * 0.3), fps, config: {damping: 14, stiffness: 140}});
  const count = interpolate(frame, [fps * 0.3, fps * 1.5], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const shown = parsed ? formatStat(parsed, 1 - Math.pow(1 - count, 3)) : value;
  return (
    <div
      style={{
        position: 'absolute',
        left: safe.left,
        top: kind === 'reel' ? safe.top + 40 : safe.top + 20,
        padding: '18px 30px',
        borderRadius: 24,
        background: 'rgba(11,11,16,.78)',
        border: `3px solid ${brand.colors.accent}`,
        transform: `scale(${0.7 + 0.3 * pop})`,
        transformOrigin: 'left top',
        opacity: pop,
        fontFamily: brand.fonts.latin,
      }}
    >
      <div style={{fontWeight: 900, fontSize: kind === 'reel' ? 120 : 96, lineHeight: 1, color: brand.colors.accent}}>{shown}</div>
      {label ? <div style={{fontWeight: 700, fontSize: kind === 'reel' ? 40 : 34, color: brand.colors.text, marginTop: 6}}>{label}</div> : null}
    </div>
  );
};
