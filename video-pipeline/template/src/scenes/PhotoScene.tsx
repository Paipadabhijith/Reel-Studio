import React from 'react';
import {AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame} from 'remotion';

export const PhotoScene: React.FC<{file: string; motion: string; durationInFrames: number}> = ({
  file,
  motion,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [0, Math.max(durationInFrames, 1)], [0, 1], {
    extrapolateRight: 'clamp',
  });
  let transform = 'scale(1)';
  if (motion === 'none') transform = 'scale(1)';
  else if (motion === 'slow-zoom-out') transform = `scale(${1.15 - 0.15 * p})`;
  else if (motion === 'pan-left') transform = `scale(1.15) translateX(${(0.5 - p) * 6}%)`;
  else if (motion === 'pan-right') transform = `scale(1.15) translateX(${(p - 0.5) * 6}%)`;
  else transform = `scale(${1 + 0.15 * p})`; // slow-zoom-in (default)

  return (
    <AbsoluteFill style={{overflow: 'hidden', backgroundColor: '#000'}}>
      <Img
        src={staticFile(file)}
        style={{width: '100%', height: '100%', objectFit: motion === 'none' ? 'contain' : 'cover', transform}}
      />
      <AbsoluteFill
        style={{background: 'linear-gradient(to bottom, rgba(0,0,0,0.25), rgba(0,0,0,0) 30%, rgba(0,0,0,0.45))'}}
      />
    </AbsoluteFill>
  );
};
