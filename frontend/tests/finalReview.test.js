import { describe, expect, it } from 'vitest'
import { reviewChecks, wordCount } from '../src/components/FinalReview'

describe('final review checklist', () => {
  const guides = { answer: { prompt: 'Pick one', target_words: 100 } }

  it('flags an empty section', () => {
    const [c] = reviewChecks([{ key: 'answer', title: 'Answer', content: '  ' }], guides)
    expect(c.issues[0].level).toBe('error')
  })

  it('flags a section well short of its target, not one close to it', () => {
    const short = reviewChecks([{ key: 'answer', content: 'too short' }], guides)[0]
    expect(short.issues.map(i => i.level)).toEqual(['warn'])
    const close = reviewChecks([{ key: 'answer', content: 'word '.repeat(70) }], guides)[0]
    expect(close.issues).toEqual([])
  })

  it('flags a section written as a conversation between teammates', () => {
    const chat = 'A: we should pick option 1\nB: agreed, adding evidence'
    expect(reviewChecks([{ key: 'x', content: chat }], {})[0].issues).toHaveLength(1)
    const named = 'Ana: I think so\nBen: me too'
    expect(reviewChecks([{ key: 'x', content: named }], {}, ['Ana Lopez', 'Ben Okafor'])[0].issues).toHaveLength(1)
  })

  it('does not mistake labelled prose for a conversation', () => {
    const doc = 'Goal: reduce cost\nRisk: vendor lock-in\nOwner: the team'
    expect(reviewChecks([{ key: 'x', content: doc }], {})[0].issues).toEqual([])
  })

  it('counts words', () => {
    expect(wordCount('  one two\nthree ')).toBe(3)
    expect(wordCount('')).toBe(0)
  })
})
