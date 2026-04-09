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

export function authHeaders() {
  const token = localStorage.getItem('token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}
