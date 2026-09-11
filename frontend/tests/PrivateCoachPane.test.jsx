import { StrictMode } from 'react'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import PrivateCoachPane from '../src/components/PrivateCoachPane'
import { installFakeWebSocket, FakeWebSocket } from './helpers'

/**
 * The private coach thread must be unreachable from any other identity.
 *
 * The threat is a shared machine: student A uses the private coach, logs out,
 * student B logs in on the same browser. Nothing of A's thread may survive into
 * B's view, and B's socket may not be addressed with A's credentials.
 *
 * These assert the property at the component level, rather than re-reading the
 * fix: each one fails if the state were module level, or if the socket were
 * reused across an identity change, or if the cleanup stopped clearing.
 */

const PROPS = { groupId: 'g-1', sessionNum: 1, token: 'tok-A', roleLabel: null }

function mountPane(overrides = {}) {
  const props = { ...PROPS, ...overrides }
  const utils = render(
    <StrictMode>
      <PrivateCoachPane {...props} />
    </StrictMode>,
  )
  const rerenderWith = (next) =>
    utils.rerender(
      <StrictMode>
        <PrivateCoachPane {...props} {...next} />
      </StrictMode>,
    )
  return { ...utils, rerenderWith }
}

const openSocket = () => act(() => { FakeWebSocket.last.onopen?.({}) })
const deliver = (payload) => act(() => { FakeWebSocket.last.receive(payload) })

describe('PrivateCoachPane isolation', () => {
  beforeEach(() => {
    localStorage.clear()
    installFakeWebSocket()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('authenticates with the token and puts no conversation id in the URL', () => {
    mountPane()
    const { url } = FakeWebSocket.last

    expect(url).toContain('/coach?')
    expect(url).toContain('token=tok-A')
    expect(url).toContain('group_id=g-1')
    expect(url).toContain('session_num=1')
    // The server resolves the conversation from the authenticated user, so
    // there must be nothing here for a student to tamper with.
    expect(url).not.toMatch(/conversation/i)
  })

  it('renders the thread delivered for the current identity', () => {
    mountPane()
    openSocket()
    deliver({ type: 'history', messages: [{ role: 'user', content: 'SECRET-FROM-A' }] })

    expect(screen.getByText('SECRET-FROM-A')).toBeInTheDocument()
  })

  /**
   * The leak this would have caught: if messages lived anywhere shared, or the
   * effect did not clear on an identity change, A's thread would still be on
   * screen after B logs in -- visible to B before any of B's own history lands.
   */
  it('clears the thread the moment the identity changes, before any new history', () => {
    const pane = mountPane({ token: 'tok-A' })
    openSocket()
    deliver({ type: 'history', messages: [{ role: 'user', content: 'SECRET-FROM-A' }] })
    expect(screen.getByText('SECRET-FROM-A')).toBeInTheDocument()

    const socketA = FakeWebSocket.last
    act(() => { pane.rerenderWith({ token: 'tok-B' }) })

    // Gone immediately -- not "gone once the server answers".
    expect(screen.queryByText('SECRET-FROM-A')).toBeNull()
    expect(screen.getByText('This is your own coach.')).toBeInTheDocument()

    // And B is talking over a new socket authenticated as B.
    expect(socketA.closed).toBe(true)
    expect(FakeWebSocket.last).not.toBe(socketA)
    expect(FakeWebSocket.last.url).toContain('token=tok-B')
    expect(FakeWebSocket.last.url).not.toContain('tok-A')
  })

  it('leaves nothing behind for a later mount under a different identity', () => {
    const pane = mountPane({ token: 'tok-A' })
    openSocket()
    deliver({ type: 'history', messages: [{ role: 'assistant', content: 'SECRET-FROM-A' }] })
    act(() => { pane.unmount() })

    mountPane({ token: 'tok-B' })
    expect(screen.queryByText('SECRET-FROM-A')).toBeNull()
  })

  it('resets when the session changes within the same identity', () => {
    const pane = mountPane({ token: 'tok-A', sessionNum: 1 })
    openSocket()
    deliver({ type: 'history', messages: [{ role: 'user', content: 'SESSION-1-ONLY' }] })

    act(() => { pane.rerenderWith({ sessionNum: 2 }) })

    expect(screen.queryByText('SESSION-1-ONLY')).toBeNull()
    expect(FakeWebSocket.last.url).toContain('session_num=2')
  })

  it('discards a streamed partial reply on an identity change', () => {
    const pane = mountPane({ token: 'tok-A' })
    openSocket()
    deliver({ type: 'typing' })
    deliver({ type: 'stream', content: 'HALF-WRITTEN-SECRET' })
    expect(screen.getByText('HALF-WRITTEN-SECRET')).toBeInTheDocument()

    act(() => { pane.rerenderWith({ token: 'tok-B' }) })
    expect(screen.queryByText('HALF-WRITTEN-SECRET')).toBeNull()
  })

  it('sends the student prompt with no identity in the payload', () => {
    mountPane()
    openSocket()

    const box = screen.getByPlaceholderText('Ask your own coach…')
    fireEvent.change(box, { target: { value: 'is my approach sound?' } })
    fireEvent.click(screen.getByText('Send'))

    const [sent] = FakeWebSocket.last.sentOfType('message')
    expect(sent).toEqual({ type: 'message', content: 'is my approach sound?', attachments: [] })
  })

  it('ignores malformed history rows rather than rendering junk', () => {
    mountPane()
    openSocket()
    deliver({
      type: 'history',
      messages: [
        { role: 'user', content: 'GOOD-ROW' },
        { role: 'user' },
        null,
        { content: 'no role' },
      ],
    })

    expect(screen.getByText('GOOD-ROW')).toBeInTheDocument()
    expect(screen.queryByText('no role')).toBeNull()
  })
})
