import { createTheme } from '@mui/material/styles';

// Wireframe-inspired look: IBM Plex Mono for text, Roboto for controls, fresh green
// accents, rounded cards with soft shadows. Light and dark variants (see colorMode.js).
const MONO = '"IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, monospace';
const SANS = '"Roboto", "Helvetica", "Arial", sans-serif';

export const GREEN = '#7ED34E';
export const GREEN_DARK = '#5DB032';
export const GREEN_LIGHT = '#A6E37F';
export const ON_GREEN = '#0B0B0B'; // text on green surfaces, in both modes

const PALETTES = {
  light: {
    background: { default: '#F4F4F4', paper: '#FFFFFF' },
    text: { primary: '#111111', secondary: '#5F5F5F' },
    placeholder: { main: '#D9D9D9' }, // empty album art / covers
    surface: { main: '#FAFAFA' }, // the panel behind the song list
    shadow: 'rgba(0,0,0,0.12)',
  },
  dark: {
    background: { default: '#121212', paper: '#1E1E1E' },
    text: { primary: '#F2F2F2', secondary: '#A8A8A8' },
    placeholder: { main: '#3A3A3A' },
    surface: { main: '#181818' },
    shadow: 'rgba(0,0,0,0.5)',
  },
};

export const buildTheme = (mode = 'light') => {
  const p = PALETTES[mode] || PALETTES.light;
  return createTheme({
    palette: {
      mode,
      primary: { main: GREEN, dark: GREEN_DARK, light: GREEN_LIGHT, contrastText: ON_GREEN },
      secondary: { main: '#191414', contrastText: '#FFFFFF' },
      success: { main: '#4CAF50', contrastText: '#FFFFFF' },
      error: { main: mode === 'dark' ? '#EF5350' : '#C62828' },
      background: p.background,
      text: p.text,
      placeholder: p.placeholder,
      surface: p.surface,
    },
    shape: { borderRadius: 12 },
    typography: {
      fontFamily: MONO,
      h1: { fontWeight: 500 },
      h2: { fontWeight: 500 },
      h3: { fontWeight: 500 },
      h4: { fontWeight: 500, letterSpacing: '0.02em' },
      h5: { fontWeight: 500, letterSpacing: '0.02em' },
      h6: { fontWeight: 500 },
      button: { fontFamily: SANS, fontWeight: 500, textTransform: 'none', letterSpacing: 0 },
    },
    components: {
      MuiCssBaseline: {
        styleOverrides: { body: { transition: 'background-color 200ms ease' } },
      },
      MuiCard: {
        styleOverrides: { root: { borderRadius: 16, boxShadow: `0 2px 6px ${p.shadow}`, backgroundImage: 'none' } },
      },
      MuiPaper: { styleOverrides: { root: { backgroundImage: 'none' } } },
      MuiButton: { styleOverrides: { root: { borderRadius: 10 } } },
      MuiChip: { styleOverrides: { root: { fontFamily: SANS } } },
      MuiTab: {
        styleOverrides: { root: { fontFamily: SANS, textTransform: 'none', fontWeight: 500, fontSize: '1rem' } },
      },
      MuiAlert: { styleOverrides: { root: { fontFamily: SANS } } },
    },
  });
};

export default buildTheme('light');
