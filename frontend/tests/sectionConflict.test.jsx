// @vitest-environment jsdom
/**
 * The optimistic-concurrency contract of an artifact section, from the editor's
 * side. The server rejects a save whose expected version is stale; that only
 * protects anyone if the browser reports the version the draft was STARTED
 * from. Found in a two-browser test: a teammate's save arrived mid-edit, the
 * live section.version moved on, and the stale draft was sent as if current,
 * silently overwriting their work.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { Section } from '../src/pages/CoachWorkspace.jsx'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container, root
beforeEach(() => { container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container) })
afterEach(() => { act(() => root.unmount()); container.remove() })

const base = { key: 'evidence', title: 'Evidence', content: 'v1 text', version: 1,
               updated_by_user_id: 'u-other', updated_at: new Date().toISOString() }

function render(props) {
  act(() => {
    root.render(<Section section={base} isMine={false} editorName="Cleo"
      onExpand={() => {}} onCollapse={() => {}} onSave={() => {}}
      onDismissConflict={() => {}} {...props} />)
  })
}
const button = (label) => [...container.querySelectorAll('button')].find(b => b.textContent.trim().startsWith(label))
const click = (el) => act(() => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
function type(text) {
  const ta = container.querySelector('textarea')
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set
  act(() => { setter.call(ta, text); ta.dispatchEvent(new Event('input', { bubbles: true })) })
}

describe('Section save', () => {
  it('sends the version the edit started from, not the live one', () => {
    const onSave = vi.fn()
    render({ onSave })
    click(button('Evidence'))          // expand
    click(button('Edit'))              // draft starts from v1
    type('v1 text + mine')
    // A teammate saves v2 while we are still typing.
    render({ onSave, section: { ...base, content: 'v1 text + theirs', version: 2 } })
    click(button('Save'))
    expect(onSave).toHaveBeenCalledWith('evidence', 'v1 text + mine', 1)
  })

  it('hands the draft back on a conflict instead of replacing it with theirs', () => {
    const onSave = vi.fn()
    render({ onSave })
    click(button('Evidence'))
    click(button('Edit'))
    type('my draft')
    click(button('Save'))
    // Server: conflict, current is their v2.
    render({ onSave, section: { ...base, content: 'their v2', version: 2 }, conflict: { version: 2 } })
    const ta = container.querySelector('textarea')
    expect(ta, 'editor should reopen after a conflict').not.toBeNull()
    expect(ta.value).toBe('my draft')
    expect(container.textContent).toContain('their v2')   // shown so it can be folded in
    // Retrying now rebases on v2, the version the user has just been shown.
    click(button('Save'))
    expect(onSave).toHaveBeenLastCalledWith('evidence', 'my draft', 2)
  })
})
