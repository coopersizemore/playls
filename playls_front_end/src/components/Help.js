import React, { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  IconButton,
  Typography,
} from '@mui/material';
import { Add, ArrowBack, ArrowForward, Close, QueueMusic } from '@mui/icons-material';
import { keyframes } from '@mui/system';
import { ON_GREEN } from '../theme';

// A short first-run guide: what a rotation is, reviewing, restocking, history, and one warning.
// Opened from the ? in the top bar, and by Home for a new account that hasn't seen it on this device.

const SEEN_KEY = (userId) => `playls.helpSeen.${userId}`;

export const hasSeenHelp = (userId) => {
  try {
    return localStorage.getItem(SEEN_KEY(userId)) === '1';
  } catch (e) {
    return true; // storage blocked: don't pop up on every visit
  }
};

export const markHelpSeen = (userId) => {
  try {
    localStorage.setItem(SEEN_KEY(userId), '1');
  } catch (e) {
    // private window or blocked storage: nothing to remember
  }
};

const noMotion = '@media (prefers-reduced-motion: reduce)';
const spin = keyframes`from { transform: rotate(0deg); } to { transform: rotate(360deg); }`;
const sway = keyframes`
  0%, 100% { transform: translateX(0) rotate(0deg); }
  25% { transform: translateX(14px) rotate(5deg); }
  75% { transform: translateX(-14px) rotate(-5deg); }
`;

const Art = ({ size = 28, color = 'placeholder.main', sx }) => (
  <Box sx={{ width: size, height: size, borderRadius: 1, bgcolor: color, flexShrink: 0, ...sx }} />
);

const Line = ({ width, sx }) => (
  <Box sx={{ height: 6, width, borderRadius: 3, bgcolor: 'placeholder.main', ...sx }} />
);

// ---------- visuals ----------

// A lazy Susan: songs ride around the turntable and come up for review at the front.
// Also used on the logged-out landing page, without the "Due" marker.
export const RotationVisual = ({ showDue = true }) => {
  const n = 8;
  const radius = 56;
  return (
    <Box sx={{ position: 'relative', width: 160, height: 160, mx: 'auto' }}>
      <Box sx={{
        position: 'absolute', inset: 8, borderRadius: '50%', border: '2px dashed', borderColor: 'placeholder.main',
        animation: `${spin} 24s linear infinite`, [noMotion]: { animation: 'none' },
      }}>
        {Array.from({ length: n }, (_, i) => {
          const angle = (360 / n) * i;
          return (
            <Box key={i} sx={{
              position: 'absolute', top: '50%', left: '50%', width: 26, height: 26, mt: '-13px', ml: '-13px',
              transform: `rotate(${angle}deg) translateY(-${radius}px) rotate(-${angle}deg)`,
            }}>
              <Art size={26} color={i % 3 === 0 ? 'text.secondary' : 'placeholder.main'} sx={{ opacity: i % 3 === 0 ? 0.5 : 1 }} />
            </Box>
          );
        })}
      </Box>
      <Box sx={{
        position: 'absolute', inset: 0, m: 'auto', width: 44, height: 44, borderRadius: '50%',
        bgcolor: 'surface.main', display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <QueueMusic sx={{ color: 'text.secondary' }} />
      </Box>
      {/* The review point at the front of the turntable */}
      {showDue && (
        <Chip size="small" label="Due" color="primary"
          sx={{ position: 'absolute', bottom: -6, left: '50%', transform: 'translateX(-50%)', fontWeight: 600 }} />
      )}
    </Box>
  );
};

// The review card, swaying between Remove and Keep
const ReviewVisual = () => (
  <Box display="flex" alignItems="center" justifyContent="center" gap={1.5} sx={{ height: 160 }}>
    <Chip size="small" icon={<ArrowBack />} label="Remove" color="error" variant="outlined" />
    <Box sx={{
      width: 92, p: 1, borderRadius: 2, bgcolor: 'background.paper', boxShadow: 3,
      animation: `${sway} 4s ease-in-out infinite`, [noMotion]: { animation: 'none' },
    }}>
      <Art size="100%" sx={{ aspectRatio: '1 / 1', height: 'auto', mb: 1 }} />
      <Line width="80%" sx={{ mb: 0.75 }} />
      <Line width="55%" />
    </Box>
    <Chip size="small" icon={<ArrowForward />} label="Keep" color="success" variant="outlined" />
  </Box>
);

// A small deck of suggestions, with where they come from
const RestockVisual = () => (
  <Box sx={{ height: 160, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 2 }}>
    <Box sx={{ position: 'relative', width: 96, height: 84 }}>
      {[2, 1, 0].map((i) => (
        <Box key={i} sx={{
          position: 'absolute', inset: 0, borderRadius: 2, bgcolor: i ? 'surface.main' : 'background.paper', boxShadow: 2,
          transform: `translate(${i * 8}px, ${-i * 8}px)`, p: 1, display: 'flex', gap: 1, alignItems: 'center',
        }}>
          {i === 0 && (<><Art size={36} /><Box flexGrow={1}><Line width="90%" sx={{ mb: 0.75 }} /><Line width="60%" /></Box></>)}
        </Box>
      ))}
      <Box sx={{
        position: 'absolute', right: -14, bottom: -12, width: 32, height: 32, borderRadius: '50%',
        bgcolor: 'primary.main', color: ON_GREEN, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: 2,
      }}>
        <Add fontSize="small" />
      </Box>
    </Box>
    <Box display="flex" gap={0.75} flexWrap="wrap" justifyContent="center">
      {['For you', 'Bring back', 'Picks'].map((s) => <Chip key={s} size="small" label={s} variant="outlined" />)}
    </Box>
  </Box>
);

// A few history rows
const HistoryVisual = () => (
  <Box sx={{ height: 160, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 1, maxWidth: 240, mx: 'auto' }}>
    {[['Kept', 'success'], ['Removed', 'error'], ['Kept', 'success']].map(([label, color], i) => (
      <Box key={i} display="flex" alignItems="center" gap={1.25}
        sx={{ p: 1, borderRadius: 2, bgcolor: 'surface.main' }}>
        <Art size={30} />
        <Box flexGrow={1}><Line width="85%" sx={{ mb: 0.75 }} /><Line width="50%" /></Box>
        <Chip size="small" label={label} color={color} />
      </Box>
    ))}
  </Box>
);

// ---------- the guide ----------

const STEPS = [
  {
    title: 'Rotations',
    visual: <RotationVisual />,
    body: 'A rotation wraps a Spotify playlist you own. Like a lazy Susan, it brings each song back around on a schedule you choose, say once a month.',
  },
  {
    title: 'Keep or remove',
    visual: <ReviewVisual />,
    body: 'When songs come due, tap Rotate and swipe through them. Swipe right to keep a song for another lap, or left to take it out of the playlist.',
  },
  {
    title: 'Restock',
    visual: <RestockVisual />,
    body: 'Running low? Tap Restock and swipe through songs picked from your listening, songs you removed a while back, and PlayLS picks. Swipe right to add one.',
  },
  {
    title: 'History',
    visual: <HistoryVisual />,
    body: "Every keep and removal is saved in the rotation's History tab, so you can add a song back if you change your mind.",
  },
];

// userId: remembers (per browser) that this account has seen the guide
export const HelpDialog = ({ open, onClose, userId }) => {
  const [step, setStep] = useState(0);
  useEffect(() => { if (open) setStep(0); }, [open]);
  useEffect(() => { if (open && userId != null) markHelpSeen(userId); }, [open, userId]);

  const last = step === STEPS.length; // the final page is the warning
  const current = STEPS[step];

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="xs" aria-labelledby="help-title"
      PaperProps={{ sx: { m: 2, width: 'calc(100% - 32px)' } }}>
      <Box display="flex" alignItems="center" justifyContent="space-between" px={2.5} pt={2}>
        <Typography id="help-title" variant="overline" color="text.secondary">
          How PlayLS works · {Math.min(step + 1, STEPS.length + 1)}/{STEPS.length + 1}
        </Typography>
        <IconButton aria-label="Close" onClick={onClose} edge="end" size="small"><Close fontSize="small" /></IconButton>
      </Box>

      <DialogContent sx={{ pt: 1, minHeight: 300 }}>
        {last ? (
          <Box>
            <Typography variant="h6" gutterBottom>One thing to avoid</Typography>
            <Alert severity="warning" sx={{ mb: 2 }}>
              Don't edit a playlist in Spotify while you're using it in PlayLS. Changes made in both places
              at once can get mixed up.
            </Alert>
            <Typography color="text.secondary">
              Make your changes in Spotify first, then come back: PlayLS picks them up. You can reopen this
              guide anytime from the <b>?</b> at the top.
            </Typography>
          </Box>
        ) : (
          <Box>
            <Box mb={2}>{current.visual}</Box>
            <Typography variant="h6" gutterBottom>{current.title}</Typography>
            <Typography color="text.secondary">{current.body}</Typography>
          </Box>
        )}
      </DialogContent>

      <DialogActions sx={{ px: 2.5, pb: 2, justifyContent: 'space-between' }}>
        <Box display="flex" gap={0.75} aria-hidden>
          {Array.from({ length: STEPS.length + 1 }, (_, i) => (
            <Box key={i} sx={{
              width: i === step ? 18 : 8, height: 8, borderRadius: 4, transition: 'width 150ms',
              bgcolor: i === step ? 'primary.main' : 'placeholder.main',
            }} />
          ))}
        </Box>
        <Box display="flex" gap={1}>
          {step > 0 && <Button color="inherit" onClick={() => setStep(step - 1)}>Back</Button>}
          {last
            ? <Button variant="contained" onClick={onClose}>Got it</Button>
            : <Button variant="contained" onClick={() => setStep(step + 1)}>Next</Button>}
        </Box>
      </DialogActions>
    </Dialog>
  );
};
