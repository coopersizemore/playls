import axios from 'axios';

// The API is served from the same origin under /api (Vercel services, `vercel dev`,
// or the CRA dev-server proxy in package.json).
export const API_BASE = '/api';

// Auth is an httpOnly session cookie the browser sends automatically. The backend
// rejects state-changing requests without this header (CSRF protection).
const CSRF_HEADER = { 'X-Requested-With': 'XMLHttpRequest' };
axios.defaults.headers.common['X-Requested-With'] = CSRF_HEADER['X-Requested-With'];

const data = (promise) => promise.then((r) => r.data);

// The daily review limit resets at the user's local midnight
const tz = () => ({ tz_offset: new Date().getTimezoneOffset() });

export const api = {
  rotations: () => data(axios.get(`${API_BASE}/user/me/rotations`, { params: tz() })),
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
  review: (id, trackId, action) =>
    data(axios.post(`${API_BASE}/rotation/${id}/review`, { track_id: trackId, action })),
  flush: (id) => data(axios.post(`${API_BASE}/rotation/${id}/flush`)),
  history: (id) => data(axios.get(`${API_BASE}/rotation/${id}/history`)),
  playlists: () => data(axios.get(`${API_BASE}/spotify/playlists`)),
  settings: () => data(axios.get(`${API_BASE}/user/me/settings`)),
  updateSettings: (body) => data(axios.put(`${API_BASE}/user/me/settings`, body)),
  // Restock (source: bring_back | picks | suggested)
  restockDeck: (id, source, { refresh = false } = {}) =>
    data(axios.get(`${API_BASE}/rotation/${id}/restock/deck/${source}`, { params: { refresh, ...tz() } })),
  restockSearch: (id, q, offset = 0) =>
    data(axios.get(`${API_BASE}/rotation/${id}/restock/search`, { params: { q, offset } })),
  restockAdd: (id, trackId, source) =>
    data(axios.post(`${API_BASE}/rotation/${id}/restock/add`, { track_id: trackId, source })),
  restockSkip: (id, trackId, source) =>
    data(axios.post(`${API_BASE}/rotation/${id}/restock/skip`, { track_id: trackId, source })),
  // "Stop suggesting" a song in every restock deck (undo: unblockSong)
  restockBlock: (id, trackId, source) =>
    data(axios.post(`${API_BASE}/rotation/${id}/restock/block`, { track_id: trackId, source })),
  blockedSongs: () => data(axios.get(`${API_BASE}/user/me/blocked-songs`)),
  unblockSong: (trackId) => data(axios.delete(`${API_BASE}/user/me/blocked-songs/${encodeURIComponent(trackId)}`)),
  // Admin: curating PlayLS picks
  picks: () => data(axios.get(`${API_BASE}/admin/picks`)),
  createPick: (body) => data(axios.post(`${API_BASE}/admin/picks`, body)),
  deletePick: (pickId) => data(axios.delete(`${API_BASE}/admin/picks/${pickId}`)),
  searchSpotify: (q, offset = 0) =>
    data(axios.get(`${API_BASE}/spotify/search`, { params: { q, offset, type: 'track' } })),
  deleteAccount: () => data(axios.delete(`${API_BASE}/user/me`)),
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
  if (status === 429) return 'Spotify is rate limiting requests. Try again in a minute.';
  const detail = error?.response?.data?.detail;
  return typeof detail === 'string' && status && status < 500 ? detail : fallback;
};
