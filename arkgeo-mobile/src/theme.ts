/**
 * ArkGeo tactical theme — OLED dark slate with electric cyan & emergency red.
 */

export const Colors = {
  // Backgrounds
  bgDarkest: '#0B0F17',
  bgDark: '#111827',
  bgCard: '#1A2332',
  bgCardElevated: '#243044',
  bgInput: '#0D1421',

  // Accents
  cyan: '#38BDF8',
  cyanDim: '#0EA5E9',
  cyanBright: '#7DD3FC',

  // States
  emergency: '#EF4444',
  emergencyDim: '#B91C1C',
  success: '#22C55E',
  warning: '#F59E0B',

  // Text
  textPrimary: '#F1F5F9',
  textSecondary: '#94A3B8',
  textMuted: '#64748B',

  // Borders
  border: '#334155',
  borderDim: '#1E293B',
};

export const Typography = {
  title: { fontSize: 22, fontWeight: 'bold' as const, color: Colors.textPrimary },
  subtitle: { fontSize: 16, fontWeight: '600' as const, color: Colors.textPrimary },
  body: { fontSize: 14, color: Colors.textSecondary },
  caption: { fontSize: 12, color: Colors.textMuted },
  mono: { fontSize: 13, color: Colors.cyanBright, letterSpacing: 0.5 },
};

export const Spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
};

export const BorderRadius = {
  sm: 6,
  md: 10,
  lg: 16,
  pill: 999,
};
