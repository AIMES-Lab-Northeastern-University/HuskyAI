# Novice Exemplars (PEI 10-35)

Use these as calibration anchors for low-scoring conversations.

---

DOMAIN: coding | PEI: 14 | TURN: 1
USER: "help me make a website"
WHY LOW:
  PSQ=8:  "make" is barely a verb, no tech stack, no purpose, no constraints
  CCM=10: user has no direction, fully open to whatever AI decides
  TSI=5:  zero decomposition — website could mean anything
  CLM=20: single vague request, no incremental thinking
  RAS=12: implied willingness to accept any suggestion
WHAT WOULD IMPROVE IT:
  "Build me a portfolio website using React. It needs a projects section,
   contact form, and must be mobile responsive. I already have the design mockup."

---

DOMAIN: debugging | PEI: 22 | TURN: 1
USER: "my code doesn't work, can you fix it"
WHY LOW:
  PSQ=15: no error message, no language, no code provided
  CCM=8:  user delegates entirely — "can you fix it"
  TSI=10: no attempt to isolate or characterize the problem
  CLM=25: vague single message
  RAS=18: expects AI to diagnose without any information
WHAT WOULD IMPROVE IT:
  "Getting a TypeError: 'NoneType' has no attribute 'split' on line 47.
   The error happens only when the input CSV has an empty row.
   Here's the relevant function: [...]. I tried adding a null check but
   it didn't help. Is the issue in how I'm reading the file?"

---

DOMAIN: casual | PEI: 28 | TURN: 1
USER: "explain machine learning"
WHY LOW:
  PSQ=22: "explain" is a verb but scope is enormous with no constraints
  CCM=15: user passively requests, no direction or focus
  TSI=12: no decomposition of what aspect of ML they care about
  CLM=30: monolithic request for a massive topic
  RAS=25: will likely accept first explanation without probing further
WHAT WOULD IMPROVE IT:
  "Explain how gradient descent works specifically in the context of
   neural networks. I understand basic calculus but have never implemented
   backprop. Focus on the intuition, not the math."
