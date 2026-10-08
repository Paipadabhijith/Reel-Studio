import React from 'react';
import {AbsoluteFill, interpolate, random, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import type {Brand} from '../types';
import {PALETTE} from '../utils/format';
import {safeFor} from '../utils/safeZones';

type Params = {style?: 'kinetic' | 'burst' | 'rings'; headline?: string; subline?: string; keywords?: string[]};

/** A stand-in for a missing picture: an animated headline over moving graphics. All text stays in the safe zone. */
export const AnimationScene: React.FC<{params: Params; brand: Brand; kind: 'reel' | 'long'; seed: number}> = ({
  params,
  brand,
  kind,
  seed,
}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const safe = safeFor(kind);
  const style = params.style ?? 'kinetic';
  const headline = (params.headline || '').trim();
  const words = headline ? headline.split(/\s+/) : [];
  const accent = brand.colors.accent;
  const reel = kind === 'reel';
  // the reel's caption band starts about 62% down, so the content block sits above it
  const cy = reel ? height * 0.38 : height * 0.46;
  const cx = width / 2;
  const maxW = width - safe.left - safe.right;
  const size = Math.min((reel ? 150 : 190) * (words.length > 2 ? 0.75 : 1), (maxW / Math.max(headline.length, 6)) * 1.9);
  const t = frame / fps;

  const angle = 160 + frame * 0.2;
  const tint = PALETTE[seed % PALETTE.length];

  const blobs = [0, 1, 2].map((i) => {
    const r = random(`blob-${seed}-${i}`);
    return (
      <div
        key={i}
        style={{
          position: 'absolute',
          left: ((r * 0.8 + 0.1 + Math.sin(t * 0.4 + i * 2) * 0.08) * width) - 360,
          top: ((random(`b2-${seed}-${i}`) * 0.7 + 0.1 + Math.cos(t * 0.35 + i) * 0.08) * height) - 360,
          width: 720,
          height: 720,
          borderRadius: '50%',
          background: `radial-gradient(circle, ${i === 0 ? accent : tint}33, transparent 65%)`,
          filter: 'blur(10px)',
        }}
      />
    );
  });

  const particles = Array.from({length: 22}, (_, i) => {
    const x = random(`px-${seed}-${i}`) * width;
    const speed = 20 + random(`ps-${seed}-${i}`) * 50;
    const y = (height + 40 - ((t * speed + random(`py-${seed}-${i}`) * height) % (height + 80)));
    const s = 4 + random(`pz-${seed}-${i}`) * 10;
    return <circle key={i} cx={x} cy={y} r={s} fill={i % 3 === 0 ? accent : '#ffffff'} opacity={0.12 + random(`po-${seed}-${i}`) * 0.2} />;
  });

  const background = (
    <>
      <AbsoluteFill style={{background: `linear-gradient(${angle}deg, ${brand.colors.background}, #1c1c2b 55%, ${tint}22)`}} />
      {blobs}
      <svg width={width} height={height} style={{position: 'absolute', inset: 0}}>{particles}</svg>
    </>
  );

  const enter = spring({frame, fps, config: {damping: 16, stiffness: 110}});

  let graphic: React.ReactNode = null;
  if (style === 'burst') {
    const rays = Array.from({length: 28}, (_, i) => {
      const a = (i / 28) * Math.PI * 2 + t * 0.12;
      const len = Math.max(width, height);
      const w = 0.045 + (i % 2) * 0.02;
      const pts = [[cx, cy], [cx + Math.cos(a - w) * len, cy + Math.sin(a - w) * len], [cx + Math.cos(a + w) * len, cy + Math.sin(a + w) * len]];
      return <polygon key={i} points={pts.map((p) => p.join(',')).join(' ')} fill={i % 2 ? accent : '#ffffff'} opacity={i % 2 ? 0.1 : 0.05} />;
    });
    graphic = <svg width={width} height={height} style={{position: 'absolute', inset: 0}}>{rays}</svg>;
  } else if (style === 'rings') {
    const rings = Array.from({length: 5}, (_, i) => {
      const p = ((t * 0.35 + i / 5) % 1);
      return <circle key={i} cx={cx} cy={cy} r={60 + p * Math.min(width, height) * 0.62} fill="none" stroke={accent} strokeWidth={6 * (1 - p) + 1} opacity={0.55 * (1 - p)} />;
    });
    graphic = <svg width={width} height={height} style={{position: 'absolute', inset: 0}}>{rings}</svg>;
  }

  const pulse = style === 'burst' ? 1 + Math.sin(t * 3) * 0.015 : 1;
  const lineIn = interpolate(frame, [fps * 0.5, fps * 1.1], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const subIn = interpolate(frame, [fps * 0.7, fps * 1.2], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

  return (
    <AbsoluteFill style={{fontFamily: brand.fonts.latin, overflow: 'hidden'}}>
      {background}
      {graphic}
      <div
        style={{
          position: 'absolute',
          left: safe.left,
          width: maxW,
          top: cy,
          transform: `translateY(-50%) scale(${pulse})`,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          textAlign: 'center',
        }}
      >
        <div style={{display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: `0 ${size * 0.28}px`}}>
          {words.map((w, i) => {
            const p = spring({frame: frame - i * 6, fps, config: {damping: 13, stiffness: 150}});
            return (
              <span
                key={i}
                style={{
                  display: 'inline-block',
                  fontWeight: 900,
                  fontSize: size,
                  lineHeight: 1.08,
                  color: i === words.length - 1 && words.length > 1 ? accent : brand.colors.text,
                  textTransform: 'uppercase',
                  transform: `translateY(${(1 - p) * 110}px) rotate(${(1 - p) * -5}deg) scale(${0.85 + 0.15 * p})`,
                  opacity: Math.min(p * 1.4, 1),
                  textShadow: '0 6px 28px rgba(0,0,0,.45)',
                }}
              >
                {w}
              </span>
            );
          })}
        </div>
        <div style={{width: maxW * 0.5 * lineIn * enter, height: 10, borderRadius: 6, background: accent, marginTop: size * 0.22}} />
        {params.subline ? (
          <div style={{marginTop: size * 0.28, fontSize: reel ? 44 : 40, fontWeight: 600, color: brand.colors.text, opacity: 0.88 * subIn, lineHeight: 1.3, maxWidth: maxW * 0.92}}>
            {params.subline}
          </div>
        ) : null}
        {params.keywords && params.keywords.length ? (
          <div style={{display: 'flex', gap: 14, flexWrap: 'wrap', justifyContent: 'center', marginTop: 26, opacity: subIn}}>
            {params.keywords.map((k, i) => (
              <span key={i} style={{padding: '8px 22px', borderRadius: 99, border: `3px solid ${accent}`, color: accent, fontWeight: 800, fontSize: reel ? 36 : 32, textTransform: 'uppercase'}}>{k}</span>
            ))}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
