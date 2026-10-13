import React from 'react';
import {AbsoluteFill, Easing, interpolate, random, useCurrentFrame} from 'remotion';
import type {Theme, TransitionKind} from '../theme';
import {useTheme} from '../theme';

/** One transition per scene from the theme's set, stable for a scene id; never the same kind twice in a row. */
export const planTransitions = (ids: number[], kinds: TransitionKind[]): TransitionKind[] => {
  const out: TransitionKind[] = [];
  ids.forEach((id, i) => {
    if (i === 0) {
      out.push('cut');
      return;
    }
    let k = kinds[Math.floor(random(`tr-${id}`) * kinds.length)];
    if (k === out[i - 1]) k = kinds[(kinds.indexOf(k) + 1) % kinds.length];
    out.push(k);
  });
  return out;
};

/** Frames each side of a cut: the incoming scene starts this early, the outgoing one ends this late. */
export const half = (t: Theme) => Math.floor(t.transitionFrames / 2);

const ease = Easing.bezier(0.65, 0, 0.35, 1);

/** Wraps an incoming scene; animates it in over the theme's transition length. */
export const TransitionIn: React.FC<{kind: TransitionKind; children: React.ReactNode}> = ({kind, children}) => {
  const frame = useCurrentFrame();
  const t = useTheme();
  const n = t.transitionFrames;
  if (kind === 'cut' || frame >= n) return <AbsoluteFill>{children}</AbsoluteFill>;
  const p = interpolate(frame, [0, n], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
  let style: React.CSSProperties = {};
  let over: React.ReactNode = null;
  if (kind === 'wipe-left') style = {clipPath: `inset(0 0 0 ${(1 - p) * 100}%)`};
  else if (kind === 'wipe-up') style = {clipPath: `inset(${(1 - p) * 100}% 0 0 0)`};
  else if (kind === 'zoom') style = {transform: `scale(${1.25 - 0.25 * p})`, opacity: p};
  else if (kind === 'whip') style = {transform: `translateX(${(1 - p) * 100}%)`, filter: `blur(${(1 - p) * 24}px)`};
  else if (kind === 'iris') style = {clipPath: `circle(${p * 80}% at 50% 42%)`};
  else if (kind === 'dissolve') style = {opacity: p};
  else if (kind === 'slide-up') style = {transform: `translateY(${(1 - p) * 18}%)`, opacity: p};
  else if (kind === 'flash') {
    style = {opacity: p < 0.5 ? 0 : 1};
    over = <AbsoluteFill style={{backgroundColor: '#fff', opacity: (1 - Math.abs(2 * p - 1)) * 0.85}} />;
  } else if (kind === 'stinger') {
    // a broadcast stinger: an accent slab sweeps across and the new scene is revealed behind it
    style = {clipPath: `inset(0 ${(1 - p) * 100}% 0 0)`};
    const x = -40 + p * 140;
    over = (
      <AbsoluteFill style={{overflow: 'hidden'}}>
        <div style={{position: 'absolute', top: '-20%', bottom: '-20%', left: `${x - 22}%`, width: '22%', background: t.accent, transform: 'skewX(-14deg)'}} />
        <div style={{position: 'absolute', top: '-20%', bottom: '-20%', left: `${x - 30}%`, width: '6%', background: t.accent2, transform: 'skewX(-14deg)'}} />
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill>
      <AbsoluteFill style={style}>{children}</AbsoluteFill>
      {over}
    </AbsoluteFill>
  );
};
