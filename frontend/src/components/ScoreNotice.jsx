/* Shown when a turn's scoring failed on our side and is being retried (or
 * could not be completed). Deliberately calm and neutral: this is our problem,
 * not a judgement of the student's prompt, and it must not look like a score. */
export default function ScoreNotice({ message }) {
  if (!message) return null
  return (
    <div role="status"
         className="px-4 py-3 rounded-[12px] bg-[#FEF9EC] border border-[#F5DFA8] text-[12px] text-[#6B5A2E] leading-relaxed"
         style={{ borderWidth: '1.5px' }}>
      {message}
    </div>
  )
}

/* The four frames a delayed score produces, as one reducer so every page
 * treats them the same way:
 *   eval_pending          the turn happened; its score is not known yet
 *   eval_late             the score arrived (show it only if it is the latest turn)
 *   eval_late_suppressed  the score arrived in a feed-off session (count it, show nothing)
 *   eval_rescore_failed   every retry failed */
export function lateScoreAction(data, latestTurn) {
  switch (data.type) {
    case 'eval_pending':
      return { countTurn: true, notice: data.message || null, suppressed: !!data.suppressed }
    case 'eval_late':
      return { scored: true, notice: null, show: data.turn >= latestTurn ? data.data : null }
    case 'eval_late_suppressed':
      return { scored: true, notice: null }
    case 'eval_rescore_failed':
      return { notice: data.message || null }
    default:
      return null
  }
}
