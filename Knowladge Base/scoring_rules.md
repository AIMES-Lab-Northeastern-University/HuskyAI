# HuskyAI Scoring Rules and Edge Cases

## Red Flag Trigger Conditions
- RAS < 0.3 across 3 or more consecutive turns = mandatory red flag
- No verification attempts across 5+ code generations = red flag
- Multi-turn degradation > 50% from turn 1 = flag for intervention
- Premature acceptance rate > 40% = over-reliance red flag

## Edge Cases
- Single-turn conversations: score CLM at 50 (neutral), insufficient data
- First message in session: CCM scored at 50, no arc to measure yet
- Debugging domain: weight TSI +10% (problem isolation is core skill)
- Casual domain: weight TSI -10% (no code decomposition expected)
- New student (first session): calibrate suggestions toward building habits, not correcting patterns

## Score Anchors
- PSQ 0-20: vague verb ("help me", "fix this"), no context, no constraints
- PSQ 40-60: has some context, missing constraints or success criteria
- PSQ 80-100: clear verb, full context, explicit constraints, success criteria defined
- CCM 0-20: user fully reactive, accepts all AI direction
- CCM 80-100: user leads, redirects, verifies, challenges assumptions
- RAS 0-20: blindly accepts all AI output, no verification
- RAS 80-100: verifies before accepting, questions incorrect suggestions

## Classification Thresholds
- Novice: PEI < 40
- Intermediate: PEI 40-70
- Advanced: PEI > 70

## PEI Formula
PEI = 0.25 * PSQ + 0.25 * CCM + 0.20 * TSI + 0.15 * CLM + 0.15 * RAS

## PSQ Sub-formula
PSQ = 0.30 * verb_specificity + 0.25 * context_completeness + 0.20 * constraint_defined + 0.15 * focus_clarity + 0.10 * alignment_specified
