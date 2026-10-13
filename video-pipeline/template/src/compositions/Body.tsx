import React, {useMemo} from 'react';
import {AbsoluteFill, Audio, Sequence, staticFile} from 'remotion';
import {WordCaptions} from '../captions/WordCaptions';
import {useFonts} from '../fonts';
import {ChartScene} from '../scenes/ChartScene';
import {GraphicScene} from '../scenes/GraphicScene';
import {PhotoScene} from '../scenes/PhotoScene';
import {StatOverlay, StatScene} from '../scenes/StatScene';
import {TextCardScene} from '../scenes/TextCardScene';
import {VideoScene} from '../scenes/VideoScene';
import {ThemeContext, makeTheme, useTheme} from '../theme';
import type {Theme} from '../theme';
import type {Brand, SceneProps, VideoProps} from '../types';
import {safeFor} from '../utils/safeZones';
import {Grain, Vignette} from './Look';
import {TransitionIn, half, planTransitions} from './transitions';

/** The older scenes take a Brand; give them one in the pack's colours and type. */
const themedBrand = (brand: Brand, t: Theme): Brand => ({
  fonts: {latin: t.body, devanagari: brand.fonts.devanagari},
  colors: {background: t.bg, text: t.text, accent: t.accent, captionActive: t.captionActive, captionInactive: t.captionText},
});

const SceneVisual: React.FC<{sc: SceneProps; brand: Brand; len: number; kind: 'reel' | 'long'}> = ({sc, brand, len, kind}) => {
  const v = sc.visual;
  const t = useTheme();
  if (v.type === 'photo' && v.file) {
    return <AbsoluteFill style={{filter: t.grade}}><PhotoScene file={v.file} motion={v.motion} durationInFrames={len} /></AbsoluteFill>;
  }
  if ((v.type === 'video' || v.type === 'blender') && v.file) {
    return <AbsoluteFill style={{filter: v.type === 'video' ? t.grade : undefined}}><VideoScene file={v.file} clipFrames={v.clipFrames ?? undefined} /></AbsoluteFill>;
  }
  if (v.type === 'chart' && v.params) return <ChartScene params={v.params} brand={brand} kind={kind} seed={sc.id} />;
  if (v.type === 'animation' && v.params) return <GraphicScene params={v.params} kind={kind} seed={sc.id} len={len} />;
  if (v.type === 'stat') {
    const value = sc.overlay?.value ?? v.params?.value;
    if (value) return <StatScene value={String(value)} label={sc.overlay?.label ?? v.params?.label} brand={brand} kind={kind} seed={sc.id} />;
  }
  return <TextCardScene text={sc.text} headline={v.params?.headline} kind={kind} seed={sc.id} len={len} />;
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
  const {scenes, audioSrc, fps, emphasisMarks, durationInFrames, draft, kind, captions, chapterTitle, direction} = props;
  useFonts();
  const theme = useMemo(() => makeTheme(direction, props.brand), [direction, props.brand]);
  const brand = useMemo(() => themedBrand(props.brand, theme), [props.brand, theme]);
  const safe = safeFor(kind);
  const labelTop = Math.max(safe.top - 110, 10);
  const transitions = planTransitions(scenes.map((sc) => sc.id), theme.transitions);
  const HALF = half(theme);
  return (
    <ThemeContext.Provider value={theme}>
    <AbsoluteFill style={{backgroundColor: theme.bg}}>
      {scenes.map((sc, i) => {
        // each scene starts HALF a transition early and ends HALF late, so the cut sits where it always did
        const cutIn = Math.round(sc.startS * fps);
        const cutOut = i === scenes.length - 1 ? durationInFrames : Math.round(sc.endS * fps);
        const from = i === 0 ? cutIn : Math.max(cutIn - HALF, 0);
        const to = i === scenes.length - 1 ? durationInFrames : Math.min(cutOut + HALF, durationInFrames);
        const len = Math.max(to - from, 1);
        // a stat badge belongs on footage; on a graphic it would sit on top of the headline
        const overlayOnMedia = sc.overlay?.type === 'stat' && sc.overlay.value && ['photo', 'video', 'blender'].includes(sc.visual.type) && !!sc.visual.file;
        return (
          <Sequence key={sc.id} from={from} durationInFrames={len}>
            <TransitionIn kind={transitions[i]}>
              <SceneVisual sc={sc} brand={brand} len={len} kind={kind} />
              {overlayOnMedia ? <StatOverlay value={sc.overlay!.value!} label={sc.overlay!.label} brand={brand} kind={kind} /> : null}
            </TransitionIn>
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
      <Vignette />
      <Grain />
      {captions ? <WordCaptions scenes={scenes} marks={emphasisMarks} brand={brand} /> : null}
      {audioSrc ? <Audio src={staticFile(audioSrc)} /> : null}
    </AbsoluteFill>
    </ThemeContext.Provider>
  );
};
