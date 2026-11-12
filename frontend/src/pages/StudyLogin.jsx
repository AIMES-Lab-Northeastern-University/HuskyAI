import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  CompletionCode, EndOfTaskAnswers, EndOfTaskRatings, STUDY_ENDED_MESSAGE, STUDY_HOME,
  STUDY_TASK_COUNT, enterTask, fetchStudyMe, postCompletionToParent, studyLogin,
} from '../lib/study'

/** Sign-in for study participants: an anonymous code, no email.
 * /study?code=XXXX-XXXX-XXXX prefills the field (e.g. from a printed QR code).
 * /study?code=...&task=N is a survey link: sign in and open task N directly. */
export default function StudyLogin() {
  const [params] = useSearchParams()
  const task = Number.parseInt(params.get('task') || '', 10)
  const embed = params.get('embed') === '1'
  if (params.get('code') && task >= 1) {
    return <StudyTaskEntry code={params.get('code')} task={task} embed={embed} />
  }
  // Inside the survey, a link without a code or a task number is the survey's
  // set-up (e.g. task_n not set), never a reason to show the code form and
  // the task list in the frame.
  if (embed) {
    return <Shell><IncompleteSurveyLink /></Shell>
  }
  if (params.get('ended') === '1') {
    return <Shell><Ended /></Shell>
  }
  return <CodeForm initialCode={params.get('code') || ''} />
}

function Shell({ children }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-[#F7F3EE] p-6">
      <div className="w-full max-w-[440px] bg-[#FDFCFB] border-[1.5px] border-[#E7E0D8] rounded-[14px] p-8">
        {children}
      </div>
    </div>
  )
}

function Ended() {
  return (
    <>
      <h1 className="font-serif text-[24px] text-[#16120E] mb-2">{STUDY_ENDED_MESSAGE}</h1>
      <p className="text-[13px] text-[#6B6560] leading-relaxed m-0">
        Your work has been saved. You can close this tab.
      </p>
    </>
  )
}

function IncompleteSurveyLink() {
  return (
    <>
      <h1 className="font-serif text-[24px] text-[#16120E] mb-2">This task couldn't be opened</h1>
      <p role="alert" className="text-[13px] text-[#6B6560] leading-relaxed m-0">
        The survey didn't say which task to open. Please contact the research team.
      </p>
    </>
  )
}

/** A survey link. The server enforces the order; this page only shows what it said. */
function StudyTaskEntry({ code, task, embed }) {
  const navigate = useNavigate()
  const [state, setState] = useState({ status: 'working' })
  const ran = useRef(false)

  // Either page's response: page 2 next, or the code (posted to the parent).
  const onAnswered = (data) => {
    if (data?.stage === 'ratings') {
      setState(s => ({ ...s, stage: 'ratings', ratings: data.ratings }))
    } else if (typeof data?.completion_code === 'string') {
      setState(s => ({ ...s, completion: data }))
      postCompletionToParent(data, embed)
    }
  }

  const run = async () => {
    setState({ status: 'working' })
    const login = await studyLogin(code)
    if (!login.ok) {
      // A server fault is retryable and says nothing about the code.
      setState(login.ended ? { status: 'ended' }
        : login.unavailable ? { status: 'error', error: login.error }
        : { status: 'bad_code', error: login.error })
      return
    }
    const res = await enterTask(task)
    if (res.status === 'ready') {
      const q = new URLSearchParams({ challenge: res.challenge_id, session: String(res.session_number), task: String(task) })
      if (embed) q.set('embed', '1')
      navigate(`/workspace?${q}`, { replace: true })
      return
    }
    setState(res)
  }

  useEffect(() => {
    // Once per mount: a second sign-in from StrictMode's double effect is harmless
    // but pointless.
    if (ran.current) return
    ran.current = true
    run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <Shell>
      <div className="text-[11px] font-bold text-[#9A948E] uppercase tracking-[0.7px] mb-2">Task {task} of {STUDY_TASK_COUNT}</div>
      {state.status === 'working' && <p className="text-[14px] text-[#6B6560] m-0">Opening your task…</p>}
      {state.status === 'completed' && (
        <>
          <h1 className="font-serif text-[24px] text-[#16120E] mb-2">You've already completed task {task}</h1>
          <p className="text-[13px] text-[#6B6560] leading-relaxed mb-1">A task can only be done once. Here is its completion code again.</p>
          <CompletionCode code={state.completion_code} />
        </>
      )}
      {state.status === 'answers_required' && (
        // A finished task whose questions were never answered (a closed tab),
        // possibly an earlier task than this link's: the owed page, then the
        // next, then its code.
        <>
          <h1 className="font-serif text-[24px] text-[#16120E] mb-2">Task {state.task} is finished</h1>
          {!state.completion && (
            <p className="text-[13px] text-[#6B6560] leading-relaxed mb-1">
              Please answer these questions to get its completion code.
            </p>
          )}
          {state.stage === 'answers' && !state.completion && (
            <EndOfTaskAnswers task={state.task} questions={state.questions} onDone={onAnswered} />
          )}
          {state.stage === 'ratings' && !state.completion && (
            <EndOfTaskRatings key="ratings" task={state.task} ratings={state.ratings} onDone={onAnswered} />
          )}
          {state.completion && <CompletionCode code={state.completion.completion_code} />}
        </>
      )}
      {state.status === 'locked' && (
        <>
          <h1 className="font-serif text-[24px] text-[#16120E] mb-2">
            {state.current_task ? `Please complete task ${state.current_task} first` : 'All tasks are complete'}
          </h1>
          <p className="text-[13px] text-[#6B6560] leading-relaxed m-0">
            {state.current_task
              ? `Go back to the survey and open the link for task ${state.current_task}.`
              : 'There is nothing more to do here. You can close this tab.'}
          </p>
        </>
      )}
      {state.status === 'ended' && <Ended />}
      {state.status === 'bad_code' && (
        <>
          <h1 className="font-serif text-[24px] text-[#16120E] mb-2">This link didn't work</h1>
          <p role="alert" className="text-[13px] text-[#6B6560] leading-relaxed m-0">{state.error}</p>
        </>
      )}
      {state.status === 'error' && (
        <>
          <h1 className="font-serif text-[24px] text-[#16120E] mb-2">Something went wrong</h1>
          <p role="alert" className="text-[13px] text-[#6B6560] mb-4">{state.error || "We couldn't open your task."}</p>
          <button type="button" onClick={run}
            className="px-4 py-2 bg-[#C8102E] text-white text-[13px] font-semibold border-none rounded-[9px] cursor-pointer">
            Try again
          </button>
        </>
      )}
    </Shell>
  )
}

function CodeForm({ initialCode }) {
  const navigate = useNavigate()
  const [code, setCode] = useState(initialCode)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    if (!code.trim() || loading) return
    setError('')
    setLoading(true)
    const res = await studyLogin(code.trim())
    if (!res.ok) {
      setError(res.error)
      setLoading(false)
      return
    }
    // Confirms the server sees a participant; StudyHome handles the rest.
    await fetchStudyMe()
    navigate(STUDY_HOME, { replace: true })
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#F7F3EE] p-6">
      <div className="w-full max-w-[400px] bg-[#FDFCFB] border-[1.5px] border-[#E7E0D8] rounded-[14px] p-8">
        <h1 className="font-serif text-[26px] text-[#16120E] mb-2">Join the study</h1>
        <p className="text-[13px] text-[#6B6560] mb-6 leading-relaxed">
          Enter the code you were given. You don't need an account or an email address.
        </p>
        <form onSubmit={submit} className="flex flex-col gap-[18px]">
          <div>
            <label htmlFor="study-code" className="block text-[12px] font-semibold text-[#4A4440] mb-[6px] tracking-[0.2px]">
              Study code
            </label>
            <input
              id="study-code"
              type="text"
              autoComplete="off"
              autoCapitalize="characters"
              spellCheck={false}
              required
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="XXXX-XXXX-XXXX"
              className="w-full px-[14px] py-[10px] border-[1.5px] border-[#E7E0D8] rounded-[9px] text-[15px] font-mono tracking-[1px] text-[#16120E] bg-[#FDFCFB] outline-none placeholder-[#9A948E] focus:border-[#C8102E] transition-colors"
            />
          </div>
          {error && (
            <div role="alert" className="text-[12px] text-red-700 bg-red-50 border border-red-200 rounded-[9px] px-3 py-2">{error}</div>
          )}
          <button type="submit" disabled={loading}
            className="w-full py-[13px] bg-[#C8102E] hover:bg-[#9E0B24] disabled:opacity-60 text-white text-[14px] font-semibold border-none rounded-[9px] cursor-pointer transition-colors">
            {loading ? 'Please wait...' : 'Continue'}
          </button>
        </form>
        <div className="text-center mt-5 text-[12px] text-[#9A948E]">
          <Link to="/login" className="text-[#9A948E] no-underline hover:text-[#4A4440]">Back to sign in</Link>
        </div>
      </div>
    </div>
  )
}
