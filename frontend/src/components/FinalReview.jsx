import { useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/**
 * The team's final review: the whole document exactly as the instructor will
 * receive it, a checklist of what still needs work, and who is ready to
 * submit. The session ends when everyone who took part is ready (server side),
 * or when a member submits without waiting.
 */

export function wordCount(text = '') {
  return text.trim() ? text.trim().split(/\s+/).length : 0
}

// "A: ...", "B: ..." or "Ana: ..." lines: the section was used as a chat.
function chatLines(text, names) {
  const firsts = new Set(names.map(n => (n || '').split(/\s+/)[0].toLowerCase()).filter(Boolean))
  return text.split('\n').filter(line => {
    const m = line.match(/^\s*([A-Za-z][\w'-]{0,14}):\s+\S/)
    if (!m) return false
    const label = m[1].toLowerCase()
    return label.length === 1 || firsts.has(label)
  }).length
}

/** What is still wrong with each section, worst first. Guidance, not rules:
 *  the team can always submit anyway. */
export function reviewChecks(sections = [], guides = {}, teamNames = []) {
  return sections.map(s => {
    const text = s.content || ''
    const words = wordCount(text)
    const target = guides[s.key]?.target_words || null
    const issues = []
    if (!words) {
      issues.push({ level: 'error', text: 'Empty — nothing will be submitted for this section.' })
    } else {
      if (target && words < target * 0.6) {
        issues.push({ level: 'warn', text: `${words} words; aim for about ${target}.` })
      }
      if (chatLines(text, teamNames) >= 2) {
        issues.push({ level: 'warn', text: 'Reads like a conversation. Rewrite it as the team\'s answer, and keep discussion in team chat.' })
      }
    }
    return { key: s.key, title: s.title || 'Document', words, target, issues }
  })
}

function Chip({ issues }) {
  const err = issues.some(i => i.level === 'error')
  const style = !issues.length
    ? { color: '#0D9488', background: '#E6F7F6', text: '✓ Looks complete' }
    : err ? { color: '#C8102E', background: '#FDE8EC', text: 'Needs writing' }
      : { color: '#B45309', background: '#FEF3C7', text: 'Check this' }
  return (
    <span className="text-[10px] font-bold rounded-full px-2 py-0.5 flex-shrink-0"
          style={{ color: style.color, background: style.background }}>{style.text}</span>
  )
}

export default function FinalReview({
  sections, guides, review, myId, nameFor, teamNames, notice,
  onClose, onEdit, onReady, readyBusy, onSubmitNow, ending, error,
}) {
  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const checks = reviewChecks(sections, guides, teamNames)
  const byKey = Object.fromEntries(checks.map(c => [c.key, c]))
  const open = checks.filter(c => c.issues.length)
  const empties = checks.filter(c => c.issues.some(i => i.level === 'error'))
  const required = review?.required || []
  const ready = new Set(review?.ready_user_ids || [])
  const iAmReady = ready.has(myId)
  const waitingOn = required.filter(m => !ready.has(m.user_id))
  const total = checks.reduce((n, c) => n + c.words, 0)

  const markReady = () => {
    if (!iAmReady && empties.length &&
        !window.confirm(`${empties.map(c => `"${c.title}"`).join(', ')} ${empties.length === 1 ? 'is' : 'are'} still empty. Mark ready anyway?`)) return
    onReady(!iAmReady)
  }

  return (
    <div role="dialog" aria-modal="true" aria-label="Final review"
         className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4" style={{ background: 'rgba(22,18,14,0.45)' }}>
      <div className="bg-[#FDFCFB] rounded-[14px] flex flex-col w-full overflow-hidden"
           style={{ maxWidth: '1180px', height: 'min(92vh, 1000px)', border: '1.5px solid #E7E0D8' }}>
        <div className="flex items-center gap-3 px-5 py-3 border-b border-[#E7E0D8] flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
          <div className="min-w-0">
            <div className="text-[15px] font-bold text-[#16120E]">Final review</div>
            <div className="text-[12px] text-[#6B6560]">This is exactly what your instructor will receive. You can still edit until everyone is ready.</div>
          </div>
          <button type="button" onClick={onClose}
                  className="ml-auto px-3 py-1.5 text-[12px] font-bold text-[#4A4440] bg-[#F7F3EE] border border-[#E7E0D8] rounded-[8px] cursor-pointer flex-shrink-0">
            Back to editing
          </button>
        </div>

        {notice && (
          <div className="px-5 py-2 bg-[#FEF3C7] text-[12px] text-[#92400E] flex-shrink-0">{notice}</div>
        )}

        <div className="flex-1 min-h-0 flex flex-col md:flex-row overflow-auto md:overflow-hidden">
          {/* The document */}
          <div className="md:flex-1 md:min-w-0 md:overflow-auto bg-white">
            <article className="max-w-[720px] mx-auto px-6 py-6">
              {sections.map(s => {
                const c = byKey[s.key]
                const brief = guides[s.key]?.prompt
                return (
                  <section key={s.key} className="mb-7">
                    <div className="flex items-center gap-2 flex-wrap">
                      {s.title && <h2 className="text-[17px] font-bold text-[#16120E] m-0">{s.title}</h2>}
                      <Chip issues={c.issues} />
                      <span className="text-[11px] text-[#9A948E]">{c.words} word{c.words === 1 ? '' : 's'}{c.target ? ` / ~${c.target}` : ''}</span>
                      <button type="button" onClick={() => onEdit(s.key)}
                              className="ml-auto text-[12px] font-bold text-[#C8102E] underline cursor-pointer bg-transparent border-0">
                        {c.words ? 'Edit' : 'Write it'}
                      </button>
                    </div>
                    {brief && <div className="text-[12px] text-[#9A948E] italic mt-1">Brief: {brief}</div>}
                    {c.issues.map((i, n) => (
                      <div key={n} className="text-[12px] mt-1" style={{ color: i.level === 'error' ? '#C8102E' : '#B45309' }}>⚠ {i.text}</div>
                    ))}
                    <div className="mt-2">
                      {c.words
                        ? <div className="prose-chat text-[14px] text-[#16120E] leading-relaxed"><ReactMarkdown remarkPlugins={[remarkGfm]}>{s.content}</ReactMarkdown></div>
                        : <div className="text-[13px] italic text-[#B5AFA8]">(empty)</div>}
                    </div>
                  </section>
                )
              })}
            </article>
          </div>

          {/* Checklist and readiness */}
          <aside className="md:w-[330px] flex-shrink-0 md:overflow-auto border-t md:border-t-0 md:border-l border-[#E7E0D8] bg-[#FBF9F6] p-5 flex flex-col gap-5">
            <div>
              <div className="text-[11px] font-bold text-[#6B6560] uppercase tracking-[0.6px] mb-2">Checklist</div>
              {open.length === 0
                ? <div className="text-[13px] text-[#0D9488] font-semibold">✓ Every section is written.</div>
                : <div className="text-[13px] text-[#4A4440] mb-1">{open.length} section{open.length === 1 ? '' : 's'} to look at:</div>}
              <ul className="m-0 p-0 list-none flex flex-col gap-1.5">
                {checks.map(c => (
                  <li key={c.key} className="flex items-start gap-2 text-[12px]">
                    <span aria-hidden style={{ color: !c.issues.length ? '#0D9488' : c.issues.some(i => i.level === 'error') ? '#C8102E' : '#B45309' }}>
                      {!c.issues.length ? '✓' : '⚠'}
                    </span>
                    <button type="button" onClick={() => onEdit(c.key)}
                            className="text-left text-[#16120E] bg-transparent border-0 p-0 cursor-pointer hover:underline">
                      {c.title}
                      {c.issues[0] && <span className="block text-[11px] text-[#9A948E]">{c.issues[0].text}</span>}
                    </button>
                  </li>
                ))}
              </ul>
              <div className="text-[11px] text-[#9A948E] mt-2">{total} words in total.</div>
            </div>

            <div>
              <div className="text-[11px] font-bold text-[#6B6560] uppercase tracking-[0.6px] mb-2">Ready to submit</div>
              <ul className="m-0 p-0 list-none flex flex-col gap-1">
                {required.map(m => (
                  <li key={m.user_id} className="text-[13px] flex items-center gap-2">
                    <span style={{ color: ready.has(m.user_id) ? '#0D9488' : '#B5AFA8' }}>{ready.has(m.user_id) ? '✓' : '○'}</span>
                    <span className="text-[#16120E]">{m.user_id === myId ? 'You' : (m.name || nameFor(m.user_id) || 'Teammate')}</span>
                    {!ready.has(m.user_id) && <span className="text-[11px] text-[#9A948E]">still reviewing</span>}
                  </li>
                ))}
              </ul>
              <button type="button" onClick={markReady} disabled={readyBusy}
                      className="mt-3 w-full px-3 py-2.5 text-[13px] font-bold rounded-[9px] cursor-pointer disabled:opacity-50"
                      style={iAmReady
                        ? { color: '#4A4440', background: '#fff', border: '1.5px solid #E7E0D8' }
                        : { color: '#fff', background: '#0D9488', border: '1.5px solid #0D9488' }}>
                {readyBusy ? 'Saving…' : iAmReady ? 'Not ready yet' : "I'm ready to submit"}
              </button>
              <div className="text-[11px] text-[#9A948E] mt-2 leading-snug">
                {iAmReady && waitingOn.length
                  ? `Waiting for ${waitingOn.map(m => m.name || 'a teammate').join(', ')}. `
                  : ''}
                The document is submitted when everyone is ready. Any edit clears everyone's ready, so the team approves the final text.
              </div>
              {error && <div role="alert" className="text-[12px] text-[#C8102E] mt-2">{error}</div>}
            </div>

            <div className="mt-auto pt-3 border-t border-[#EFE8DF]">
              <button type="button" onClick={onSubmitNow} disabled={ending}
                      className="text-[12px] font-bold text-[#C8102E] underline bg-transparent border-0 p-0 cursor-pointer disabled:opacity-50">
                {ending ? 'Submitting…' : 'Submit now without waiting'}
              </button>
              <div className="text-[11px] text-[#9A948E] mt-1">Ends the session for the whole team.</div>
            </div>
          </aside>
        </div>

        {/* On a phone the checklist sits below the whole document; keep the
            decision itself within reach. */}
        <div className="md:hidden flex items-center gap-3 px-4 py-3 border-t border-[#E7E0D8] bg-[#FDFCFB] flex-shrink-0">
          <div className="text-[12px] text-[#4A4440] min-w-0">
            <b>{ready.size}/{required.length}</b> ready{open.length ? ` · ${open.length} to check` : ''}
          </div>
          <button type="button" onClick={markReady} disabled={readyBusy}
                  className="ml-auto px-3 py-2 text-[12px] font-bold rounded-[8px] cursor-pointer disabled:opacity-50 flex-shrink-0"
                  style={iAmReady
                    ? { color: '#4A4440', background: '#fff', border: '1.5px solid #E7E0D8' }
                    : { color: '#fff', background: '#0D9488', border: '1.5px solid #0D9488' }}>
            {readyBusy ? 'Saving…' : iAmReady ? 'Not ready yet' : "I'm ready"}
          </button>
        </div>
      </div>
    </div>
  )
}
