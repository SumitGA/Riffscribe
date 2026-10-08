/**
 * Riffscribe's look: a dark "musician studio" (the approved mockups, docs/design). Screens use
 * these tokens and the components in src/ui, never raw colours or font names.
 */
export const colors = {
  background: '#0D0E11',
  surface: '#16181D',
  raised: '#1E2128',
  line: '#2A2E36',
  tabBar: '#121317',
  text: '#F3F4F6',
  muted: '#9CA3AF',
  faint: '#4A505C',
  accent: '#FFB224',
  /** Text and icons on an accent fill. */
  onAccent: '#1B1305',
  success: '#3DD68C',
  danger: '#FF6B6B',
  dangerText: '#FF8A8A',
} as const;

export const fonts = {
  display: 'SpaceGrotesk_700Bold',
  displayMedium: 'SpaceGrotesk_500Medium',
  body: 'IBMPlexSans_400Regular',
  bodyMedium: 'IBMPlexSans_500Medium',
  bodySemiBold: 'IBMPlexSans_600SemiBold',
  mono: 'JetBrainsMono_500Medium',
  monoBold: 'JetBrainsMono_700Bold',
} as const;

export const radius = { sm: 10, md: 14, lg: 16, xl: 20, pill: 999 } as const;

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, xxl: 28 } as const;

/** Smallest comfortable touch target (WCAG, platform guidelines). */
export const TOUCH = 44;
