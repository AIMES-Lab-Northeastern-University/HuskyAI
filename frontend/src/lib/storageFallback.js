/**
 * Study builds only (VITE_STUDY_MODE_ENABLED): HuskyAI embedded in the survey
 * is a cross-site iframe, and a browser that blocks third-party storage
 * (incognito, Brave, strict cookie settings) refuses it localStorage and
 * sessionStorage outright: every read throws, the sign-in cannot be kept and
 * the task hangs on "Opening your task…". In that case only, this swaps in an
 * in-memory store for the page's lifetime. The sign-in then lasts until the
 * frame reloads, and a reload starts again from the survey link, which signs
 * in afresh from its code.
 *
 * Never runs outside a frame, so the normal app is untouched. Imported first in
 * main.jsx, before any module reads storage.
 */

export function memoryStorage() {
  const m = new Map()
  return {
    get length() { return m.size },
    key(i) { return [...m.keys()][i] ?? null },
    getItem(k) { k = String(k); return m.has(k) ? m.get(k) : null },
    setItem(k, v) { m.set(String(k), String(v)) },
    removeItem(k) { m.delete(String(k)) },
    clear() { m.clear() },
  }
}

function usable(win, name) {
  try {
    const s = win[name]
    s.setItem('__husky_probe__', '1')
    s.removeItem('__husky_probe__')
    return true
  } catch {
    return false
  }
}

/** Returns the names of the stores it replaced (none unless all three hold:
 * study build, inside a frame, storage refused). */
export function installStorageFallback(win = typeof window === 'undefined' ? null : window,
                                       studyBuild = import.meta.env.VITE_STUDY_MODE_ENABLED === 'true') {
  if (!win || !studyBuild || win.parent === win) return []
  const swapped = []
  for (const name of ['localStorage', 'sessionStorage']) {
    if (usable(win, name)) continue
    try {
      Object.defineProperty(win, name, { value: memoryStorage(), configurable: true })
      swapped.push(name)
    } catch { /* cannot shadow it here: leave the page as it was */ }
  }
  return swapped
}

installStorageFallback()
