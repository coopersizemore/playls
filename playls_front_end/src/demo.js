// Demo mode: the whole app served again under /demo with a sample account and no Spotify
// connection (back-end/rest_api/services/demo). Fixed at page load; moving between /demo and
// the real app is a full page load.
export const DEMO_BASENAME = '/demo';
export const IS_DEMO = typeof window !== 'undefined' && /^\/demo(\/|$)/.test(window.location.pathname);
// Sent on every API request from the demo; the backend then reads the demo session cookie
export const DEMO_HEADER = 'X-PlayLS-Demo';
