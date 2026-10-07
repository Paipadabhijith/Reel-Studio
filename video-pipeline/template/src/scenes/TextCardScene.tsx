import React from 'react';
import {AbsoluteFill} from 'remotion';
import type {Brand} from '../types';
import {safeFor} from '../utils/safeZones';

export const TextCardScene: React.FC<{text: string; brand: Brand; kind?: 'reel' | 'long'}> = ({
  text,
  brand,
  kind = 'reel',
}) => {
  const safe = safeFor(kind);
  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(160deg, ${brand.colors.background}, #1c1c2b)`,
        justifyContent: 'center',
        paddingLeft: safe.left,
        paddingRight: safe.right,
        paddingTop: safe.top,
        paddingBottom: safe.bottom,
      }}
    >
      <div
        style={{
          color: brand.colors.text,
          fontFamily: brand.fonts.latin,
          fontWeight: 800,
          fontSize: kind === 'reel' ? 84 : 72,
          lineHeight: 1.15,
          textAlign: 'center',
        }}
      >
        {text}
      </div>
    </AbsoluteFill>
  );
};
