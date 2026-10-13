import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {Backdrop} from '../packs/Backdrop';
import {useTheme} from '../theme';
import type {Brand} from '../types';
import {formatStat, parseStat} from '../utils/format';
import {safeFor} from '../utils/safeZones';

/** One big number that counts up, with a label under it. */
export const StatScene: React.FC<{
  value: string;
  label?: string | null;
  brand: Brand;
  kind: 'reel' | 'long';
  seed: number;
}> = ({value, label, brand, kind, seed}) => {
  const t = useTheme();
  const frame = useCurrentFrame();
  const {fps, width} = useVideoConfig();
  const safe = safeFor(kind);
  const parsed = parseStat(value);
  const enter = spring({frame, fps, config: {damping: 16, stiffness: 120}});
  const count = interpolate(frame, [4, fps * 1.4], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const shown = parsed ? formatStat(parsed, 1 - Math.pow(1 - count, 3)) : value;
  // Anton runs about half an em per character; size to the final value so the count-up never reflows
  const finalLen = (parsed ? formatStat(parsed, 1) : value).length;
  const size = Math.min(kind === 'reel' ? 340 : 400, (width - safe.left - safe.right) / (Math.max(finalLen, 2) * 0.52));

  return (
    <AbsoluteFill
      style={{
        justifyContent: 'center',
        alignItems: 'center',
        paddingTop: safe.top,
        paddingBottom: safe.bottom,
        paddingLeft: safe.left,
        paddingRight: safe.right,
      }}
    >
      <Backdrop seed={seed} />
      <div
        style={{
          position: 'relative',
          fontFamily: t.display,
          fontWeight: t.displayWeight,
          fontSize: size,
          lineHeight: 1,
          color: brand.colors.accent,
          transform: `scale(${0.85 + 0.15 * enter})`,
          opacity: enter,
          fontVariantNumeric: 'tabular-nums',
          textShadow: t.pack === 'archival' ? 'none' : '0 8px 40px rgba(0,0,0,.5)',
        }}
      >
        {shown}
      </div>
      {label ? (
        <div
          style={{
            position: 'relative',
            marginTop: 28,
            fontFamily: t.pack === 'archival' ? t.label : brand.fonts.latin,
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
  const t = useTheme();
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
        background: t.pack === 'archival' ? t.surface : 'rgba(11,11,16,.78)',
        boxShadow: t.pack === 'archival' ? '0 6px 18px rgba(60,40,20,0.3)' : undefined,
        border: `3px solid ${brand.colors.accent}`,
        transform: `scale(${0.7 + 0.3 * pop})`,
        transformOrigin: 'left top',
        opacity: pop,
        fontFamily: brand.fonts.latin,
      }}
    >
      <div style={{fontFamily: t.display, fontWeight: t.displayWeight, fontSize: kind === 'reel' ? 132 : 104, lineHeight: 1, color: brand.colors.accent}}>{shown}</div>
      {label ? <div style={{fontWeight: 700, fontSize: kind === 'reel' ? 40 : 34, color: brand.colors.text, marginTop: 6}}>{label}</div> : null}
    </div>
  );
};
