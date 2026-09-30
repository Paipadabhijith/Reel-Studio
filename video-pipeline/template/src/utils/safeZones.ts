export type SafeZone = {top: number; bottom: number; left: number; right: number};

// Instagram Reels UI: keep text out of the top 250, bottom 250 and left/right 100 px.
export const REEL_SAFE: SafeZone = {top: 250, bottom: 250, left: 100, right: 100};

export const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

/** Clamp a box's top-left so the whole box sits inside the safe area. */
export const clampBox = (
  x: number,
  y: number,
  w: number,
  h: number,
  frame: {width: number; height: number},
  safe: SafeZone = REEL_SAFE,
) => ({
  x: clamp(x, safe.left, Math.max(safe.left, frame.width - safe.right - w)),
  y: clamp(y, safe.top, Math.max(safe.top, frame.height - safe.bottom - h)),
});
