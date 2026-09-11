import { StrictMode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import GroupChat from '../src/pages/GroupChat'
import { bufferKey, bufferedEvents, clearAllReadBuffers } from '../src/lib/readTracking'
import { installFakeWebSocket, FakeWebSocket, resetVisibility } from './helpers'

/**
 * The centre column's tab strip (Team coach | My coach | Artifact), mounted.
 *
 * The tabs are asymmetric on purpose and the assertions have to match:
 *   - team_coach is ALWAYS mounted and merely hidden with display:none
 *     (GroupChat.jsx), so it keeps its socket, scroll position and stream state
 *   - my_coach and artifact are CONDITIONALLY mounted, so switching away
 *     unmounts them
 *
 * A test that asserted "the old pane is gone from the DOM" for all three would
 * be wrong about team_coach, and one that asserted "still in the DOM" for all
 * three would be wrong about the other two.
 */

const SECTIONS = [
  { key: 'problem', title: 'Problem statement', content: 'ALPHA-BODY-TEXT', version: 1 },
]

const SCOPE = { userId: 'u-1', groupSessionId: 'g-1:1' }

function mountGroupChat() {
  return render(
    <StrictMode>
      <MemoryRouter initialEntries={['/groups/g-1/chat?session=1']}>
        <Routes>
          <Route path="/groups/:id/chat" element={<GroupChat />} />
        </Routes>
      </MemoryRouter>
    </StrictMode>,
  )
}

const advance = (ms) => act(() => { vi.advanceTimersByTime(ms) })

/** Open the socket and deliver the artifact state, as the server would. */
function connectWithArtifact(sections = SECTIONS) {
  const ws = FakeWebSocket.last
  act(() => { ws.onopen?.({}) })
  act(() => { ws.receive({ type: 'artifact_state', sections, locks: [] }) })
  return ws
}

const clickTab = (label) => fireEvent.click(screen.getByText(label))
const teamPane = () => screen.getByText("Your team's shared chat")

describe('GroupChat centre-column tabs', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] })
    resetVisibility()
    localStorage.clear()
    clearAllReadBuffers()
    localStorage.setItem('token', 'tok-abc')
    localStorage.setItem('user', JSON.stringify({ user_id: 'u-1', name: 'Ada' }))
    installFakeWebSocket()
    // Sidebar fetches /auth/me, /classrooms/me, the husky score and challenges
    // on mount. None of it matters here; it just must not reject.
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({}) })))
  })

  afterEach(() => {
    vi.useRealTimers()
    resetVisibility()
  })

  it('offers the Artifact tab only once the server sends sections', () => {
    mountGroupChat()
    expect(screen.getByText('Team coach')).toBeInTheDocument()
    expect(screen.getByText('My coach')).toBeInTheDocument()
    expect(screen.queryByText('Artifact')).toBeNull()

    connectWithArtifact()
    expect(screen.getByText('Artifact')).toBeInTheDocument()
  })

  it('defaults to the team coach, with no other pane mounted', () => {
    mountGroupChat()
    connectWithArtifact()

    expect(teamPane()).toBeVisible()
    expect(screen.queryByText('Your private coach')).toBeNull()
    expect(screen.queryByText('Shared Artifact')).toBeNull()
  })

  it('swaps the rendered pane when a tab is clicked', () => {
    mountGroupChat()
    connectWithArtifact()

    clickTab('My coach')
    expect(screen.getByText('Your private coach')).toBeInTheDocument()
    // Mounted but hidden, not unmounted -- this pane keeps its stream state.
    expect(teamPane()).not.toBeVisible()
    expect(screen.queryByText('Shared Artifact')).toBeNull()

    clickTab('Artifact')
    expect(screen.getByText('Shared Artifact')).toBeInTheDocument()
    // Conditionally mounted, so switching away really does remove it.
    expect(screen.queryByText('Your private coach')).toBeNull()
    expect(teamPane()).not.toBeVisible()

    clickTab('Team coach')
    expect(teamPane()).toBeVisible()
    expect(screen.queryByText('Shared Artifact')).toBeNull()
    expect(screen.queryByText('Your private coach')).toBeNull()
  })

  it('renders no section content until the student expands a section', () => {
    mountGroupChat()
    connectWithArtifact()
    clickTab('Artifact')

    expect(screen.getByText('Problem statement')).toBeInTheDocument()
    expect(screen.queryByText('ALPHA-BODY-TEXT')).toBeNull()
  })

  /**
   * Decision 3, end to end through the real tab mechanism rather than a bare
   * unmount: leaving the Artifact tab mid-dwell must bank the time, not bin it.
   */
  it('banks dwell time across a tab switch and resumes on return', () => {
    mountGroupChat()
    const ws = connectWithArtifact()
    clickTab('Artifact')

    fireEvent.click(screen.getByText('Problem statement').closest('button'))
    advance(2000)                                  // 2s of genuine reading

    clickTab('My coach')                           // unmounts ArtifactPanel
    advance(60000)                                 // away; must not accumulate
    expect(ws.sentOfType('section_read')).toHaveLength(0)

    clickTab('Artifact')
    // Returns with the section still open, because the episode was paused.
    expect(screen.getByText('ALPHA-BODY-TEXT')).toBeInTheDocument()

    advance(999)
    expect(ws.sentOfType('section_read')).toHaveLength(0)
    advance(1)                                     // 3s of visible time total
    expect(ws.sentOfType('section_read')).toHaveLength(1)
  })

  it('sends the read event over the group socket with the right surface', () => {
    mountGroupChat()
    const ws = connectWithArtifact()
    clickTab('Artifact')

    fireEvent.click(screen.getByText('Problem statement').closest('button'))
    advance(3000)

    const [event] = ws.sentOfType('section_read')
    expect(event).toMatchObject({
      section_key: 'problem',
      event_type: 'section_expand',
      surface: 'artifact_panel',
    })
    expect(event.event_id).toBeTruthy()
  })

  /**
   * Bug #1, at the level it was actually broken.
   *
   * GroupChat's read_event_ack handler called readTrackerRef.current?.ack(),
   * and readTrackerRef was never assigned -- so the ack was swallowed by the
   * optional chain and the durable buffer grew forever, replaying every read
   * on every reconnect.
   */
  it('applies read_event_ack from the server and prunes the buffer', () => {
    mountGroupChat()
    const ws = connectWithArtifact()
    clickTab('Artifact')

    fireEvent.click(screen.getByText('Problem statement').closest('button'))
    advance(3000)

    const key = bufferKey(SCOPE)
    const [event] = ws.sentOfType('section_read')
    expect(bufferedEvents(key)).toHaveLength(1)

    act(() => { ws.receive({ type: 'read_event_ack', event_id: event.event_id }) })
    expect(bufferedEvents(key)).toHaveLength(0)
  })

  it('applies read_event_rejected too, so a non-qualifying read is not retried forever', () => {
    mountGroupChat()
    const ws = connectWithArtifact()
    clickTab('Artifact')

    fireEvent.click(screen.getByText('Problem statement').closest('button'))
    advance(3000)

    const key = bufferKey(SCOPE)
    const [event] = ws.sentOfType('section_read')

    act(() => { ws.receive({ type: 'read_event_rejected', event_id: event.event_id }) })
    expect(bufferedEvents(key)).toHaveLength(0)
  })

  /**
   * The realistic race: the ack lands a beat after the event, by which time the
   * student may already have switched tabs and unmounted the pane. The ack must
   * still prune, or bug #1 survives in a narrower form.
   */
  it('still applies an ack that arrives after the artifact pane is unmounted', () => {
    mountGroupChat()
    const ws = connectWithArtifact()
    clickTab('Artifact')

    fireEvent.click(screen.getByText('Problem statement').closest('button'))
    advance(3000)
    const [event] = ws.sentOfType('section_read')

    clickTab('Team coach')                         // ArtifactPanel unmounted
    act(() => { ws.receive({ type: 'read_event_ack', event_id: event.event_id }) })

    expect(bufferedEvents(bufferKey(SCOPE))).toHaveLength(0)
  })
})
