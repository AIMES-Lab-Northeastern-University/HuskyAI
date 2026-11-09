/**
 * Authoring for the shared artifact's fixed sections.
 *
 * One list per challenge, applied to every session by the API. That is not a
 * simplification: a section that existed in session 1 but not session 2 would
 * silently start empty with no signal that anything was lost.
 *
 * `key` is deliberately editable and shown, not generated behind the scenes:
 * it is what the artifact websocket payloads and every study_events row are
 * addressed by (`payload.section_key` is the unit of read and write
 * attribution), so an instructor renaming a key needs to see that they are
 * doing something consequential — sections already written into a live
 * session's artifact keep the old key.
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
    const t = s.target_words
    if (t !== '' && t != null && !(Number.isInteger(Number(t)) && Number(t) >= 10 && Number(t) <= 5000)) {
      return `Section "${key}": target length must be a whole number of words between 10 and 5000`
    }
  }
  return ''
}

export default function SectionsEditor({ sections, onChange, disabled }) {
  const rows = sections || []

  const update = (i, field, value) => {
    const next = rows.map((r, idx) => (idx === i ? { ...r, [field]: value } : r))
    onChange(next)
  }
  const add = () => onChange([...rows, { key: '', title: '', prompt: '', target_words: '' }])
  const remove = (i) => onChange(rows.filter((_, idx) => idx !== i))

  const problem = sectionsProblem(rows)

  return (
    <div style={{ display: 'grid', gap: '8px' }}>
      <div style={{ fontSize: '11px', color: '#9A948E' }}>
        Sections of the team's final document (optional) — this is what each
        team submits. Tell students what goes in each section and roughly how
        long it should be: they see it while writing, and the final review flags
        sections that are empty or well short. Anyone on the team can edit any
        section. Leave empty for no shared document.
      </div>

      {rows.length === 0 && (
        <div style={{ fontSize: '11px', color: '#9A948E', fontStyle: 'italic' }}>
          No sections — this challenge has no shared artifact.
        </div>
      )}

      {rows.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(80px, 1fr) minmax(120px, 2fr) minmax(90px, 0.9fr) auto', gap: '6px', padding: '0 9px', fontSize: '10px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
          <span>Key</span><span>Title</span><span>Target words</span><span style={{ width: '62px' }} />
        </div>
      )}

      {rows.map((s, i) => (
        <div key={i} style={{ display: 'grid', gap: '6px', padding: '8px', border: '1px solid #F0EBE4', borderRadius: '9px', background: '#fff' }}>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'minmax(80px, 1fr) minmax(120px, 2fr) minmax(90px, 0.9fr) auto',
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
              type="number"
              min={10}
              max={5000}
              placeholder="~words"
              title="Roughly how many words a finished section should have"
              value={s.target_words ?? ''}
              disabled={disabled}
              onChange={(e) => update(i, 'target_words', e.target.value)}
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
          <textarea
            rows={2}
            placeholder="What should this section contain? e.g. State your recommendation and the two strongest pieces of evidence."
            value={s.prompt || ''}
            disabled={disabled}
            onChange={(e) => update(i, 'prompt', e.target.value)}
            style={{ ...input, resize: 'vertical' }}
          />
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
