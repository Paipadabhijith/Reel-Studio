import React from 'react';
import {AbsoluteFill, Audio, Sequence, staticFile} from 'remotion';
import {WordCaptions} from '../captions/WordCaptions';
import {PhotoScene} from '../scenes/PhotoScene';
import {TextCardScene} from '../scenes/TextCardScene';
import {VideoScene} from '../scenes/VideoScene';
import type {Brand, ReelProps, SceneProps} from '../types';
import {REEL_SAFE} from '../utils/safeZones';

const SceneVisual: React.FC<{sc: SceneProps; brand: Brand; len: number}> = ({sc, brand, len}) => {
  if (sc.visual.type === 'photo' && sc.visual.file) {
    return <PhotoScene file={sc.visual.file} motion={sc.visual.motion} durationInFrames={len} />;
  }
  if (sc.visual.type === 'video' && sc.visual.file) {
    return <VideoScene file={sc.visual.file} clipFrames={sc.visual.clipFrames ?? undefined} />;
  }
  return <TextCardScene text={sc.text} brand={brand} />;
};

const DraftLabel: React.FC<{text: string; top: number}> = ({text, top}) => (
  <div
    style={{
      position: 'absolute',
      top,
      left: REEL_SAFE.left,
      right: REEL_SAFE.right,
      padding: '12px 20px',
      borderRadius: 12,
      background: 'rgba(220, 38, 38, 0.9)',
      color: '#fff',
      fontFamily: 'Inter, Helvetica, Arial, sans-serif',
      fontWeight: 700,
      fontSize: 34,
      lineHeight: 1.25,
    }}
  >
    {text}
  </div>
);

export const Reel: React.FC<ReelProps> = ({scenes, brand, audioSrc, fps, emphasisMarks, durationInFrames, draft}) => (
  <AbsoluteFill style={{backgroundColor: brand.colors.background}}>
    {scenes.map((sc, i) => {
      const from = Math.round(sc.startS * fps);
      const isLast = i === scenes.length - 1;
      const to = isLast ? durationInFrames : Math.round(sc.endS * fps);
      const len = Math.max(to - from, 1);
      return (
        <Sequence key={sc.id} from={from} durationInFrames={len}>
          <SceneVisual sc={sc} brand={brand} len={len} />
          {draft ? <DraftLabel text={`DRAFT · scene ${sc.id}`} top={REEL_SAFE.top - 110} /> : null}
          {draft && sc.visual.placeholder ? <DraftLabel text={sc.visual.placeholder} top={REEL_SAFE.top} /> : null}
        </Sequence>
      );
    })}
    <WordCaptions scenes={scenes} marks={emphasisMarks} brand={brand} />
    {audioSrc ? <Audio src={staticFile(audioSrc)} /> : null}
  </AbsoluteFill>
);
