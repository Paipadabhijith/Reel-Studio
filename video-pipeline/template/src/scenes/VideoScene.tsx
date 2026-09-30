import React from 'react';
import {AbsoluteFill, Loop, OffthreadVideo, staticFile, useVideoConfig} from 'remotion';

// Stock clips are muted (narration is the only audio) and looped if shorter than the scene.
export const VideoScene: React.FC<{file: string; clipFrames?: number}> = ({file, clipFrames}) => {
  const {durationInFrames} = useVideoConfig();
  const video = (
    <OffthreadVideo src={staticFile(file)} muted style={{width: '100%', height: '100%', objectFit: 'cover'}} />
  );
  return (
    <AbsoluteFill style={{backgroundColor: '#000'}}>
      {clipFrames && clipFrames < durationInFrames ? <Loop durationInFrames={clipFrames}>{video}</Loop> : video}
    </AbsoluteFill>
  );
};
