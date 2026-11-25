import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  Alert,
  Avatar,
  Badge,
  Box,
  ButtonBase,
  Chip,
  Divider,
  IconButton,
  InputAdornment,
  ListItemIcon,
  Menu,
  MenuItem,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material';
import {
  AddCircleOutline,
  ArrowDownward,
  ArrowUpward,
  AutoMode,
  Autorenew,
  Delete,
  Edit,
  MusicNote,
  PlaylistRemove,
  RestartAlt,
  Search,
  Settings as SettingsIcon,
  Star,
  SyncProblem,
  ViewList,
} from '@mui/icons-material';
import { IS_DEMO } from '../demo';
import { api, errorMessage } from '../api';
import { readStored, writeStored } from '../storage';
import { GREEN, GREEN_DARK, GREEN_LIGHT, ON_GREEN } from '../theme';
import { HistoryList } from './History';
import { Layout, PlaylistCover, formatDuration, parseUtc, relativeDays } from './Layout';
import {
  DeleteRotationDialog,
  EditRotationDialog,
  RemoveUnplayableDialog,
  ResetDueDialog,
  formatInterval,
} from './RotationDialogs';
import { RotationPageSkeleton, SongRowsSkeleton } from './Skeletons';
import { PlaysIcon, playsText, windowLabel } from './Listening';

// Spotify's mark, simplified (MUI has no brand icons)
const SpotifyMark = () => (
  <Box component="svg" viewBox="0 0 24 24" sx={{ width: 34, height: 34 }} aria-hidden>
    <circle cx="12" cy="12" r="12" fill="#191414" />
    <path d="M6.5 9.4c3.7-1.1 8-.8 11.2 1M7.2 12.4c3-.8 6.4-.5 9 .9M7.8 15.2c2.4-.6 5-.4 7 .7"
      stroke={GREEN} strokeWidth="1.6" strokeLinecap="round" fill="none" />
  </Box>
);

// The white (or green) action tiles from the wireframes
const Tile = ({ icon, label, onClick, href, green = false, badge = 0, disabled = false }) => (
  <Badge badgeContent={badge} color="error" max={999} overlap="rectangular"
    anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }} sx={{ width: '100%' }}>
    <ButtonBase
      onClick={onClick}
      disabled={disabled}
      {...(href ? { component: 'a', href, target: '_blank', rel: 'noopener noreferrer' } : {})}
      sx={{
        width: '100%', height: 72, px: 2.5, gap: 2, justifyContent: 'flex-start', borderRadius: 2,
        bgcolor: green ? GREEN : 'background.paper', color: green ? ON_GREEN : 'text.primary',
        boxShadow: '0 2px 6px rgba(0,0,0,0.25)',
        opacity: disabled ? 0.5 : 1, transition: 'transform 120ms', '&:active': { transform: 'scale(0.98)' },
      }}
    >
      {icon}
      <Typography sx={{ fontFamily: '"Roboto", sans-serif', fontSize: '1.15rem', fontWeight: 500 }}>{label}</Typography>
    </ButtonBase>
  </Badge>
);

const DueLabel = ({ track, auto }) => {
  if (track.status === 'pending_removal') return <Chip size="small" label="Removing" color="error" />;
  if (auto) {
    // Auto rotations: when the song is expected to rotate out
    if (track.protected) return <Typography variant="caption" sx={{ whiteSpace: 'nowrap', ml: 1 }}>Kept</Typography>;
    if (!track.due_at) return null;
    return (
      <Typography variant="caption" sx={{ whiteSpace: 'nowrap', ml: 1 }}>
        Leaves {relativeDays(track.due_at)}
      </Typography>
    );
  }
  if (track.listening?.held) {
    return <Typography variant="caption" sx={{ whiteSpace: 'nowrap', ml: 1 }}>Held</Typography>;
  }
  if (!track.due_at) return null;
  const due = parseUtc(track.due_at) <= new Date();
  return (
    <Typography variant="caption" sx={{ fontWeight: due ? 700 : 400, whiteSpace: 'nowrap', ml: 1 }}>
      {due ? 'Due' : relativeDays(track.due_at)}
    </Typography>
  );
};

// Current songs sort options. Ties (and unknown dates, which go last) fall back to the title.
const SORTS = {
  due: { label: 'Due date', autoLabel: 'Leaving date', key: (t) => t.due_at, dir: 'asc' },
  added: { label: 'Date added', key: (t) => t.added_at, dir: 'desc' },
  reviewed: { label: 'Last reviewed', key: (t) => t.last_reviewed_at, dir: 'desc' },
  title: { label: 'Title', key: null, dir: 'asc' },
  kept: { label: 'Times kept', key: (t) => t.times_kept, dir: 'desc' },
  plays: { label: 'Plays', key: (t) => t.listening?.plays || null, dir: 'desc' },
};
const SORT_KEY = 'playls.songSort';

const byTitle = (a, b) =>
  a.title.localeCompare(b.title, undefined, { sensitivity: 'base' }) || a.track_id.localeCompare(b.track_id);

const sortSongs = (tracks, by, dir) => {
  const sign = dir === 'asc' ? 1 : -1;
  const key = SORTS[by].key;
  return [...tracks].sort((a, b) => {
    if (!key) return sign * byTitle(a, b);
    const va = key(a);
    const vb = key(b);
    if (va == null || vb == null) {
      if (va != null) return -1; // unknown last, in either direction
      if (vb != null) return 1;
      return byTitle(a, b);
    }
    if (va !== vb) return sign * (va < vb ? -1 : 1); // ISO timestamps compare as strings
    return byTitle(a, b);
  });
};

const loadSort = () => {
  try {
    const saved = JSON.parse(readStored(SORT_KEY));
    if (saved && SORTS[saved.by] && ['asc', 'desc'].includes(saved.dir)) return saved;
  } catch (e) {
    // bad JSON: use the default
  }
  return { by: 'due', dir: 'asc' };
};

const mixHex = (from, to, t) => {
  const channel = (hex, i) => parseInt(hex.slice(1 + 2 * i, 3 + 2 * i), 16);
  return '#' + [0, 1, 2].map((i) =>
    Math.round(channel(from, i) + (channel(to, i) - channel(from, i)) * t).toString(16).padStart(2, '0')).join('');
};

// Row shades by rank among the rotation's due dates, not by the dates themselves: the next
// song due is lightest and the furthest out darkest. Songs already due share the lightest
// shade; songs with no due date (or kept, or being removed) stay plain green.
const dueShades = (tracks, auto) => {
  const now = new Date();
  const keyOf = (t) => {
    if (!t.due_at || t.status === 'pending_removal' || (auto && t.protected)) return null;
    const at = parseUtc(t.due_at);
    return at <= now ? 0 : at.getTime();
  };
  const keys = [...new Set((tracks || []).map(keyOf).filter((k) => k != null))].sort((a, b) => a - b);
  const rank = new Map(keys.map((k, i) => [k, keys.length > 1 ? i / (keys.length - 1) : 0.5]));
  const shades = new Map();
  for (const t of tracks || []) {
    const k = keyOf(t);
    if (k != null) shades.set(t.track_id, mixHex(GREEN_LIGHT, GREEN_DARK, rank.get(k)));
  }
  return shades;
};

const SongRow = ({ track, auto, shade }) => (
  <Box sx={{
    display: 'flex', alignItems: 'center', gap: 2, px: 1.5, py: 1.25, borderRadius: 999,
    bgcolor: track.status === 'pending_removal' ? 'action.disabledBackground' : shade || GREEN,
    color: track.status === 'pending_removal' ? 'text.primary' : ON_GREEN,
  }}>
    <Avatar variant="rounded" src={track.image_url || undefined}
      sx={{ width: 52, height: 52, borderRadius: 2.5, bgcolor: 'placeholder.main', color: 'text.secondary' }}>
      <MusicNote />
    </Avatar>
    <Box sx={{ minWidth: 0, flexGrow: 1 }}>
      <Typography noWrap sx={{ fontWeight: 500 }}>
        {track.keep_multiplier > 1 && <Star sx={{ fontSize: 14, mr: 0.5, verticalAlign: '-2px' }} />}
        {track.title}
      </Typography>
      <Typography noWrap variant="body2" sx={{ opacity: 0.75 }}>
        {track.artists}
        {track.is_playable === false && ' · unavailable'}
      </Typography>
    </Box>
    <Box pr={1.5} display="flex" flexDirection="column" alignItems="flex-end" flexShrink={0}>
      <DueLabel track={track} auto={auto} />
      <Typography variant="caption" sx={{ opacity: 0.75, whiteSpace: 'nowrap' }}>
        Kept {track.times_kept ?? 0}×
      </Typography>
      {playsText(track.listening) && (
        <Typography variant="caption" sx={{ opacity: 0.75, whiteSpace: 'nowrap', fontWeight: track.listening.heavy ? 700 : 400 }}>
          <PlaysIcon sx={{ fontSize: 12, mr: 0.4, verticalAlign: '-1px' }} />{playsText(track.listening)}
        </Typography>
      )}
    </Box>
  </Box>
);

// A rotation, opened like a Spotify playlist: cover, stats, actions, songs and history
const RotationPage = () => {
  const { rotationId } = useParams();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') === 'history' ? 1 : 0;
  const [rotation, setRotation] = useState(null);
  const [tracks, setTracks] = useState(null);
  const [lastReviewed, setLastReviewed] = useState(undefined);
  const [filter, setFilter] = useState('');
  const [sort, setSort] = useState(loadSort);
  const [error, setError] = useState('');
  const [menuAnchor, setMenuAnchor] = useState(null);
  const [dialog, setDialog] = useState(null); // 'edit' | 'reset' | 'unplayable' | 'delete'

  const load = useCallback(async () => {
    setError('');
    try {
      const summary = await api.rotation(rotationId); // syncs with Spotify first
      setRotation(summary);
      const [songs, history] = await Promise.all([
        api.tracks(rotationId), api.history(rotationId, { filter: 'reviews', limit: 1 }),
      ]);
      setTracks(songs);
      setLastReviewed(history[0]?.created_at || null);
    } catch (e) {
      if (e?.response?.status === 404) navigate('/', { replace: true });
      setError(errorMessage(e, 'Failed to load this rotation.'));
      setTracks((t) => t || []);
    }
  }, [rotationId, navigate]);

  useEffect(() => { load(); }, [load]);

  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const matching = q
      ? (tracks || []).filter((t) => `${t.title} ${t.artists || ''} ${t.album || ''}`.toLowerCase().includes(q))
      : tracks || [];
    return sortSongs(matching, sort.by, sort.dir);
  }, [tracks, filter, sort]);
  const isAutoKind = rotation?.kind === 'auto';
  const shades = useMemo(() => dueShades(tracks, isAutoKind), [tracks, isAutoKind]);

  const changeSort = (next) => {
    setSort(next);
    writeStored(SORT_KEY, JSON.stringify(next));
  };

  const closeDialog = (changed) => { setDialog(null); if (changed) load(); };
  const menuItem = (icon, label, onClick, props = {}) => (
    <MenuItem onClick={() => { setMenuAnchor(null); onClick(); }} {...props}>
      <ListItemIcon>{icon}</ListItemIcon>{label}
    </MenuItem>
  );

  if (!rotation) {
    return (
      <Layout maxWidth="sm" back="/">
        {error ? <Alert severity="error">{error}</Alert> : <RotationPageSkeleton />}
      </Layout>
    );
  }

  const totalMs = (tracks || []).reduce((sum, t) => sum + (t.duration_ms || 0), 0);
  const due = rotation.due_count;
  const isAuto = rotation.kind === 'auto';

  return (
    <Layout maxWidth="sm" back="/">
      <Box display="flex" flexDirection="column" alignItems="center">
        <PlaylistCover rotation={rotation} size={220} radius={3} shadow />
        <Typography variant="h5" component="h1" textAlign="center" mt={3} sx={{ overflowWrap: 'anywhere' }}>
          {rotation.name}
        </Typography>
        {isAuto && (
          <Chip icon={<AutoMode />} size="small" sx={{ mt: 1 }}
            label={`Auto-restocking · ${rotation.target_size} songs`} />
        )}
        {rotation.is_liked && (
          <Chip size="small" sx={{ mt: 1 }} label="Liked Songs · removing a song unlikes it" />
        )}
      </Box>

      <Box display="flex" justifyContent="space-between" gap={1} mt={2.5} mb={3} px={0.5} flexWrap="wrap">
        <Typography variant="body2">{rotation.active_count} songs</Typography>
        <Typography variant="body2">
          {lastReviewed === undefined ? '' : lastReviewed ? `Last reviewed ${relativeDays(lastReviewed)}` : 'Not reviewed yet'}
        </Typography>
        <Typography variant="body2">{tracks ? formatDuration(totalMs) : ''}</Typography>
      </Box>
      {rotation.listening?.plays_here > 0 && (
        <Typography variant="body2" color="text.secondary" textAlign="center" mt={-1.5} mb={3} px={0.5}>
          <PlaysIcon sx={{ fontSize: 15, mr: 0.5, verticalAlign: '-2px' }} />
          {rotation.listening.plays_here} play{rotation.listening.plays_here === 1 ? '' : 's'} from this playlist in{' '}
          {windowLabel(rotation.listening.window_days)}
          {rotation.listening.top_song && ` · most played: ${rotation.listening.top_song}`}
        </Typography>
      )}

      {!rotation.sync_ok && (
        <Alert severity="warning" icon={<SyncProblem />} sx={{ mb: 2 }}>
          Couldn't reach Spotify, so this may be out of date.
        </Alert>
      )}
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Box display="grid" gridTemplateColumns="1fr 1fr" gap={2.5} mb={1}>
        <Tile
          icon={<Avatar sx={{ bgcolor: 'placeholder.main', color: 'text.primary' }}><Autorenew /></Avatar>}
          label="Rotate"
          badge={isAuto ? 0 : rotation.ready_today}
          disabled={due === 0}
          onClick={() => navigate(`/rotation/${rotation.id}/review`)}
        />
        <Tile icon={<AddCircleOutline sx={{ fontSize: 34 }} />} label="Restock"
          onClick={() => navigate(`/rotation/${rotation.id}/restock`)} />
        {/* A demo playlist doesn't exist on Spotify */}
        {!IS_DEMO && (
          <Tile icon={<SpotifyMark />} label="Spotify" green
            href={rotation.is_liked
              ? 'https://open.spotify.com/collection/tracks'
              : `https://open.spotify.com/playlist/${encodeURIComponent(rotation.playlist_id)}`} />
        )}
        <Tile icon={<SettingsIcon sx={{ fontSize: 34 }} />} label="Settings" onClick={(e) => setMenuAnchor(e.currentTarget)} />
      </Box>
      <Typography variant="caption" color="text.secondary" display="block" textAlign="center" mb={2}>
        {isAuto
          ? `${due} song${due === 1 ? '' : 's'} leaving ${relativeDays(rotation.next_rotation_at)} · ` +
            `${rotation.rotate_percent}% every ${formatInterval(rotation.interval_hours)}` +
            (rotation.active_count < rotation.target_size
              ? ` · ${rotation.target_size - rotation.active_count} short of ${rotation.target_size}` : '')
          : due === 0
            ? (rotation.next_due_at ? `Next song due ${relativeDays(rotation.next_due_at)}` : 'Nothing due')
            : `${due} due · every ${formatInterval(rotation.interval_hours)}`}
      </Typography>

      <Menu anchorEl={menuAnchor} open={!!menuAnchor} onClose={() => setMenuAnchor(null)}>
        {menuItem(<Edit fontSize="small" />, 'Edit rotation', () => setDialog('edit'))}
        {menuItem(<ViewList fontSize="small" />, 'Review all songs',
          () => navigate(`/rotation/${rotation.id}/review?all=1`), { disabled: rotation.active_count === 0 })}
        {!isAuto && menuItem(<RestartAlt fontSize="small" />, 'Reset all songs to not due…', () => setDialog('reset'),
          { disabled: rotation.active_count === 0 })}
        {menuItem(<PlaylistRemove fontSize="small" />,
          rotation.is_liked ? 'Unlike unavailable songs…' : 'Remove unavailable songs…', () => setDialog('unplayable'),
          { disabled: rotation.active_count === 0 })}
        <Divider />
        {menuItem(<Delete fontSize="small" color="error" />, 'Delete rotation', () => setDialog('delete'),
          { sx: { color: 'error.main' } })}
      </Menu>

      <Box sx={{ bgcolor: 'surface.main', borderRadius: 4, p: { xs: 1.5, sm: 2.5 }, boxShadow: 'inset 0 0 0 1px rgba(127,127,127,0.12)' }}>
        <Tabs value={tab} onChange={(_, v) => setParams(v === 1 ? { tab: 'history' } : {}, { replace: true })}
          variant="fullWidth" sx={{ mb: 2 }}>
          <Tab label="Current songs" />
          <Tab label="History" />
        </Tabs>

        {tab === 0 ? (
          tracks === null ? (
            <SongRowsSkeleton />
          ) : (
            <>
              {tracks.length > 1 && (
                <Box display="flex" gap={1} mb={2} flexWrap="wrap">
                  {tracks.length > 8 && (
                    <TextField size="small" placeholder="Filter songs" value={filter}
                      onChange={(e) => setFilter(e.target.value)} sx={{ flex: '1 1 180px' }}
                      InputProps={{ startAdornment: <InputAdornment position="start"><Search /></InputAdornment> }} />
                  )}
                  <Box display="flex" gap={0.5} alignItems="center" sx={{ flex: '0 0 auto', ml: 'auto' }}>
                    <TextField select size="small" label="Sort by" value={sort.by} sx={{ minWidth: 160 }}
                      onChange={(e) => changeSort({ by: e.target.value, dir: SORTS[e.target.value].dir })}>
                      {Object.entries(SORTS).map(([value, s]) => (
                        <MenuItem key={value} value={value}>{isAuto && s.autoLabel ? s.autoLabel : s.label}</MenuItem>
                      ))}
                    </TextField>
                    <IconButton
                      aria-label={sort.dir === 'asc' ? 'Ascending (tap for descending)' : 'Descending (tap for ascending)'}
                      onClick={() => changeSort({ ...sort, dir: sort.dir === 'asc' ? 'desc' : 'asc' })}>
                      {sort.dir === 'asc' ? <ArrowUpward /> : <ArrowDownward />}
                    </IconButton>
                  </Box>
                </Box>
              )}
              {shown.length === 0 ? (
                <Typography color="text.secondary" textAlign="center" py={3}>
                  {tracks.length === 0 ? 'No songs yet. Add some in Spotify or with Restock.' : 'No songs match.'}
                </Typography>
              ) : (
                <Box display="flex" flexDirection="column" gap={1.5}>
                  {shown.map((t) => <SongRow key={t.track_id} track={t} auto={isAuto} shade={shades.get(t.track_id)} />)}
                </Box>
              )}
            </>
          )
        ) : (
          <HistoryList rotationId={rotation.id} onChanged={load} auto={isAuto} />
        )}
      </Box>

      <EditRotationDialog rotation={dialog === 'edit' ? rotation : null} onClose={() => closeDialog(false)}
        onSaved={() => closeDialog(true)} />
      <ResetDueDialog rotation={dialog === 'reset' ? rotation : null} onClose={() => closeDialog(false)}
        onDone={() => closeDialog(true)} />
      <RemoveUnplayableDialog rotation={dialog === 'unplayable' ? rotation : null} onClose={() => closeDialog(false)}
        onDone={() => closeDialog(true)} />
      <DeleteRotationDialog rotation={dialog === 'delete' ? rotation : null} onClose={() => closeDialog(false)}
        onDeleted={() => navigate('/', { replace: true })} />
    </Layout>
  );
};

export default RotationPage;
