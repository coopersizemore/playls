import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { CssBaseline, useMediaQuery } from '@mui/material';
import { ThemeProvider } from '@mui/material/styles';
import { readStored, writeStored } from './storage';
import { buildTheme } from './theme';

// Light / dark mode. The preference ('light' | 'dark' | 'system') is a per-browser
// convenience kept in localStorage; 'system' follows the device setting.
const STORAGE_KEY = 'playls-color-mode';

const PREFERENCES = ['light', 'dark', 'system'];

const storedPreference = () => {
  const value = readStored(STORAGE_KEY, 'system');
  return PREFERENCES.includes(value) ? value : 'system';
};

const ColorModeContext = createContext({ preference: 'system', mode: 'light', setPreference: () => {}, toggle: () => {} });

export const useColorMode = () => useContext(ColorModeContext);

export const ColorModeProvider = ({ children }) => {
  const prefersDark = useMediaQuery('(prefers-color-scheme: dark)', { noSsr: true });
  const [preference, setPreferenceState] = useState(storedPreference);
  const mode = preference === 'system' ? (prefersDark ? 'dark' : 'light') : preference;

  const setPreference = (value) => {
    setPreferenceState(value);
    writeStored(STORAGE_KEY, value); // if it can't be saved, it still applies for this visit
  };

  // Keep the browser chrome (mobile address bar) in step with the theme
  useEffect(() => {
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', mode === 'dark' ? '#121212' : '#ffffff');
  }, [mode]);

  const theme = useMemo(() => buildTheme(mode), [mode]);
  const value = {
    preference,
    mode,
    setPreference,
    toggle: () => setPreference(mode === 'dark' ? 'light' : 'dark'),
  };

  return (
    <ColorModeContext.Provider value={value}>
      <ThemeProvider theme={theme}>
        <CssBaseline enableColorScheme />
        {children}
      </ThemeProvider>
    </ColorModeContext.Provider>
  );
};
