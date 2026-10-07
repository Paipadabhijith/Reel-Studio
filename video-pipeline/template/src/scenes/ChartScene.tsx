import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import type {Brand} from '../types';
import {PALETTE} from '../utils/format';
import {safeFor} from '../utils/safeZones';

type Params = {
  kind?: 'bar' | 'line' | 'pie';
  title?: string;
  unit?: string | null;
  labels?: string[];
  values?: number[];
};

// show as many decimals as the data has, so 165 never turns into 165.0 while it animates
const fmt = (v: number, unit?: string | null, decimals = 0) => `${v.toFixed(decimals)}${unit ?? ''}`;

/** Bars grow, lines draw, pies sweep, in sequence. Layout stays inside the format's safe zone. */
export const ChartScene: React.FC<{params: Params; brand: Brand; kind: 'reel' | 'long'}> = ({params, brand, kind}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const safe = safeFor(kind);
  const labels = params.labels ?? [];
  const values = params.values ?? [];
  const n = Math.min(labels.length, values.length);
  const type = params.kind ?? 'bar';

  // the reel's caption band starts about 62% down, so charts stay above it
  const bottomLimit = kind === 'reel' ? height * 0.6 : height - safe.bottom;
  const titleSize = kind === 'reel' ? 64 : 56;
  const top = safe.top + (params.title ? titleSize + 110 : 40);  // headroom for the tallest bar's value label
  const chart = {x: safe.left, y: top, w: width - safe.left - safe.right, h: bottomLimit - top - 70};
  const max = Math.max(...values, 1);
  const decimals = values.some((v) => !Number.isInteger(v)) ? 1 : 0;
  const labelSize = kind === 'reel' ? 38 : 32;
  const t = (i: number) => spring({frame: frame - 6 - i * 7, fps, config: {damping: 18, stiffness: 90}});

  return (
    <AbsoluteFill style={{background: `linear-gradient(160deg, ${brand.colors.background}, #1c1c2b)`, fontFamily: brand.fonts.latin}}>
      {params.title ? (
        <div style={{position: 'absolute', top: safe.top, left: safe.left, right: safe.right, textAlign: 'center',
                     color: brand.colors.text, fontWeight: 800, fontSize: titleSize, opacity: interpolate(frame, [0, 12], [0, 1], {extrapolateRight: 'clamp'})}}>
          {params.title}
        </div>
      ) : null}
      <svg width={width} height={height} style={{position: 'absolute', inset: 0}}>
        {type === 'bar' && values.slice(0, n).map((v, i) => {
          const slot = chart.w / n;
          const bw = Math.min(slot * 0.62, 260);
          const x = chart.x + slot * i + (slot - bw) / 2;
          const h = (chart.h * (v / max)) * t(i);
          const y = chart.y + chart.h - h;
          return (
            <g key={i}>
              <rect x={x} y={y} width={bw} height={Math.max(h, 0)} rx={14} fill={PALETTE[i % PALETTE.length]} />
              <text x={x + bw / 2} y={y - 16} textAnchor="middle" fill={brand.colors.text} fontWeight={800}
                    fontSize={labelSize + 6} opacity={t(i)}>{fmt(v * Math.min(t(i), 1), params.unit, decimals)}</text>
              <text x={x + bw / 2} y={chart.y + chart.h + labelSize + 14} textAnchor="middle" fill={brand.colors.text}
                    fontSize={labelSize} opacity={0.9}>{labels[i]}</text>
            </g>
          );
        })}
        {type === 'line' && n > 1 && (() => {
          const pts = values.slice(0, n).map((v, i) => [chart.x + 30 + ((chart.w - 60) * i) / (n - 1), chart.y + chart.h - (chart.h * v) / max] as const);
          const d = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0]},${p[1]}`).join(' ');
          const len = pts.reduce((acc, p, i) => (i ? acc + Math.hypot(p[0] - pts[i - 1][0], p[1] - pts[i - 1][1]) : 0), 0);
          const draw = interpolate(frame, [6, fps * 1.6], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
          return (
            <g>
              <path d={d} fill="none" stroke={brand.colors.accent} strokeWidth={10} strokeLinecap="round" strokeLinejoin="round"
                    strokeDasharray={len} strokeDashoffset={len * (1 - draw)} />
              {pts.map((p, i) => {
                const reveal = draw * (n - 1) >= i - 0.01;
                return (
                  <g key={i} opacity={reveal ? 1 : 0}>
                    <circle cx={p[0]} cy={p[1]} r={14} fill={brand.colors.accent} />
                    <text x={p[0]} y={p[1] - 28} textAnchor="middle" fill={brand.colors.text} fontWeight={800} fontSize={labelSize}>{fmt(values[i], params.unit, decimals)}</text>
                    <text x={p[0]} y={chart.y + chart.h + labelSize + 14} textAnchor="middle" fill={brand.colors.text} fontSize={labelSize}>{labels[i]}</text>
                  </g>
                );
              })}
            </g>
          );
        })()}
        {type === 'pie' && (() => {
          const total = values.slice(0, n).reduce((a, b) => a + b, 0) || 1;
          const r = Math.min(chart.w, chart.h) * 0.36;
          const cx = chart.x + chart.w / 2;
          const cy = chart.y + chart.h * 0.46;
          const sweepAll = interpolate(frame, [6, fps * 1.5], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
          let acc = 0;
          return (
            <g>
              {values.slice(0, n).map((v, i) => {
                const a0 = (acc / total) * Math.PI * 2 - Math.PI / 2;
                acc += v;
                const full = (v / total) * Math.PI * 2;
                const a1 = a0 + full * Math.min(1, Math.max(0, sweepAll * n - i));
                const large = a1 - a0 > Math.PI ? 1 : 0;
                const p = (a: number) => [cx + r * Math.cos(a), cy + r * Math.sin(a)];
                const [x0, y0] = p(a0);
                const [x1, y1] = p(a1);
                const mid = a0 + full / 2;
                return (
                  <g key={i}>
                    {a1 - a0 > 0.001 && <path d={`M${cx},${cy} L${x0},${y0} A${r},${r} 0 ${large} 1 ${x1},${y1} Z`} fill={PALETTE[i % PALETTE.length]} />}
                    <text x={cx + (r + 56) * Math.cos(mid)} y={cy + (r + 56) * Math.sin(mid)} textAnchor="middle" fill={brand.colors.text}
                          fontSize={labelSize} fontWeight={700} opacity={sweepAll * n - i > 0.9 ? 1 : 0}>{labels[i]} {fmt(v, params.unit, decimals)}</text>
                  </g>
                );
              })}
            </g>
          );
        })()}
      </svg>
    </AbsoluteFill>
  );
};
