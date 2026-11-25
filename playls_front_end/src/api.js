import axios from 'axios';
import { DEMO_HEADER, IS_DEMO } from './demo';

// The API is served from the same origin under /api (Vercel services, `vercel dev`,
// or the CRA dev-server proxy in package.json).
export const API_BASE = '/api';

// Auth is an httpOnly session cookie the browser sends automatically. The backend
// rejects state-changing requests without this header (CSRF protection).
const CSRF_HEADER = { 'X-Requested-With': 'XMLHttpRequest', ...(IS_DEMO ? { [DEMO_HEADER]: '1' } : {}) };
axios.defaults.headers.common['X-Requested-With'] = CSRF_HEADER['X-Requested-With'];
// Demo pages use the demo session (src/demo.js)
if (IS_DEMO) axios.defaults.headers.common[DEMO_HEADER] = '1';

// How long the app has been in front of the user. The backend only reuses a recent sync of a
// rotation if it happened after this point, so coming back from editing a playlist in Spotify
// always re-checks it.
let shownAt = Date.now();
if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') shownAt = Date.now();
  });
  window.addEventListener('pageshow', () => { shownAt = Date.now(); });
}
axios.interceptors.request.use((config) => {
  config.headers['X-Visible-For'] = String(Math.max(0, Date.now() - shownAt));
  return config;
});

const data = (promise) => promise.then((r) => r.data);

// Optional usage telemetry (src/telemetry.js) rides along with decision requests
const withTelemetry = (body, telemetry) => (telemetry ? { ...body, telemetry } : body);

// The daily review limit resets at the user's local midnight
const tz = () => ({ tz_offset: new Date().getTimezoneOffset() });

export const api = {
  rotations: ({ sync = true } = {}) =>
    data(axios.get(`${API_BASE}/user/me/rotations`, { params: { sync, ...tz() } })),
  rotation: (id, { sync = true } = {}) =>
    data(axios.get(`${API_BASE}/rotation/${id}`, { params: { sync, ...tz() } })),
  createRotation: (body) => data(axios.post(`${API_BASE}/rotation/`, body)),
  updateRotation: (id, body) => data(axios.put(`${API_BASE}/rotation/${id}`, body)),
  deleteRotation: (id) => data(axios.delete(`${API_BASE}/rotation/${id}`)),
  // Today's batch: { tracks, due_count, daily_limit, reviewed_today, remaining_after_batch, limit_reached }
  // all: every song in the rotation (soonest due first), ignoring the daily limit
  queue: (id, { more = false, all = false } = {}) =>
    data(axios.get(`${API_BASE}/rotation/${id}/queue`, { params: { more, all, ...tz() } })),
  resetDue: (id) => data(axios.post(`${API_BASE}/rotation/${id}/reset-due`)),
  // Re-reads the whole playlist, then lists songs Spotify reports as unavailable
  unplayable: (id) => data(axios.get(`${API_BASE}/rotation/${id}/unplayable`)),
  removeUnplayable: (id) => data(axios.post(`${API_BASE}/rotation/${id}/remove-unplayable`)),
  tracks: (id) => data(axios.get(`${API_BASE}/rotation/${id}/tracks`)),
  review: (id, trackId, action, telemetry) =>
    data(axios.post(`${API_BASE}/rotation/${id}/review`, withTelemetry({ track_id: trackId, action }, telemetry))),
  flush: (id) => data(axios.post(`${API_BASE}/rotation/${id}/flush`)),
  // Newest first. filter: all | removed | kept | skipped | rotated | reviews (the user's own decisions)
  history: (id, { filter = 'all', limit = 50, offset = 0 } = {}) =>
    data(axios.get(`${API_BASE}/rotation/${id}/history`, { params: { filter, limit, offset } })),
  // One page of history plus how many events match in total: { events, total }
  historyPage: (id, { filter = 'all', limit = 25, offset = 0 } = {}) =>
    axios.get(`${API_BASE}/rotation/${id}/history`, { params: { filter, limit, offset } })
      .then((r) => ({ events: r.data, total: Number(r.headers['x-total-count']) || r.data.length })),
  // Daily listening for a rotation (newest day first): { since, days: [{ date, plays_here, plays_elsewhere, songs }] }
  listeningDigest: (id, { days = 30 } = {}) =>
    data(axios.get(`${API_BASE}/rotation/${id}/listening`, { params: { days, ...tz() } })),
  playlists: () => data(axios.get(`${API_BASE}/spotify/playlists`)),
  // Listening history: save the latest plays (throttled on the server), its status, an export import
  captureListening: () => data(axios.post(`${API_BASE}/user/me/listening/capture`)),
  listeningStatus: () => data(axios.get(`${API_BASE}/user/me/listening`)),
  importListening: (rows) => data(axios.post(`${API_BASE}/user/me/listening/import`, { rows })),
  settings: () => data(axios.get(`${API_BASE}/user/me/settings`)),
  updateSettings: (body) => data(axios.put(`${API_BASE}/user/me/settings`, body)),
  // Restock (source: bring_back | picks | suggested)
  restockDeck: (id, source, { refresh = false } = {}) =>
    data(axios.get(`${API_BASE}/rotation/${id}/restock/deck/${source}`, { params: { refresh, ...tz() } })),
  restockSearch: (id, q, offset = 0) =>
    data(axios.get(`${API_BASE}/rotation/${id}/restock/search`, { params: { q, offset } })),
  restockAdd: (id, trackId, source, telemetry) =>
    data(axios.post(`${API_BASE}/rotation/${id}/restock/add`, withTelemetry({ track_id: trackId, source }, telemetry))),
  restockSkip: (id, trackId, source, telemetry) =>
    data(axios.post(`${API_BASE}/rotation/${id}/restock/skip`, withTelemetry({ track_id: trackId, source }, telemetry))),
  // Undo the latest Add (taken back out of the playlist) or Not now on a song: { undone: 'add' | 'skip' }
  restockUndo: (id, trackId, source, telemetry) =>
    data(axios.post(`${API_BASE}/rotation/${id}/restock/undo`, withTelemetry({ track_id: trackId, source }, telemetry))),
  // "Stop suggesting" a song in every restock deck (undo: unblockSong)
  restockBlock: (id, trackId, source, telemetry) =>
    data(axios.post(`${API_BASE}/rotation/${id}/restock/block`, withTelemetry({ track_id: trackId, source }, telemetry))),
  blockedSongs: () => data(axios.get(`${API_BASE}/user/me/blocked-songs`)),
  unblockSong: (trackId) => data(axios.delete(`${API_BASE}/user/me/blocked-songs/${encodeURIComponent(trackId)}`)),
  // Admin: curating PlayLS picks
  picks: () => data(axios.get(`${API_BASE}/admin/picks`)),
  createPick: (body) => data(axios.post(`${API_BASE}/admin/picks`, body)),
  updatePick: (pickId, body) => data(axios.put(`${API_BASE}/admin/picks/${pickId}`, body)),
  deletePick: (pickId) => data(axios.delete(`${API_BASE}/admin/picks/${pickId}`)),
  // Admin: monitoring dashboard (days: 7 | 30 | 90 | 180; kind: all | manual | auto)
  adminStats: ({ days = 30, kind = 'all' } = {}) => data(axios.get(`${API_BASE}/admin/stats`, { params: { days, kind } })),
  searchSpotify: (q, offset = 0) =>
    data(axios.get(`${API_BASE}/spotify/search`, { params: { q, offset, type: 'track' } })),
  deleteAccount: () => data(axios.delete(`${API_BASE}/user/me`)),
  // Demo mode: { expires_at, clock_offset_hours }
  demoStart: () => data(axios.post(`${API_BASE}/demo/start`)),
  demoSkipAhead: () => data(axios.post(`${API_BASE}/demo/skip-ahead`)),
  demoEnd: () => data(axios.post(`${API_BASE}/demo/end`)),
};

// Fire-and-forget flush that survives the page closing (pagehide/visibilitychange).
// sendBeacon can't set the CSRF header, so this uses fetch with keepalive instead.
export const flushOnExit = (rotationId) => {
  try {
    fetch(`${API_BASE}/rotation/${rotationId}/flush`, {
      method: 'POST',
      keepalive: true,
      credentials: 'same-origin',
      headers: CSRF_HEADER,
    }).catch(() => {});
  } catch (e) {
    // Older browsers without keepalive: the next sync flushes pending removals anyway
  }
};

// Generic, user-facing message for a failed request
export const errorMessage = (error, fallback = 'Something went wrong. Please try again.') => {
  const status = error?.response?.status;
  const detail = error?.response?.data?.detail;
  if (status === 429) {
    // The backend already waited out short pauses; this is a quota error or a long one
    if (typeof detail === 'string' && detail.includes('quota')) return detail;
    const wait = Number(error?.response?.headers?.['retry-after']);
    return wait > 0 && wait <= 120
      ? `Spotify is rate limiting requests. Try again in ${wait} seconds.`
      : 'Spotify is rate limiting requests. Try again in a minute.';
  }
  // 503: the demo is full or unavailable (a deliberate, user-facing message)
  if (status === 503 && typeof detail === 'string') return detail;
  return typeof detail === 'string' && status && status < 500 ? detail : fallback;
};
