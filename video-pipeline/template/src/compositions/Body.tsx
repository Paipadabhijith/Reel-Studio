import React from 'react';
import {AbsoluteFill, Audio, Sequence, staticFile} from 'remotion';
import {WordCaptions} from '../captions/WordCaptions';
import {AnimationScene} from '../scenes/AnimationScene';
import {ChartScene} from '../scenes/ChartScene';
import {PhotoScene} from '../scenes/PhotoScene';
import {StatOverlay, StatScene} from '../scenes/StatScene';
import {TextCardScene} from '../scenes/TextCardScene';
import {VideoScene} from '../scenes/VideoScene';
import type {Brand, SceneProps, VideoProps} from '../types';
import {safeFor} from '../utils/safeZones';

const SceneVisual: React.FC<{sc: SceneProps; brand: Brand; len: number; kind: 'reel' | 'long'}> = ({sc, brand, len, kind}) => {
  const v = sc.visual;
  if (v.type === 'photo' && v.file) return <PhotoScene file={v.file} motion={v.motion} durationInFrames={len} />;
  if ((v.type === 'video' || v.type === 'blender') && v.file) {
    return <VideoScene file={v.file} clipFrames={v.clipFrames ?? undefined} />;
  }
  if (v.type === 'chart' && v.params) return <ChartScene params={v.params} brand={brand} kind={kind} />;
  if (v.type === 'animation' && v.params) return <AnimationScene params={v.params} brand={brand} kind={kind} seed={sc.id} />;
  if (v.type === 'stat') {
    const value = sc.overlay?.value ?? v.params?.value;
    if (value) return <StatScene value={String(value)} label={sc.overlay?.label ?? v.params?.label} brand={brand} kind={kind} />;
  }
  return <TextCardScene text={sc.text} brand={brand} kind={kind} />;
};

const Label: React.FC<{text: string; top: number; kind: 'reel' | 'long'}> = ({text, top, kind}) => {
  const safe = safeFor(kind);
  return (
    <div
      style={{
        position: 'absolute',
        top,
        left: safe.left,
        right: safe.right,
        padding: '12px 20px',
        borderRadius: 12,
        background: 'rgba(220, 38, 38, 0.9)',
        color: '#fff',
        fontFamily: 'Inter, Helvetica, Arial, sans-serif',
        fontWeight: 700,
        fontSize: kind === 'reel' ? 34 : 28,
        lineHeight: 1.25,
      }}
    >
      {text}
    </div>
  );
};

/** Everything a video is made of. Reels burn captions in; long-form ships a sidecar .srt instead. */
export const Body: React.FC<VideoProps> = (props) => {
  const {scenes, brand, audioSrc, fps, emphasisMarks, durationInFrames, draft, kind, captions, chapterTitle} = props;
  const safe = safeFor(kind);
  const labelTop = Math.max(safe.top - 110, 10);
  return (
    <AbsoluteFill style={{backgroundColor: brand.colors.background}}>
      {scenes.map((sc, i) => {
        const from = Math.round(sc.startS * fps);
        const to = i === scenes.length - 1 ? durationInFrames : Math.round(sc.endS * fps);
        const len = Math.max(to - from, 1);
        const overlayOnMedia = sc.overlay?.type === 'stat' && sc.overlay.value && sc.visual.type !== 'stat';
        return (
          <Sequence key={sc.id} from={from} durationInFrames={len}>
            <SceneVisual sc={sc} brand={brand} len={len} kind={kind} />
            {overlayOnMedia ? <StatOverlay value={sc.overlay!.value!} label={sc.overlay!.label} brand={brand} kind={kind} /> : null}
            {draft ? (
              <Label
                text={`DRAFT · ${chapterTitle ? chapterTitle + ' · ' : ''}scene ${sc.id}`}
                top={labelTop}
                kind={kind}
              />
            ) : null}
            {draft && sc.visual.placeholder ? <Label text={sc.visual.placeholder} top={labelTop + 56} kind={kind} /> : null}
          </Sequence>
        );
      })}
      {captions ? <WordCaptions scenes={scenes} marks={emphasisMarks} brand={brand} /> : null}
      {audioSrc ? <Audio src={staticFile(audioSrc)} /> : null}
    </AbsoluteFill>
  );
};
