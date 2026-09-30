import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {Reel} from './compositions/Reel';
import type {ReelProps} from './types';

const defaultReel: ReelProps = {
  reelId: 'reel_01',
  fps: 30,
  width: 1080,
  height: 1920,
  durationInFrames: 90,
  audioSrc: 'audio/narration.m4a',
  brand: {
    fonts: {latin: 'Inter, Helvetica, Arial, sans-serif', devanagari: 'Noto Sans Devanagari, sans-serif'},
    colors: {
      background: '#0B0B10',
      text: '#FFFFFF',
      accent: '#FFD23F',
      captionActive: '#FFD23F',
      captionInactive: '#FFFFFF',
    },
  },
  scenes: [],
  emphasisMarks: [],
};

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="Reel"
      component={Reel}
      width={1080}
      height={1920}
      fps={30}
      durationInFrames={90}
      defaultProps={defaultReel}
      calculateMetadata={({props}) => ({
        durationInFrames: Math.max(props.durationInFrames, 1),
        fps: props.fps,
        width: props.width,
        height: props.height,
      })}
    />
    {/* LongForm (1920x1080) is registered in Phase 3 */}
  </>
);

registerRoot(RemotionRoot);
