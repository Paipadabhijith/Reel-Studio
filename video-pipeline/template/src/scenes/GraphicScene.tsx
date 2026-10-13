import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {Backdrop} from '../packs/Backdrop';
import {Headline, Kicker, Panel, useEnter} from '../packs/Chrome';
import {useTheme} from '../theme';
import {formatStat, parseStat} from '../utils/format';
import {safeFor} from '../utils/safeZones';

export type Item = {label: string; value?: string | null};
export type GraphicParams = {
  template?: 'headline' | 'versus' | 'timeline' | 'list' | 'quote' | 'scorecard';
  style?: 'kinetic' | 'burst' | 'rings';
  headline?: string;
  kicker?: string | null;
  subline?: string | null;
  items?: Item[];
  quote?: string | null;
  attribution?: string | null;
  keywords?: string[];
};

type Box = {left: number; top: number; width: number; height: number};

/** Where content may go: reels keep clear of the Reels UI on top and the caption band from ~60% down. */
const contentBox = (kind: 'reel' | 'long', width: number, height: number): Box => {
  const safe = safeFor(kind);
  const top = kind === 'reel' ? safe.top : safe.top + 40;
  const bottom = kind === 'reel' ? height * 0.6 : height - safe.bottom - 40;
  return {left: safe.left, top, width: width - safe.left - safe.right, height: bottom - top};
};

/** Headline size that fits the longest word on one line (display faces run ~0.55 em per character). */
const fitSize = (text: string, maxW: number, cap: number) => {
  const longest = Math.max(...text.split(/\s+/).map((w) => w.length), 3);
  return Math.min(cap, maxW / (longest * 0.58));
};

/** Items appear one after another across the first part of the scene, never faster than the eye can follow. */
const stagger = (i: number, n: number, len: number, fps: number) => {
  const span = Math.min(len * 0.5, n * fps * 0.55);
  return Math.round(8 + (n > 1 ? (span / n) * i : 0));
};

const CountUp: React.FC<{value: string; delay: number}> = ({value, delay}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const parsed = parseStat(value);
  if (!parsed) return <>{value}</>;
  const p = interpolate(frame - delay, [0, fps * 1.1], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return <>{formatStat(parsed, 1 - Math.pow(1 - p, 3))}</>;
};

/** Faint motion behind a headline (broadcast and editorial only): rays or pulses in the accent colour. */
const HeadlineMotion: React.FC<{style?: string; cx: number; cy: number}> = ({style, cx, cy}) => {
  const t = useTheme();
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  if (t.pack === 'archival' || (style !== 'burst' && style !== 'rings')) return null;
  const s = frame / fps;
  if (style === 'burst') {
    const len = Math.max(width, height);
    return (
      <svg width={width} height={height} style={{position: 'absolute', inset: 0}}>
        {Array.from({length: 18}, (_, i) => {
          const a = (i / 18) * Math.PI * 2 + s * 0.1;
          const w = 0.05;
          const pts = [[cx, cy], [cx + Math.cos(a - w) * len, cy + Math.sin(a - w) * len], [cx + Math.cos(a + w) * len, cy + Math.sin(a + w) * len]];
          return <polygon key={i} points={pts.map((p) => p.join(',')).join(' ')} fill={t.accent} opacity={i % 2 ? 0.07 : 0.02} />;
        })}
      </svg>
    );
  }
  return (
    <svg width={width} height={height} style={{position: 'absolute', inset: 0}}>
      {Array.from({length: 4}, (_, i) => {
        const p = (s * 0.3 + i / 4) % 1;
        return <circle key={i} cx={cx} cy={cy} r={80 + p * Math.min(width, height) * 0.6} fill="none" stroke={t.accent} strokeWidth={4 * (1 - p) + 1} opacity={0.35 * (1 - p)} />;
      })}
    </svg>
  );
};

const HeadlineT: React.FC<{p: GraphicParams; box: Box; reel: boolean}> = ({p, box, reel}) => {
  const t = useTheme();
  const head = (p.headline || '').trim();
  const size = fitSize(head, box.width, reel ? 190 : 170);
  const sub = useEnter(14);
  return (
    <>
      <HeadlineMotion style={p.style} cx={box.left + box.width / 2} cy={box.top + box.height * 0.5} />
      <div style={{position: 'absolute', ...box, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: size * 0.22, textAlign: 'center'}}>
        {p.kicker ? <Kicker text={p.kicker} size={reel ? 40 : 34} /> : null}
        <Headline text={head} size={size} maxW={box.width} delay={4} />
        {p.subline ? (
          <div style={{fontFamily: t.pack === 'archival' ? t.label : t.body, fontWeight: t.pack === 'archival' ? 400 : 600, fontSize: reel ? 40 : 36,
                       color: t.muted, opacity: sub, lineHeight: 1.3, maxWidth: box.width * 0.92}}>
            {p.subline}
          </div>
        ) : null}
      </div>
    </>
  );
};

const Title: React.FC<{p: GraphicParams; box: Box; reel: boolean; size?: number}> = ({p, box, reel, size}) => {
  if (!p.headline && !p.kicker) return null;
  const s = size ?? Math.min(reel ? 96 : 84, fitSize(p.headline || '', box.width, 120));
  return (
    <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: s * 0.2, marginBottom: s * 0.35}}>
      {p.kicker ? <Kicker text={p.kicker} size={reel ? 34 : 30} /> : null}
      {p.headline ? <Headline text={p.headline} size={s} maxW={box.width} /> : null}
    </div>
  );
};

const VersusT: React.FC<{p: GraphicParams; box: Box; reel: boolean; len: number}> = ({p, box, reel, len}) => {
  const t = useTheme();
  const {fps} = useVideoConfig();
  const [a, b] = p.items ?? [];
  const sides = [a, b].filter(Boolean) as Item[];
  const vs = useEnter(stagger(1, 2, len, fps) + 6);
  const side = (it: Item, i: number) => {
    const d = stagger(i, 2, len, fps);
    return <Side key={i} it={it} i={i} delay={d} reel={reel} />;
  };
  return (
    <div style={{position: 'absolute', ...box, display: 'flex', flexDirection: 'column', justifyContent: 'center'}}>
      <Title p={p} box={box} reel={reel} />
      <div style={{display: 'flex', flexDirection: reel ? 'column' : 'row', alignItems: 'stretch', gap: reel ? 26 : 40, position: 'relative'}}>
        {sides.map(side)}
        <div style={{position: 'absolute', left: '50%', top: '50%', transform: `translate(-50%, -50%) scale(${vs})`, width: reel ? 120 : 130, height: reel ? 120 : 130,
                     borderRadius: t.pack === 'broadcast' ? 0 : '50%', background: t.pack === 'archival' ? t.text : t.accent2,
                     rotate: t.pack === 'broadcast' ? '45deg' : '0deg', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 2}}>
          <span style={{rotate: t.pack === 'broadcast' ? '-45deg' : '0deg', fontFamily: t.display, fontWeight: t.displayWeight, fontSize: reel ? 52 : 56,
                        color: t.pack === 'archival' ? t.surface : '#FFFFFF', fontStyle: t.pack === 'archival' ? 'italic' : 'normal'}}>vs</span>
        </div>
      </div>
    </div>
  );
};

const Side: React.FC<{it: Item; i: number; delay: number; reel: boolean}> = ({it, i, delay, reel}) => {
  const t = useTheme();
  const p = useEnter(delay);
  const hl = i === 0;
  const fg = hl && t.pack !== 'archival' ? t.onAccent : t.text;
  return (
    <Panel p={p} highlight={hl} seed={i} style={{flex: 1, padding: reel ? '34px 44px' : '40px 48px'}}>
      <div style={{fontFamily: t.label, fontSize: reel ? 40 : 36, color: hl && t.pack !== 'archival' ? fg : t.muted, letterSpacing: '0.04em',
                   textTransform: t.labelUpper ? 'uppercase' : 'none'}}>{it.label}</div>
      {it.value ? (
        <div style={{fontFamily: t.display, fontWeight: t.displayWeight, fontSize: reel ? 130 : 120, lineHeight: 1.05, color: hl && t.pack === 'archival' ? t.accent : fg}}>
          <CountUp value={it.value} delay={delay + 4} />
        </div>
      ) : null}
    </Panel>
  );
};

const TimelineT: React.FC<{p: GraphicParams; box: Box; reel: boolean; len: number}> = ({p, box, reel, len}) => {
  const t = useTheme();
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const items = p.items ?? [];
  const n = items.length;
  const draw = interpolate(frame, [6, stagger(n - 1, n, len, fps) + 10], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const row = reel ? 44 : 32;
  return (
    <div style={{position: 'absolute', ...box, display: 'flex', flexDirection: 'column', justifyContent: 'center'}}>
      <Title p={p} box={box} reel={reel} size={reel ? 84 : 72} />
      <div style={{position: 'relative', paddingLeft: 70}}>
        <div style={{position: 'absolute', left: 22, top: 10, width: 6, height: `calc(${draw * 100}% - 20px)`,
                     background: t.pack === 'archival' ? `repeating-linear-gradient(to bottom, ${t.text} 0 14px, transparent 14px 24px)` : t.accent}} />
        {items.map((it, i) => (
          <TimelineRow key={i} it={it} delay={stagger(i, n, len, fps)} size={row} />
        ))}
      </div>
    </div>
  );
};

const TimelineRow: React.FC<{it: Item; delay: number; size: number}> = ({it, delay, size}) => {
  const t = useTheme();
  const p = useEnter(delay);
  return (
    <div style={{position: 'relative', marginBottom: size * 1.1, opacity: Math.min(p * 1.5, 1), transform: `translateX(${(1 - p) * 40}px)`}}>
      <div style={{position: 'absolute', left: -62, top: size * 0.55, width: 30, height: 30, borderRadius: t.pack === 'broadcast' ? 0 : '50%',
                   background: t.accent, border: `5px solid ${t.bg}`, transform: `scale(${p})`}} />
      <div style={{fontFamily: t.pack === 'archival' ? t.label : t.display, fontWeight: t.pack === 'archival' ? 400 : t.displayWeight,
                   fontSize: size * 2.2, lineHeight: 1, color: t.accent}}>{it.label}</div>
      {it.value ? <div style={{fontFamily: t.body, fontWeight: 700, fontSize: size * 1.2, color: t.text, marginTop: 6, lineHeight: 1.2}}>{it.value}</div> : null}
    </div>
  );
};

const ListT: React.FC<{p: GraphicParams; box: Box; reel: boolean; len: number}> = ({p, box, reel, len}) => {
  const {fps} = useVideoConfig();
  const items = p.items ?? [];
  return (
    <div style={{position: 'absolute', ...box, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: reel ? 26 : 20}}>
      <Title p={p} box={box} reel={reel} size={reel ? 84 : 72} />
      {items.map((it, i) => <ListRow key={i} it={it} i={i} delay={stagger(i, items.length, len, fps)} reel={reel} />)}
    </div>
  );
};

const ListRow: React.FC<{it: Item; i: number; delay: number; reel: boolean}> = ({it, i, delay, reel}) => {
  const t = useTheme();
  const p = useEnter(delay);
  const num = String(i + 1).padStart(2, '0');
  return (
    <Panel p={p} seed={i + 3} style={{display: 'flex', alignItems: 'center', gap: 28, padding: reel ? '20px 30px' : '18px 28px'}}>
      <div style={{fontFamily: t.pack === 'archival' ? t.label : t.display, fontWeight: t.pack === 'archival' ? 400 : t.displayWeight,
                   fontSize: reel ? 92 : 62, color: t.accent, minWidth: reel ? 120 : 84, lineHeight: 1}}>{num}</div>
      <div>
        <div style={{fontFamily: t.pack === 'archival' ? t.display : t.body, fontWeight: 800, fontSize: reel ? 64 : 44, color: t.text, lineHeight: 1.1}}>{it.label}</div>
        {it.value ? <div style={{fontFamily: t.body, fontWeight: 500, fontSize: reel ? 40 : 28, color: t.muted, marginTop: 4}}>{it.value}</div> : null}
      </div>
    </Panel>
  );
};

const QuoteT: React.FC<{p: GraphicParams; box: Box; reel: boolean}> = ({p, box, reel}) => {
  const t = useTheme();
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const mark = useEnter(0);
  const who = useEnter(Math.round(fps * 0.9));
  const quote = (p.quote || p.headline || '').trim();
  // the quote types itself out (typewriter in archival, a quick reveal elsewhere)
  const cps = t.pack === 'archival' ? 22 : 45;
  const shown = Math.min(quote.length, Math.floor(Math.max(0, frame - 6) / fps * cps));
  const size = reel ? (quote.length > 70 ? 70 : 86) : quote.length > 70 ? 56 : 66;
  return (
    <div style={{position: 'absolute', ...box, display: 'flex', flexDirection: 'column', justifyContent: 'center'}}>
      <div style={{fontFamily: t.display, fontSize: reel ? 260 : 220, lineHeight: 0.6, color: t.accent,
                   opacity: mark, transform: `scale(${0.6 + 0.4 * mark})`, transformOrigin: 'left top', height: reel ? 140 : 120}}>“</div>
      <div style={{fontFamily: t.pack === 'archival' ? t.label : t.body, fontWeight: t.pack === 'archival' ? 400 : 800, fontSize: size,
                   lineHeight: 1.25, color: t.text}}>
        {quote.slice(0, shown)}
        <span style={{opacity: 0}}>{quote.slice(shown)}</span>
      </div>
      {p.attribution ? (
        <div style={{marginTop: 34, display: 'flex', alignItems: 'center', gap: 18, opacity: who}}>
          <div style={{width: 60, height: 6, background: t.accent}} />
          <span style={{fontFamily: t.pack === 'archival' ? t.display : t.label, fontWeight: 700, fontSize: reel ? 42 : 36, color: t.text,
                        fontStyle: t.pack === 'archival' ? 'italic' : 'normal', textTransform: t.pack === 'archival' ? 'none' : 'uppercase'}}>{p.attribution}</span>
        </div>
      ) : null}
    </div>
  );
};

const ScorecardT: React.FC<{p: GraphicParams; box: Box; reel: boolean; len: number}> = ({p, box, reel, len}) => {
  const t = useTheme();
  const {fps} = useVideoConfig();
  const items = p.items ?? [];
  const bar = useEnter(0);
  return (
    <div style={{position: 'absolute', ...box, display: 'flex', flexDirection: 'column', justifyContent: 'center'}}>
      {p.kicker ? <div style={{marginBottom: 18}}><Kicker text={p.kicker} size={reel ? 34 : 30} /></div> : null}
      {p.headline ? (
        <div style={{background: t.pack === 'archival' ? t.text : t.accent, padding: reel ? '18px 30px' : '16px 28px', opacity: bar,
                     transform: `scaleX(${0.3 + 0.7 * bar})`, transformOrigin: 'left',
                     fontFamily: t.display, fontWeight: t.displayWeight, fontSize: reel ? 80 : 56, lineHeight: 1.1,
                     color: t.pack === 'archival' ? t.surface : t.onAccent, textTransform: t.displayUpper ? 'uppercase' : 'none'}}>
          {p.headline}
        </div>
      ) : null}
      {items.map((it, i) => <ScoreRow key={i} it={it} i={i} delay={stagger(i, items.length, len, fps) + 4} reel={reel} />)}
    </div>
  );
};

const ScoreRow: React.FC<{it: Item; i: number; delay: number; reel: boolean}> = ({it, i, delay, reel}) => {
  const t = useTheme();
  const p = useEnter(delay);
  const shade = t.pack === 'archival' ? (i % 2 ? 'rgba(60,40,20,0.06)' : 'transparent') : i % 2 ? 'rgba(255,255,255,0.04)' : t.surface;
  return (
    <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: reel ? '20px 30px' : '16px 28px', background: shade,
                 borderBottom: t.pack === 'archival' ? `2px dashed ${t.muted}` : `2px solid rgba(255,255,255,0.06)`,
                 opacity: Math.min(p * 1.5, 1), transform: `translateX(${(1 - p) * 60}px)`}}>
      <span style={{fontFamily: t.pack === 'archival' ? t.label : t.body, fontWeight: 700, fontSize: reel ? 56 : 38, color: t.text,
                    textTransform: t.pack === 'archival' ? 'uppercase' : 'none'}}>{it.label}</span>
      {it.value ? (
        <span style={{fontFamily: t.display, fontWeight: t.displayWeight, fontSize: reel ? 92 : 60, color: t.accent, lineHeight: 1}}>
          <CountUp value={it.value} delay={delay} />
        </span>
      ) : null}
    </div>
  );
};

/** A graphic scene in the video's style pack. Unknown or incomplete templates fall back to a headline. */
export const GraphicScene: React.FC<{params: GraphicParams; kind: 'reel' | 'long'; seed: number; len: number}> = ({params, kind, seed, len}) => {
  const {width, height} = useVideoConfig();
  const box = contentBox(kind, width, height);
  const reel = kind === 'reel';
  const n = params.items?.length ?? 0;
  let tpl = params.template ?? 'headline';
  if ((tpl === 'versus' && n < 2) || ((tpl === 'timeline' || tpl === 'scorecard') && n < 2) || (tpl === 'list' && n < 3) || (tpl === 'quote' && !params.quote)) {
    tpl = 'headline';
  }
  // an old-style headline graphic with keywords keeps them as a list when there are enough
  const p = {...params, headline: params.headline || params.keywords?.join(' ') || ''};
  return (
    <AbsoluteFill style={{overflow: 'hidden'}}>
      <Backdrop seed={seed} />
      {tpl === 'versus' ? <VersusT p={p} box={box} reel={reel} len={len} />
        : tpl === 'timeline' ? <TimelineT p={p} box={box} reel={reel} len={len} />
          : tpl === 'list' ? <ListT p={p} box={box} reel={reel} len={len} />
            : tpl === 'quote' ? <QuoteT p={p} box={box} reel={reel} />
              : tpl === 'scorecard' ? <ScorecardT p={p} box={box} reel={reel} len={len} />
                : <HeadlineT p={p} box={box} reel={reel} />}
    </AbsoluteFill>
  );
};
