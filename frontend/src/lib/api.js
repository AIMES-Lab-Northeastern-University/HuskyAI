export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

/** Turn FastAPI `detail` (string | object | validation array) into a readable message. */
export function formatApiErrorDetail(detail) {
  if (detail == null || detail === '') return 'Something went wrong'
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (item == null) return null
      if (typeof item === 'string') return item
      if (typeof item === 'object' && item.msg != null) return String(item.msg)
      return null
    }).filter(Boolean)
    if (parts.length) return parts.join(' ')
  }
  if (typeof detail === 'object') {
    if (detail.msg != null) return String(detail.msg)
    if (detail.message != null) return String(detail.message)
  }
  try {
    return JSON.stringify(detail)
  } catch {
    return 'Something went wrong'
  }
}

/** Readable error text from a failed Response, whatever its body is. A proxy
 * error page or an empty 502 is not JSON, and reading it with res.json() used
 * to throw into a generic catch that hid the real status from the user. */
export async function readApiError(res, fallback = 'Something went wrong') {
  let text = ''
  try { text = await res.text() } catch { return fallback }
  if (text) {
    try {
      const body = JSON.parse(text)
      if (body && body.detail != null && body.detail !== '') return formatApiErrorDetail(body.detail)
    } catch { /* not JSON */ }
  }
  return res.status ? `${fallback} (${res.status})` : fallback
}

export function authHeaders() {
  const token = localStorage.getItem('token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// Everything cached about the signed-in person. Cleared together on every way
// out (sign-out button, expired token, a 4001 socket close): clearing only the
// token left the previous person's instructor/admin nav flags and role list
// behind for whoever signed in next on the same machine.
const SESSION_KEYS = ['token', 'user', 'is_instructor', 'debug_roles', 'research_ack']

export function clearSession() {
  for (const k of SESSION_KEYS) {
    try { localStorage.removeItem(k) } catch { /* storage blocked */ }
  }
}

/** Only same-app relative paths are followed after login, never another origin. */
export function safeNextPath(next) {
  if (typeof next !== 'string' || !next.startsWith('/') || next.startsWith('//')) return null
  if (next.startsWith('/login')) return null
  return next
}

export function loginUrlWithNext() {
  const here = window.location.pathname + window.location.search
  const next = safeNextPath(here)
  return next ? `/login?next=${encodeURIComponent(next)}` : '/login'
}

let redirectingToLogin = false

/** The token was rejected: sign out and send the person to log in, then back
 * to where they were. Idempotent, because a page usually has several requests
 * in flight and every one of them comes back 401. */
export function handleUnauthorized(go = (url) => window.location.assign(url)) {
  if (redirectingToLogin) return
  redirectingToLogin = true
  const target = loginUrlWithNext()
  clearSession()
  go(target)
}

function sentBearer(input, init) {
  const h = init?.headers ?? (typeof Request !== 'undefined' && input instanceof Request ? input.headers : null)
  if (!h) return false
  const v = typeof h.get === 'function' ? h.get('Authorization') : (h.Authorization ?? h.authorization)
  return typeof v === 'string' && v.startsWith('Bearer ')
}

function isApiRequest(input) {
  const url = typeof input === 'string' ? input : input?.url
  return typeof url === 'string' && url.startsWith(API_URL)
}

/** The shared fetch wrapper. Installed once at startup rather than threaded
 * through the ~90 call sites, so no page can forget it: before, an expired
 * token left each page showing its own "could not load" error with no way
 * back to the login screen. Only a request that SENT a token triggers it — a
 * wrong password on /auth/login is also a 401 and must stay on the form. */
export function installAuthExpiryHandler({ onUnauthorized = handleUnauthorized } = {}) {
  if (typeof window === 'undefined' || window.fetch.__huskyAuthWrapped) return
  const original = window.fetch.bind(window)
  const wrapped = async (input, init) => {
    const res = await original(input, init)
    if (res.status === 401 && isApiRequest(input) && sentBearer(input, init)) onUnauthorized()
    return res
  }
  wrapped.__huskyAuthWrapped = true
  window.fetch = wrapped
}
