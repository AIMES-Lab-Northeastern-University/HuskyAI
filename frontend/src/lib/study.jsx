/**
 * Study mode (cognitive-offloading experiment), frontend side.
 *
 * Off unless the frontend is built with VITE_STUDY_MODE_ENABLED=true: with it
 * unset every function here answers "not a participant" and no study UI or
 * route is rendered, so normal users get exactly the app they had before.
 *
 * The server is the real gate (it withholds feedback and enforces task
 * order); everything here is a second layer and routing convenience.
 */
import { useEffect, useRef, useState } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { API_URL, authHeaders, clearSession } from './api'

export const PARTICIPANT_KEY = 'study_participant'
const LAST_BLOCK_KEY = 'study_last_block'
export const STUDY_HOME = '/study/home'
export const BAD_CODE_MESSAGE = 'That code was not recognised.'
export const STUDY_ENDED_MESSAGE = 'This study session has ended.'
export const STUDY_UNAVAILABLE_MESSAGE = "HuskyAI can't be reached right now. Please try again in a moment."
export const RETURN_TO_SURVEY = 'Return to the survey tab and paste this code.'

/** Read per call (not once at import) so tests can toggle it. */
export function studyUiEnabled() {
  return import.meta.env.VITE_STUDY_MODE_ENABLED === 'true'
}

/** Set only by a study-code sign-in, cleared with the rest of the session. */
export function isParticipant() {
  if (!studyUiEnabled()) return false
  try { return localStorage.getItem(PARTICIPANT_KEY) === 'true' } catch { return false }
}

// Neutral names: words like "test" or "training" could shape how a
// participant approaches a block. Lucy's design has two parts (tasks 1-3 and
// 4-6); the pretest block is empty there.
const BLOCK_LABELS = { pretest: 'Warm-up', training: 'Part 1 of 2', posttest: 'Part 2 of 2' }

/** How many tasks a survey participant does (Lucy's design). */
export const STUDY_TASK_COUNT = 6
export function blockLabel(block) {
  return BLOCK_LABELS[block] || ''
}

/** Where a participant may be. Everything else sends them to StudyHome. */
export function participantMayVisit(pathname) {
  return pathname === '/study' || pathname === STUDY_HOME
    || pathname === '/workspace' || /^\/challenges\/[^/]+$/.test(pathname)
}

/** Rendered once inside the router: keeps a participant on study routes. */
export function StudyRedirect() {
  const { pathname } = useLocation()
  if (!isParticipant() || participantMayVisit(pathname)) return null
  return <Navigate to={STUDY_HOME} replace />
}

/** POST /auth/study-login and store the session exactly as a normal sign-in
 * does, plus the participant marker. Returns { ok, error }. */
export async function studyLogin(code) {
  let res
  try {
    res = await fetch(`${API_URL}/auth/study-login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code }),
    })
  } catch {
    return { ok: false, unavailable: true, error: STUDY_UNAVAILABLE_MESSAGE }
  }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    // A pause after repeated tries says so.
    if (res.status === 429 && typeof data.detail === 'string') return { ok: false, error: data.detail }
    // A right code whose study session is over (expired or revoked).
    if (res.status === 403) return { ok: false, ended: true, error: STUDY_ENDED_MESSAGE }
    // A wrong or malformed code: the one generic message, so the page never
    // hints whether a code exists.
    if (res.status === 401 || res.status === 422) return { ok: false, error: BAD_CODE_MESSAGE }
    // Anything else (503 misconfigured, 5xx, 404 study off) is the server's
    // fault, not the code's, and says nothing about the code.
    return { ok: false, unavailable: true, error: STUDY_UNAVAILABLE_MESSAGE }
  }
  // A shared lab machine: whoever signed in before must not leak into this.
  clearSession()
  localStorage.setItem('token', data.access_token)
  localStorage.setItem('user', JSON.stringify({
    id: data.user_id, name: data.name, email: data.email,
    is_platform_admin: Boolean(data.is_platform_admin),
  }))
  localStorage.setItem('research_ack', data.research_acknowledged ? 'true' : 'false')
  localStorage.setItem(PARTICIPANT_KEY, 'true')
  try { localStorage.removeItem(LAST_BLOCK_KEY) } catch { /* storage blocked */ }
  return { ok: true }
}

/** GET /study/me. null when the server is not running a study (404) or the
 * call failed, so the caller can fall back to the normal app. */
export async function fetchStudyMe() {
  try {
    const r = await fetch(`${API_URL}/study/me`, { headers: { ...authHeaders() } })
    if (!r.ok) return null
    return await r.json()
  } catch {
    return null
  }
}

/** The block the participant last acknowledged, for the transition screen. */
export function lastSeenBlock() {
  try { return localStorage.getItem(LAST_BLOCK_KEY) } catch { return null }
}
export function rememberBlock(block) {
  try { localStorage.setItem(LAST_BLOCK_KEY, block) } catch { /* storage blocked */ }
}

/**
 * The Workspace's second layer. When the server said feedback_visible: false,
 * any score frame that still arrives (it should not) is turned into its
 * suppressed form before the page sees it, so a server regression cannot put
 * a score on screen.
 */
export function maskFeedbackFrame(data) {
  switch (data?.type) {
    case 'eval':
      return { type: 'eval_suppressed', turn: data.turn }
    case 'eval_late':
      return { type: 'eval_late_suppressed', turn: data.turn }
    case 'eval_pending':
      return { ...data, suppressed: true, message: null }
    case 'eval_rescore_failed':
      return { ...data, message: null }
    case 'revision_required':
      return { type: 'ignored' }
    default:
      return data
  }
}

/** The one nav entry a participant gets in the Sidebar. */
export const STUDY_NAV = [{
  group: 'Study',
  items: [{
    label: 'Study tasks', path: STUDY_HOME,
    icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>,
  }],
}]

/** The no-feedback panel a participant sees. Neutral on purpose: it must not
 * suggest that the work is scored at all. */
export const NEUTRAL_PANEL_TEXT = "Thanks, continue with the task when you're ready."

/** Replaces the Workspace's "Session ended" banner for a participant: no
 * score, no Husky Score, and page 1 of the end-of-task questions under the
 * finished task. Page 2 and the completion code replace the whole workspace
 * (StudyTaskFinishedPage). Outside a survey link, the way back to the task
 * list. `study` is the Workspace's useCompletion(). */
export function StudyTaskEnded({ canViewAnalysis = false, onViewAnalysis, study = null,
  fromSurvey = false }) {
  const pending = study?.pending
  return (
    <div className="bg-[#F7F3EE] border-[1.5px] border-[#E7E0D8] rounded-[12px] px-[18px] py-[14px] text-center text-[13px] text-[#6B6560]">
      <div className="font-medium mb-[10px]">Task finished</div>
      {pending?.stage === 'answers' && (
        <EndOfTaskAnswers task={pending.task} questions={pending.questions} onDone={study.onAnswered} />
      )}
      {fromSurvey && !pending && !study?.completion && (
        <div className="text-[12px] text-[#9A948E] mb-[10px]">Getting your completion code…</div>
      )}
      {!fromSurvey && !pending && <div className="flex gap-2 justify-center">
        {canViewAnalysis && onViewAnalysis && (
          <button type="button" onClick={onViewAnalysis}
            className="px-4 py-[7px] bg-[#FDFCFB] text-[#4A4440] border-[1.5px] border-[#E7E0D8] rounded-[8px] text-[13px] font-semibold cursor-pointer">
            View session analysis
          </button>
        )}
        <Link to={STUDY_HOME}
          className="px-4 py-[7px] bg-[#C8102E] text-white rounded-[8px] text-[13px] font-semibold no-underline">
          Back to study tasks
        </Link>
      </div>}
    </div>
  )
}

/** Whether the finished task has moved past page 1, so StudyTaskFinishedPage
 * takes over the whole workspace (the task and the chat are no longer shown). */
export function studyTakesOver(study) {
  return Boolean(study?.completion || study?.pending?.stage === 'ratings')
}

/** Page 2 of the end-of-task questions, then the completion code, on a page
 * of their own: the task and the chat are gone, and there is no way back to
 * page 1 (it is locked on the server too). */
export function StudyTaskFinishedPage({ study, fromSurvey = false }) {
  const { pending, completion, onAnswered } = study
  return (
    <div className="min-h-screen flex items-center justify-center bg-[#F7F3EE] p-6" data-testid="study-finished-page">
      <div className="w-full max-w-[560px]">
        {pending?.stage === 'ratings' && !completion && (
          <EndOfTaskRatings task={pending.task} ratings={pending.ratings} onDone={onAnswered} />
        )}
        {completion && <CompletionCode code={completion.completion_code} />}
        {completion && !fromSurvey && (
          <div className="text-center">
            <Link to={STUDY_HOME}
              className="inline-block px-4 py-[7px] bg-[#C8102E] text-white rounded-[8px] text-[13px] font-semibold no-underline">
              Back to study tasks
            </Link>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Qualtrics flow: per-task links and completion codes ────────────────────

/** POST /study/tasks/{n}/enter. The server decides: { status: 'ready' |
 * 'completed' | 'locked', ... }, or 'ended' when the study session is over. */
export async function enterTask(task) {
  try {
    const r = await fetch(`${API_URL}/study/tasks/${task}/enter`, {
      method: 'POST', headers: { ...authHeaders() },
    })
    if (r.status === 401 || r.status === 403) return { status: 'ended' }
    if (!r.ok) return { status: 'error' }
    return await r.json()
  } catch {
    return { status: 'error' }
  }
}

/** GET /study/completion once the task is finished on the server: either
 * { task, completion_code, embed_origins }, or { task, answers_required: true,
 * stage, questions, ratings } while a page of its questions is owed. Else null. */
export async function fetchCompletion(challengeId) {
  try {
    const r = await fetch(`${API_URL}/study/completion?challenge_id=${encodeURIComponent(challengeId)}`,
      { headers: { ...authHeaders() } })
    if (!r.ok) return null
    const data = await r.json()
    if (data?.answers_required === true && data.questions) return data
    return typeof data?.completion_code === 'string' ? data : null
  } catch {
    return null
  }
}

/** Tell the page that embeds HuskyAI that the task is done. Only with embed=1,
 * only when actually framed, and only to origins on the server's allowlist
 * (STUDY_EMBED_ORIGINS): postMessage drops a message whose targetOrigin does
 * not match the parent, so posting to each allowed origin reaches the parent
 * only if it is one of them. Never "*". Two messages per origin: the survey's
 * { type: 'taskcomplete', task } and the older huskyai_task_complete, which
 * also carries the code. Returns how many origins were posted to. */
export function postCompletionToParent({ task, completion_code: code, embed_origins: origins }, embed) {
  if (!embed || typeof window === 'undefined' || window.parent === window) return 0
  let n = 0
  for (const origin of Array.isArray(origins) ? origins : []) {
    if (typeof origin !== 'string' || !/^https?:\/\/[^/*\s]+$/.test(origin)) continue
    try {
      window.parent.postMessage({ type: 'taskcomplete', task }, origin)
      window.parent.postMessage({ type: 'huskyai_task_complete', task, completion_code: code }, origin)
      n++
    } catch { /* a bad origin string: skip it */ }
  }
  return n
}

/** A finished task's owed page of questions, then its completion code.
 * Retried briefly (the server may still be finishing the task when the page
 * asks). The code is posted to an embedding parent once, when it first
 * arrives: straight away, or after page 2. Pass a null challengeId to stay
 * idle. Returns { completion, pending, onAnswered }: `pending` is the server's
 * { task, stage: 'answers' | 'ratings', questions, ratings } while a page is
 * owed, and onAnswered takes either page's response. */
export function useCompletion(challengeId, embed = false) {
  const [completion, setCompletion] = useState(null)
  const [pending, setPending] = useState(null)
  const posted = useRef(false)
  const receive = (c) => {
    setCompletion(c)
    setPending(null)
    if (!posted.current) { posted.current = true; postCompletionToParent(c, embed) }
  }
  const onAnswered = (data) => {
    if (data?.stage === 'ratings') {
      setPending(p => ({ ...(p || {}), task: data.task, stage: 'ratings', ratings: data.ratings }))
    } else if (typeof data?.completion_code === 'string') {
      receive(data)
    }
  }
  useEffect(() => {
    if (!challengeId || !isParticipant()) return undefined
    let cancelled = false
    let timer = null
    const attempt = async (left) => {
      const c = await fetchCompletion(challengeId)
      if (cancelled) return
      if (c?.answers_required) {
        setPending(c)
      } else if (c) {
        receive(c)
      } else if (left > 0) {
        timer = setTimeout(() => attempt(left - 1), 1000)
      }
    }
    attempt(5)
    return () => { cancelled = true; clearTimeout(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [challengeId, embed])
  return { completion, pending, onAnswered }
}

/** POST one page of a task's questions. { ok: true, data } on success, and
 * also when that page was already submitted (the first submit stands; data
 * then says what comes next). Otherwise { ok: false, error }. */
async function postTaskPage(task, page, body) {
  let r
  try {
    r = await fetch(`${API_URL}/study/tasks/${task}/${page}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(body),
    })
  } catch {
    return { ok: false, error: 'Could not reach the server. Try again.' }
  }
  const data = await r.json().catch(() => ({}))
  if (r.ok) return { ok: true, data }
  const detail = data?.detail
  if (r.status === 409 && detail && typeof detail === 'object' && detail.stage) {
    return { ok: true, data: detail }
  }
  if (r.status === 401 || r.status === 403) return { ok: false, error: STUDY_ENDED_MESSAGE }
  if (r.status === 422 && typeof detail === 'string') return { ok: false, error: detail }
  return { ok: false, error: 'Your answers could not be saved. Try again.' }
}

/** Page 1: POST /study/tasks/{n}/answers. data is page 2 ({ stage: 'ratings',
 * ratings }) or, if page 2 is already done, the code. */
export function submitTaskAnswers(task, { total, corrections }) {
  return postTaskPage(task, 'answers', { total, corrections })
}

/** Page 2: POST /study/tasks/{n}/ratings. data is { task, completion_code,
 * embed_origins }. */
export function submitTaskRatings(task, { confidence, trust, check }) {
  const body = { confidence }
  if (trust != null) body.trust = trust
  if (check != null) body.check = check
  return postTaskPage(task, 'ratings', body)
}

// A dollar amount: optional "$", thousands commas, at most 2 decimals. The
// server applies the same rule.
const TOTAL_RE = /^\$?\s*(\d{1,3}(,\d{3})+|\d{1,9})(\.\d{1,2})?$/

const FORM = 'text-left bg-[#FDFCFB] border-[1.5px] border-[#E7E0D8] rounded-[12px] px-5 py-4 my-3'
const LABEL = 'block text-[13px] font-semibold text-[#16120E] mb-[6px] leading-snug'
const BOX = 'w-full px-3 py-2 bg-white border-[1.5px] border-[#E7E0D8] rounded-[8px] text-[14px] text-[#16120E] disabled:bg-[#F7F3EE]'

function SubmitRow({ ready, submitting, label }) {
  return (
    <div className="mt-4 flex items-center gap-3">
      <button type="submit" disabled={!ready || submitting}
        className="px-4 py-[7px] bg-[#C8102E] text-white rounded-[8px] text-[13px] font-semibold border-none cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed">
        {submitting ? 'Submitting…' : label}
      </button>
      <span className="text-[12px] text-[#9A948E]">You can't change your answers after submitting.</span>
    </div>
  )
}

/** Page 1: the total (a dollar amount) and the corrections. Both required;
 * submitting locks the page. */
export function EndOfTaskAnswers({ task, questions, onDone }) {
  const [total, setTotal] = useState('')
  const [corrections, setCorrections] = useState('')
  const [state, setState] = useState({ status: 'editing' })
  const done = state.status === 'submitted'
  const totalOk = TOTAL_RE.test(total.trim())
  const ready = totalOk && corrections.trim() !== ''

  const submit = async (e) => {
    e.preventDefault()
    if (!ready || done || state.status === 'submitting') return
    setState({ status: 'submitting' })
    const res = await submitTaskAnswers(task, { total: total.trim(), corrections })
    if (!res.ok) { setState({ status: 'editing', error: res.error }); return }
    setState({ status: 'submitted' })
    onDone?.(res.data)
  }

  return (
    <form onSubmit={submit} data-testid="end-answers" className={FORM}>
      <div className="text-[11px] font-bold text-[#9A948E] uppercase tracking-[0.7px] mb-3">
        {done ? 'Your answers (submitted)' : 'A few questions about this task'}
      </div>
      <fieldset disabled={done || state.status === 'submitting'} className="border-0 p-0 m-0 flex flex-col gap-4">
        <div>
          <label htmlFor="eq-total" className={LABEL}>{questions.total}</label>
          <input id="eq-total" type="text" inputMode="decimal" autoComplete="off"
            value={total} onChange={e => setTotal(e.target.value)}
            aria-invalid={total.trim() !== '' && !totalOk} className={`${BOX} max-w-[200px]`} />
          <div className="text-[12px] text-[#9A948E] mt-1">
            {total.trim() !== '' && !totalOk ? 'Enter a dollar amount with at most 2 decimal places.' : 'A dollar amount, up to 2 decimal places.'}
          </div>
        </div>
        <div>
          <label htmlFor="eq-corrections" className={LABEL}>{questions.corrections}</label>
          <textarea id="eq-corrections" rows={5} maxLength={5000}
            value={corrections} onChange={e => setCorrections(e.target.value)} className={BOX} />
        </div>
      </fieldset>
      {state.error && <p role="alert" className="text-[13px] text-[#C8102E] mt-3 mb-0">{state.error}</p>}
      {!done && <SubmitRow ready={ready} submitting={state.status === 'submitting'} label="Continue" />}
    </form>
  )
}

/** Page 2: the confidence slider, and on a post-test task the two agreement
 * items. The slider counts as answered only once it has been moved or
 * clicked, so its starting position is never recorded as an answer. */
export function EndOfTaskRatings({ task, ratings, onDone }) {
  const [confidence, setConfidence] = useState(null)
  const [trust, setTrust] = useState(null)
  const [check, setCheck] = useState(null)
  const [state, setState] = useState({ status: 'editing' })
  const agreement = ratings?.agreement
  const done = state.status === 'submitted'
  const ready = confidence !== null && (!agreement || (trust !== null && check !== null))
  const touchSlider = (e) => setConfidence(Number(e.target.value))

  const submit = async (e) => {
    e.preventDefault()
    if (!ready || done || state.status === 'submitting') return
    setState({ status: 'submitting' })
    const res = await submitTaskRatings(task, agreement ? { confidence, trust, check } : { confidence })
    if (!res.ok) { setState({ status: 'editing', error: res.error }); return }
    setState({ status: 'submitted' })
    onDone?.(res.data)
  }

  const scale = (name, value, set) => (
    <div role="radiogroup" aria-label={agreement[name]} className="grid grid-cols-6 gap-1 mt-2">
      {agreement.scale.map((label, i) => (
        <label key={label} className="flex flex-col items-center gap-1 text-[11px] text-[#6B6560] text-center leading-tight cursor-pointer">
          <input type="radio" name={`${name}-${task}`} value={i + 1} checked={value === i + 1}
            onChange={() => set(i + 1)} data-testid={`${name}-${i + 1}`} />
          {label}
        </label>
      ))}
    </div>
  )

  return (
    <form onSubmit={submit} data-testid="end-ratings" className={FORM}>
      <fieldset disabled={done || state.status === 'submitting'} className="border-0 p-0 m-0 flex flex-col gap-5">
        <div>
          <label htmlFor="eq-confidence" className={LABEL}>{ratings.confidence}</label>
          <div className="flex items-center gap-3">
            <span className="text-[12px] text-[#6B6560] text-right w-[90px]">0% {ratings.confidence_low}</span>
            <input id="eq-confidence" type="range" min={0} max={100} step={1}
              value={confidence ?? 50} onChange={touchSlider} onPointerUp={touchSlider} onKeyUp={touchSlider}
              aria-valuetext={confidence === null ? 'Not answered yet' : `${confidence}%`}
              className={`flex-1 ${confidence === null ? 'opacity-50' : ''}`} />
            <span className="text-[12px] text-[#6B6560] w-[90px]">100% {ratings.confidence_high}</span>
          </div>
          <div data-testid="confidence-value" className="text-[13px] text-[#4A4440] mt-1 text-center">
            {confidence === null ? 'Move the slider to answer' : `${confidence}%`}
          </div>
        </div>
        {agreement && (
          <div>
            <div className={LABEL}>{agreement.stem}</div>
            <div className="mt-2 text-[13px] text-[#16120E]">{agreement.trust}</div>
            {scale('trust', trust, setTrust)}
            <div className="mt-4 text-[13px] text-[#16120E]">{agreement.check}</div>
            {scale('check', check, setCheck)}
          </div>
        )}
      </fieldset>
      {state.error && <p role="alert" className="text-[13px] text-[#C8102E] mt-3 mb-0">{state.error}</p>}
      {!done && <SubmitRow ready={ready} submitting={state.status === 'submitting'} label="Submit answers" />}
    </form>
  )
}

/** The completion code, a copy button, and what to do with it. */
export function CompletionCode({ code }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }
  return (
    <div className="bg-[#FDFCFB] border-[1.5px] border-[#E7E0D8] rounded-[12px] px-5 py-4 my-3 text-center">
      <div className="text-[11px] font-bold text-[#9A948E] uppercase tracking-[0.7px] mb-2">Completion code</div>
      <div className="flex items-center justify-center gap-3 mb-2">
        <code data-testid="completion-code"
          className="font-mono text-[24px] tracking-[3px] text-[#16120E] select-all">{code}</code>
        <button type="button" onClick={copy}
          className="px-3 py-[6px] bg-[#C8102E] text-white text-[12px] font-semibold border-none rounded-[8px] cursor-pointer">
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <p className="text-[13px] text-[#4A4440] m-0">{RETURN_TO_SURVEY}</p>
    </div>
  )
}

/** Shown when the server refuses the task's socket (4003): the task is not
 * the participant's current one, or their block has moved on. Inside the
 * survey there is no task list to go back to. */
export function StudyTaskUnavailable({ fromSurvey = false }) {
  return (
    <div role="alert" className="max-w-[420px] mx-auto my-16 bg-[#FDFCFB] border-[1.5px] border-[#E7E0D8] rounded-[14px] p-6 text-center">
      <div className="text-[15px] font-semibold text-[#16120E] mb-2">This task isn't available</div>
      <p className="text-[13px] text-[#6B6560] mb-4">It may already be finished, or it isn't your turn for it yet.</p>
      {!fromSurvey && (
        <Link to={STUDY_HOME}
          className="inline-block px-4 py-2 bg-[#C8102E] text-white rounded-[9px] text-[13px] font-semibold no-underline">
          Back to study tasks
        </Link>
      )}
    </div>
  )
}

/** A challenge as a participant sees it: one task is session 1 only, so the
 * later sessions (which the server refuses anyway) are not shown. */
export function studyTaskView(challenge) {
  const sessions = (challenge.sessions || []).filter(s => s.session_number === 1)
  return { ...challenge, sessions, total_sessions: sessions.length }
}
