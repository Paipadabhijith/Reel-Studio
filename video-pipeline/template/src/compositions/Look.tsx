import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {useTheme} from '../theme';

/** Darkened corners: pulls the eye to the centre and hides mismatched edges. Strength comes from the pack. */
export const Vignette: React.FC = () => {
  const t = useTheme();
  return (
    <AbsoluteFill style={{background: `radial-gradient(ellipse at 50% 45%, transparent 55%, rgba(0,0,0,${t.vignette}) 100%)`, pointerEvents: 'none'}} />
  );
};

/**
 * Film grain over the whole picture (under the captions). The noise pattern changes every other frame;
 * it is drawn at half size and scaled up, which is cheaper and looks more like film than pixel noise.
 */
export const Grain: React.FC = () => {
  const t = useTheme();
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const w = Math.round(width / 2);
  const h = Math.round(height / 2);
  const seed = Math.floor(frame / 2) % 12;
  return (
    <AbsoluteFill style={{pointerEvents: 'none', mixBlendMode: 'overlay', opacity: t.grain}}>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{width: '100%', height: '100%'}}>
        <filter id={`grain-${seed}`}>
          <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves={2} seed={seed} stitchTiles="stitch" />
          <feColorMatrix type="saturate" values="0" />
        </filter>
        <rect width="100%" height="100%" filter={`url(#grain-${seed})`} />
      </svg>
    </AbsoluteFill>
  );
};
