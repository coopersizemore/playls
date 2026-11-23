import React, { useRef, useState } from 'react';
import { Box, Typography } from '@mui/material';

export const EXIT_MS = 280;
const THRESHOLD = 90; // px of horizontal drag that counts as a swipe
const STAMP_AT = 30; // px before the KEEP / REMOVE stamp starts to show

const Stamp = ({ label, color, side, opacity }) => (
  <Typography sx={{
    position: 'absolute', top: 24, [side]: 20, zIndex: 2, px: 1.5, py: 0.5, borderRadius: 1.5,
    border: '3px solid', borderColor: color, color, fontWeight: 700, fontSize: '1.4rem', letterSpacing: '0.08em',
    bgcolor: 'rgba(255,255,255,0.85)', transform: `rotate(${side === 'left' ? -14 : 14}deg)`,
    opacity, pointerEvents: 'none', fontFamily: '"Roboto", sans-serif',
  }}>
    {label}
  </Typography>
);

// A draggable card: swipe right (keep) or left (remove). `exit` ('left' | 'right' | 'up')
// animates it off screen — set by a swipe or by a button/keyboard action. Vertical page
// scrolling still works (touch-action: pan-y).
const SwipeCard = ({ children, onSwipe, exit = null, disabled = false }) => {
  const [dx, setDx] = useState(0);
  const [dragging, setDragging] = useState(false);
  const start = useRef(null);

  const onPointerDown = (e) => {
    if (disabled || exit || (e.pointerType === 'mouse' && e.button !== 0)) return;
    start.current = { x: e.clientX, id: e.pointerId };
    setDragging(true);
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e) => {
    if (start.current && e.pointerId === start.current.id) setDx(e.clientX - start.current.x);
  };
  const end = () => {
    if (!start.current) return;
    start.current = null;
    setDragging(false);
    if (Math.abs(dx) >= THRESHOLD) {
      onSwipe(dx > 0 ? 'right' : 'left');
    } else {
      setDx(0); // snap back
    }
  };

  let transform = `translateX(${dx}px) rotate(${dx / 18}deg)`;
  let opacity = 1;
  if (exit === 'right') { transform = 'translateX(120vw) rotate(24deg)'; opacity = 0; }
  else if (exit === 'left') { transform = 'translateX(-120vw) rotate(-24deg)'; opacity = 0; }
  else if (exit === 'up') { transform = 'translateY(-110vh) scale(0.9)'; opacity = 0; }
  else if (!dragging && dx !== 0 && Math.abs(dx) < THRESHOLD) transform = 'translateX(0) rotate(0)';

  const keepOpacity = exit === 'right' ? 1 : Math.min(1, Math.max(0, (dx - STAMP_AT) / (THRESHOLD - STAMP_AT)));
  const removeOpacity = exit === 'left' ? 1 : Math.min(1, Math.max(0, (-dx - STAMP_AT) / (THRESHOLD - STAMP_AT)));

  return (
    <Box
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={end}
      onPointerCancel={end}
      sx={{
        position: 'relative', touchAction: 'pan-y', userSelect: 'none', cursor: disabled ? 'default' : 'grab',
        '&:active': { cursor: disabled ? 'default' : 'grabbing' },
        transform, opacity,
        transition: dragging ? 'none' : `transform ${EXIT_MS}ms ease-out, opacity ${EXIT_MS}ms ease-out`,
        willChange: 'transform',
      }}
    >
      <Stamp label="KEEP" color="#2E7D32" side="left" opacity={keepOpacity} />
      <Stamp label="REMOVE" color="#C62828" side="right" opacity={removeOpacity} />
      {children}
    </Box>
  );
};

export default SwipeCard;
