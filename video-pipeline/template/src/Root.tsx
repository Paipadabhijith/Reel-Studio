import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {LongForm} from './compositions/LongForm';
import {Reel} from './compositions/Reel';
import type {VideoProps} from './types';

const brand: VideoProps['brand'] = {
  fonts: {latin: 'Inter, Helvetica, Arial, sans-serif', devanagari: 'Noto Sans Devanagari, sans-serif'},
  colors: {
    background: '#0B0B10',
    text: '#FFFFFF',
    accent: '#FFD23F',
    captionActive: '#FFD23F',
    captionInactive: '#FFFFFF',
  },
};

const base = {fps: 30, durationInFrames: 90, audioSrc: null, brand, scenes: [], emphasisMarks: []};
const defaultReel: VideoProps = {...base, reelId: 'reel_01', kind: 'reel', width: 1080, height: 1920, audioSrc: 'audio/narration.m4a'};
const defaultLong: VideoProps = {...base, reelId: 'long', kind: 'long', width: 1920, height: 1080};

// Python passes the real size and length as props, so one pair of compositions covers every video.
const metadata = ({props}: {props: VideoProps}) => ({
  durationInFrames: Math.max(props.durationInFrames, 1),
  fps: props.fps,
  width: props.width,
  height: props.height,
});

export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="Reel" component={Reel} width={1080} height={1920} fps={30} durationInFrames={90}
                 defaultProps={defaultReel} calculateMetadata={metadata} />
    <Composition id="LongForm" component={LongForm} width={1920} height={1080} fps={30} durationInFrames={90}
                 defaultProps={defaultLong} calculateMetadata={metadata} />
  </>
);

registerRoot(RemotionRoot);
