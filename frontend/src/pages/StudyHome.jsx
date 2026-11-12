import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import { API_URL, authHeaders, clearSession, readApiError } from '../lib/api'
import { blockLabel, lastSeenBlock, rememberBlock } from '../lib/study'

/** A participant's home: the current block's tasks, in the order the server
 * assigned, and the one task they may do now. Says nothing about condition or
 * scores, because the server sends neither. */
export default function StudyHome() {
  const navigate = useNavigate()
  const [state, setState] = useState({ status: 'loading' })
  const [transition, setTransition] = useState(null)   // { from, to } between blocks
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState('')

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${API_URL}/study/tasks`, { headers: { ...authHeaders() } })
      if (r.status === 404) { setState({ status: 'closed' }); return }
      if (!r.ok) { setState({ status: 'error' }); return }
      const data = await r.json()
      const last = lastSeenBlock()
      if (last && last !== data.current_block && data.current_block !== 'done') {
        setTransition({ from: last, to: data.current_block })
      } else {
        rememberBlock(data.current_block)
      }
      setState({ status: 'ready', data })
    } catch {
      setState({ status: 'error' })
    }
  }, [])

  useEffect(() => { load() }, [load])

  const logout = () => { clearSession(); navigate('/study', { replace: true }) }

  const start = async (task) => {
    setStarting(true)
    setStartError('')
    try {
      const r = await fetch(`${API_URL}/challenges/${task.challenge_id}/sessions/${task.session_number}/start`, {
        method: 'POST', headers: { ...authHeaders() },
      })
      if (!r.ok) {
        // Most likely the task was finished in another tab: refresh the list.
        setStartError(r.status === 404 ? '' : await readApiError(r, 'Could not open the task'))
        setStarting(false)
        load()
        return
      }
      navigate(`/workspace?challenge=${task.challenge_id}&session=${task.session_number}`)
    } catch {
      setStartError('Could not reach the server. Try again.')
      setStarting(false)
    }
  }

  return (
    <div className="flex h-screen bg-[#F7F3EE] overflow-hidden">
      <Sidebar onLogout={logout} />
      <div className="flex-1 overflow-y-auto" style={{ marginLeft: 'var(--sidebar-width, 220px)', transition: 'margin-left 200ms ease' }}>
        <div className="max-w-[640px] mx-auto px-6 py-12">
          <Body state={state} transition={transition} starting={starting} startError={startError}
            onContinue={() => { rememberBlock(transition.to); setTransition(null) }}
            onStart={start} onRetry={() => { setState({ status: 'loading' }); load() }} />
        </div>
      </div>
    </div>
  )
}

function Card({ children }) {
  return (
    <div className="bg-[#FDFCFB] border-[1.5px] border-[#E7E0D8] rounded-[14px] p-8">{children}</div>
  )
}

function Body({ state, transition, starting, startError, onContinue, onStart, onRetry }) {
  if (state.status === 'loading') {
    return <div className="text-[14px] text-[#9A948E]">Loading…</div>
  }
  if (state.status === 'closed') {
    return (
      <Card>
        <h1 className="font-serif text-[24px] text-[#16120E] mb-2">The study isn't open</h1>
        <p className="text-[13px] text-[#6B6560] leading-relaxed">
          There are no study tasks for this account right now. Please check with the researcher.
        </p>
      </Card>
    )
  }
  if (state.status === 'error') {
    return (
      <Card>
        <h1 className="font-serif text-[24px] text-[#16120E] mb-2">Something went wrong</h1>
        <p className="text-[13px] text-[#6B6560] mb-4">We couldn't load your tasks.</p>
        <button type="button" onClick={onRetry}
          className="px-4 py-2 bg-[#C8102E] text-white text-[13px] font-semibold border-none rounded-[9px] cursor-pointer">
          Try again
        </button>
      </Card>
    )
  }

  const { current_block: block, progress, tasks } = state.data

  if (block === 'done') {
    return (
      <Card>
        <h1 className="font-serif text-[26px] text-[#16120E] mb-2">Thank you</h1>
        <p className="text-[14px] text-[#4A4440] leading-relaxed">
          You've finished all the study tasks. You can close this window now.
        </p>
      </Card>
    )
  }

  if (transition) {
    return (
      <Card>
        <div className="text-[11px] font-bold text-[#9A948E] uppercase tracking-[0.7px] mb-2">
          {blockLabel(transition.from)} complete
        </div>
        <h1 className="font-serif text-[26px] text-[#16120E] mb-2">Next: {blockLabel(transition.to)}</h1>
        <p className="text-[13px] text-[#6B6560] leading-relaxed mb-5">
          Take a short break if you like. Continue when you're ready.
        </p>
        <button type="button" onClick={onContinue}
          className="px-5 py-[10px] bg-[#C8102E] text-white text-[13px] font-semibold border-none rounded-[9px] cursor-pointer">
          Continue
        </button>
      </Card>
    )
  }

  const pct = progress.total ? Math.round((progress.completed / progress.total) * 100) : 0
  return (
    <Card>
      <div className="text-[11px] font-bold text-[#9A948E] uppercase tracking-[0.7px] mb-1">Study</div>
      <h1 className="font-serif text-[28px] text-[#16120E] mb-4">{blockLabel(block)}</h1>
      <div className="mb-6">
        <div className="text-[12px] text-[#6B6560] mb-1.5" data-testid="study-progress">
          {progress.completed} of {progress.total} tasks done
        </div>
        <div className="h-1.5 bg-[#E7E0D8] rounded-full">
          <div className="h-1.5 bg-[#C8102E] rounded-full" style={{ width: `${pct}%` }} />
        </div>
      </div>
      {tasks.length === 0 ? (
        <p className="text-[13px] text-[#6B6560]">There's nothing to do here yet. Please check with the researcher.</p>
      ) : (
        <ol className="flex flex-col gap-2 list-none p-0 m-0">
          {tasks.map((t, i) => (
            <li key={t.challenge_id} data-testid="study-task"
              className={`flex items-center justify-between gap-3 rounded-[10px] border-[1.5px] px-4 py-3 ${t.current ? 'border-[#C8102E] bg-white' : 'border-[#E7E0D8]'}`}>
              <div className="min-w-0">
                <div className="text-[11px] text-[#9A948E]">Task {i + 1}</div>
                <div className="text-[14px] font-semibold text-[#16120E] truncate">{t.title || `Task ${i + 1}`}</div>
              </div>
              {t.completed ? (
                <span className="text-[11px] font-semibold text-[#6B6560]">Done</span>
              ) : t.current ? (
                <button type="button" disabled={starting} onClick={() => onStart(t)}
                  className="px-4 py-2 bg-[#C8102E] hover:bg-[#9E0B24] disabled:opacity-60 text-white text-[13px] font-semibold border-none rounded-[9px] cursor-pointer">
                  {t.started ? 'Continue' : 'Start'}
                </button>
              ) : (
                <span className="text-[11px] text-[#9A948E]">Later</span>
              )}
            </li>
          ))}
        </ol>
      )}
      {startError && <div role="alert" className="text-[12px] text-red-700 mt-3">{startError}</div>}
    </Card>
  )
}
