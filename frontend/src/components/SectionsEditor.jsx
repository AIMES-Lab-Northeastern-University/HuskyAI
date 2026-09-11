/**
 * Authoring for the shared artifact's fixed sections.
 *
 * One list per challenge, applied to every session by the API. That is not a
 * simplification: session-to-session carry-forward copies the previous
 * session's content by matching section key, so a section that existed in
 * session 1 but not session 2 would silently start empty with no signal that
 * anything was lost.
 *
 * `key` is deliberately editable and shown, not generated behind the scenes:
 * it is what the edit lock, the websocket payloads and the read/write event log
 * are all addressed by, so an instructor renaming a key needs to see that they
 * are doing something consequential.
 */

const KEY_RE = /^[A-Za-z0-9][A-Za-z0-9_-]*$/

const input = {
  fontSize: '12px',
  padding: '6px 8px',
  border: '1px solid #E7E0D8',
  borderRadius: '8px',
  outline: 'none',
  width: '100%',
  fontFamily: 'inherit',
}

const btn = {
  fontSize: '11px',
  fontWeight: 600,
  padding: '5px 10px',
  borderRadius: '8px',
  border: '1px solid #E7E0D8',
  background: '#fff',
  cursor: 'pointer',
}

export const MAX_SECTIONS = 12

/** Client-side echo of the server's rules, so an author is told before saving. */
export function sectionsProblem(sections) {
  const rows = sections || []
  if (rows.length > MAX_SECTIONS) return `At most ${MAX_SECTIONS} sections`
  const seen = new Set()
  for (const s of rows) {
    const key = (s.key || '').trim()
    if (!key) return 'Every section needs a key'
    if (!KEY_RE.test(key)) {
      return `Key "${key}" must start with a letter or number and use only letters, numbers, - or _`
    }
    if (seen.has(key)) return `Duplicate key "${key}" — keys must be unique`
    seen.add(key)
    if (!(s.title || '').trim()) return `Section "${key}" needs a title`
  }
  return ''
}

export default function SectionsEditor({ sections, onChange, disabled }) {
  const rows = sections || []

  const update = (i, field, value) => {
    const next = rows.map((r, idx) => (idx === i ? { ...r, [field]: value } : r))
    onChange(next)
  }
  const add = () => onChange([...rows, { key: '', title: '', prompt: '' }])
  const remove = (i) => onChange(rows.filter((_, idx) => idx !== i))

  const problem = sectionsProblem(rows)

  return (
    <div style={{ display: 'grid', gap: '8px' }}>
      <div style={{ fontSize: '11px', color: '#9A948E' }}>
        Shared artifact sections (optional). Teams edit these together, one
        person per section at a time. Leave empty for no artifact.
      </div>

      {rows.length === 0 && (
        <div style={{ fontSize: '11px', color: '#9A948E', fontStyle: 'italic' }}>
          No sections — this challenge has no shared artifact.
        </div>
      )}

      {rows.map((s, i) => (
        <div
          key={i}
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(90px, 1fr) minmax(120px, 1.4fr) minmax(140px, 2fr) auto',
            gap: '6px',
            alignItems: 'start',
          }}
        >
          <input
            type="text"
            placeholder="key"
            value={s.key || ''}
            disabled={disabled}
            onChange={(e) => update(i, 'key', e.target.value)}
            style={input}
          />
          <input
            type="text"
            placeholder="Title"
            value={s.title || ''}
            disabled={disabled}
            onChange={(e) => update(i, 'title', e.target.value)}
            style={input}
          />
          <input
            type="text"
            placeholder="Prompt shown to the team (optional)"
            value={s.prompt || ''}
            disabled={disabled}
            onChange={(e) => update(i, 'prompt', e.target.value)}
            style={input}
          />
          <button
            type="button"
            onClick={() => remove(i)}
            disabled={disabled}
            style={{ ...btn, color: '#C8102E' }}
            aria-label={`Remove section ${s.key || i + 1}`}
          >
            Remove
          </button>
        </div>
      ))}

      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <button
          type="button"
          onClick={add}
          disabled={disabled || rows.length >= MAX_SECTIONS}
          style={btn}
        >
          Add section
        </button>
        {problem && (
          <span style={{ fontSize: '11px', color: '#C8102E' }}>{problem}</span>
        )}
      </div>
    </div>
  )
}
