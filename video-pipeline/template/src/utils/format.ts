export type ParsedStat = {prefix: string; value: number; decimals: number; suffix: string; grouped: boolean};

/** "76%" -> {value: 76, suffix: '%'}; "₹1,20,000 cr" -> prefix '₹', value 120000, suffix ' cr'. Non-numeric -> null. */
export const parseStat = (raw: string): ParsedStat | null => {
  const m = raw.trim().match(/^([^\d\-.]*)(-?[\d,]*\.?\d+)(.*)$/);
  if (!m) return null;
  const numText = m[2];
  const value = parseFloat(numText.replace(/,/g, ''));
  if (Number.isNaN(value)) return null;
  const decimals = numText.includes('.') ? numText.split('.')[1].length : 0;
  return {prefix: m[1], value, decimals, suffix: m[3], grouped: numText.includes(',')};
};

export const formatStat = (p: ParsedStat, progress: number): string => {
  const v = p.value * progress;
  const text = p.grouped
    ? new Intl.NumberFormat('en-IN', {minimumFractionDigits: p.decimals, maximumFractionDigits: p.decimals}).format(v)
    : v.toFixed(p.decimals);
  return `${p.prefix}${text}${p.suffix}`;
};

export const PALETTE = ['#FFD23F', '#7C8CF8', '#4FD1C5', '#F687B3', '#A0AEC0', '#F6AD55'];
