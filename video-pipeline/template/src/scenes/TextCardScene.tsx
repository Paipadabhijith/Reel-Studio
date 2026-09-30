import React from 'react';
import {AbsoluteFill} from 'remotion';
import type {Brand} from '../types';
import {REEL_SAFE} from '../utils/safeZones';

export const TextCardScene: React.FC<{text: string; brand: Brand}> = ({text, brand}) => (
  <AbsoluteFill
    style={{
      background: `linear-gradient(160deg, ${brand.colors.background}, #1c1c2b)`,
      justifyContent: 'center',
      paddingLeft: REEL_SAFE.left,
      paddingRight: REEL_SAFE.right,
      paddingTop: REEL_SAFE.top,
      paddingBottom: REEL_SAFE.bottom,
    }}
  >
    <div
      style={{
        color: brand.colors.text,
        fontFamily: brand.fonts.latin,
        fontWeight: 800,
        fontSize: 84,
        lineHeight: 1.15,
        textAlign: 'center',
      }}
    >
      {text}
    </div>
  </AbsoluteFill>
);
