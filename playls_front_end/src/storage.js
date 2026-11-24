// Per-browser conveniences in localStorage. Access can throw (private windows, blocked site
// data), so these never do: reads fall back, and writes that fail are simply not remembered.

// `blocked` is returned when storage can't be read at all (defaults to `fallback`)
export const readStored = (key, fallback = null, blocked = fallback) => {
  try {
    const value = window.localStorage.getItem(key);
    return value === null ? fallback : value;
  } catch (e) {
    return blocked;
  }
};

export const writeStored = (key, value) => {
  try {
    window.localStorage.setItem(key, value);
  } catch (e) {
    // not remembered; the app still works for this visit
  }
};
