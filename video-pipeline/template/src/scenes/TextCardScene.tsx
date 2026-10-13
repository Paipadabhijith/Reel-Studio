import React from 'react';
import {AbsoluteFill} from 'remotion';
import {Backdrop} from '../packs/Backdrop';
import {useTheme} from '../theme';
import {safeFor} from '../utils/safeZones';
import {GraphicScene} from './GraphicScene';

/**
 * A short headline in the pack's style, not the sentence: the captions already show what is said.
 * Falls back to the full text only when no headline was given (older props).
 */
export const TextCardScene: React.FC<{text: string; headline?: string | null; kind?: 'reel' | 'long'; seed: number; len: number}> = ({
  text,
  headline,
  kind = 'reel',
  seed,
  len,
}) => {
  const t = useTheme();
  if ((headline || '').trim()) {
    return <GraphicScene params={{template: 'headline', headline: headline!.trim()}} kind={kind} seed={seed} len={len} />;
  }
  const safe = safeFor(kind);
  return (
    <AbsoluteFill style={{justifyContent: 'center', paddingLeft: safe.left, paddingRight: safe.right, paddingTop: safe.top, paddingBottom: safe.bottom}}>
      <Backdrop seed={seed} />
      <div style={{position: 'relative', color: t.text, fontFamily: t.body, fontWeight: 800, fontSize: kind === 'reel' ? 84 : 72, lineHeight: 1.15, textAlign: 'center'}}>
        {text}
      </div>
    </AbsoluteFill>
  );
};
