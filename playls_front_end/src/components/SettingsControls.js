import React, { useState } from 'react';
import { Box, Button, Chip, Collapse, Stack, Typography } from '@mui/material';
import { ExpandLess, ExpandMore } from '@mui/icons-material';

// Shared pieces for the tweakable settings (account Settings page and a rotation's Edit dialog).
// Choices mirror back-end/rest_api/services/preferences.py.

export const SUPER_KEEP_OPTIONS = [
  { value: 2, label: '2× as long' },
  { value: 3, label: '3× as long' },
  { value: 5, label: '5× as long' },
];
export const SKIP_HOLD_OPTIONS = [
  { value: 1, label: 'Until tomorrow' },
  { value: 3, label: '3 days' },
  { value: 7, label: 'A week' },
];
export const ORDER_OPTIONS = [
  { value: 'overdue', label: 'Most overdue first' },
  { value: 'oldest', label: 'Longest in the playlist' },
  { value: 'shuffle', label: 'Shuffled' },
];
export const DECK_OPTIONS = [10, 20, 30, 50].map((n) => ({ value: n, label: `${n} songs` }));
export const DISCOVERY_OPTIONS = [
  { value: 15, label: 'Mostly familiar' },
  { value: 33, label: 'Balanced' },
  { value: 60, label: 'Adventurous' },
];
export const NOT_NOW_OPTIONS = [
  { value: 75, label: 'Gently' },
  { value: 50, label: 'Normally' },
  { value: 25, label: 'Strongly' },
];
export const RECOVERY_OPTIONS = [
  { value: 30, label: 'After a month' },
  { value: 90, label: 'After 3 months' },
  { value: 180, label: 'After 6 months' },
];
export const COOLDOWN_OPTIONS = [
  { value: 14, label: '2 weeks' },
  { value: 28, label: '4 weeks' },
  { value: 56, label: '8 weeks' },
];
export const PICK_OPTIONS = [
  { value: 0, label: 'Never' },
  { value: 10, label: 'Now and then' },
  { value: 25, label: 'Often' },
];
export const BACK_OPTIONS = [
  { value: 0, label: 'None' },
  { value: 20, label: 'Some' },
  { value: 40, label: 'Lots' },
];
// Built-in defaults for auto rotations (no account-wide setting)
export const AUTO_SETTING_DEFAULTS = { return_cooldown_days: 28, pick_percent: 10, bring_back_percent: 20 };

// Wording for the review screens
const TIMES = { 2: 'twice', 3: 'three times', 5: 'five times' };
export const timesWord = (n) => TIMES[n] || `${n} times`;
export const skipReturn = (days) => (days > 1 ? `in ${days} days` : 'tomorrow');

export const labelFor = (options, value) => options.find((o) => o.value === value)?.label ?? String(value);

// A row of choice chips. With `defaultLabel`, a first chip ("Default (…)") stands for null:
// "use the account setting".
export const OptionChips = ({ title, help, options, value, onChange, defaultLabel, disabled }) => (
  <Box sx={{ mt: 2 }}>
    <Typography variant="subtitle2">{title}</Typography>
    {help && <Typography variant="body2" color="text.secondary" sx={{ mb: 0.75 }}>{help}</Typography>}
    <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1, mt: help ? 0 : 0.75 }}>
      {defaultLabel && (
        <Chip label={defaultLabel} onClick={() => onChange(null)} disabled={disabled}
          color={value == null ? 'primary' : 'default'} variant={value == null ? 'filled' : 'outlined'} />
      )}
      {options.map((o) => (
        <Chip key={String(o.value)} label={o.label} onClick={() => onChange(o.value)} disabled={disabled}
          color={value === o.value ? 'primary' : 'default'} variant={value === o.value ? 'filled' : 'outlined'} />
      ))}
    </Stack>
  </Box>
);

// A quiet, collapsed "More options" section, so the defaults stay one tap away but out of the way
export const MoreOptions = ({ children, label = 'More options', defaultOpen = false }) => {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Box sx={{ mt: 2 }}>
      <Button size="small" color="inherit" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        endIcon={open ? <ExpandLess /> : <ExpandMore />} sx={{ color: 'text.secondary', px: 0.5 }}>
        {label}
      </Button>
      <Collapse in={open} unmountOnExit>
        <Box sx={{ pl: 0.5 }}>{children}</Box>
      </Collapse>
    </Box>
  );
};
