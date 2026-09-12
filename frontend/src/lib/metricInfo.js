// Single source of truth for the PEI dimension metadata (label/color/description)
// and the overall Husky Score explainer. Previously duplicated across
// Workspace.jsx, GroupChat.jsx, ContributionAnalytics.jsx, and Progress.jsx.
// Descriptions are written for a non-technical reader (any student, not just
// CS majors) -- plain language over jargon, even if slightly longer.
export const DIM_META = {
  PSQ: { label: 'Prompt Quality', color: '#C8102E', description: 'How clear, specific, and well-structured your prompt is' },
  CCM: { label: 'Conversation Control', color: '#F97316', description: 'How well you guide the conversation and check the AI’s work' },
  TSI: { label: 'Tech Sophistication', color: '#0D9488', description: 'How well you break big problems into manageable steps' },
  CLM: { label: 'Cognitive Load', color: '#7C3AED', description: 'How well-paced your requests are, not too much at once' },
  RAS: { label: 'Reliance Calibration', color: '#D97706', description: 'Whether you trust the AI’s answers the right amount' },
}

export const PEI_INFO = {
  description: 'One number that sums up your prompting skill right now.',
  formula: 'PEI = 0.25×PSQ + 0.25×CCM + 0.20×TSI + 0.15×CLM + 0.15×RAS',
}
