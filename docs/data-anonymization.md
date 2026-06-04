# Data anonymization for model training

This note covers how HuskyAI exports conversation data for research / model
training, and what you still need to do by hand to keep it safe. It pairs with
the **Export** tab in the platform admin and the code in
`backend/anonymize.py` + `backend/admin.py`.

## What the export already does

Each export row is **one scored turn**: the student prompt, the assistant
reply, and the PEI scores + sub-metrics. Before any of it leaves the database:

1. **Identity is replaced with stable pseudonyms.** The real user id and
   conversation id are run through HMAC-SHA256 with a secret salt
   (`ANONYMIZE_SALT`) and rendered as `anon-7f3a91` / `conv-997a21`. The same
   student maps to the same label across every export (good for longitudinal
   analysis) but the label can't be reversed back to a person. **No name,
   email, or user id is ever written to the file.**
2. **PII inside the text is scrubbed.** Emails, phone numbers, 9-digit NUIDs,
   SSNs, URLs, and — most reliably — the author's *own* name and email (looked
   up from the DB and matched exactly) are replaced with `[EMAIL]`, `[NAME]`,
   `[ID]`, etc.
3. **Evaluator reasoning is dropped.** The `domain_raw` field contains the
   judge's free-text reasoning that paraphrases the student; the export keeps
   only the clean domain label (`casual`, `coding`, …) and discards the prose.
4. **Timestamps are coarsened** to an ISO week (`2026-W22`) so trends survive
   but the value isn't precise enough to use as a re-identification join key.

## What you must still do by hand

- **Set `ANONYMIZE_SALT`** in the backend `.env` to a long random secret before
  exporting anything you intend to share. Without it the code falls back to a
  known dev salt (and logs a warning), which would let someone brute-force the
  pseudonyms over the small set of user ids. Keep the salt secret and stable —
  changing it re-randomizes every pseudonym.
- **Spot-check a sample.** Regex + known-term scrubbing is best-effort, not a
  guarantee. Free text can still carry PII no pattern will catch: a friend's
  name, a home address, a course/section that narrows things down, a niche
  identifier. Read through a random sample of rows before sharing externally.
- **Get consent first.** Today `consent_research` is `false` for every user and
  nothing sets it. Using identifiable student data to train a model is IRB
  territory at a university — wire a consent checkbox into signup/settings, then
  export with **"only consented students"** turned on. The export already
  supports that filter; it just returns nothing until students opt in.

## If you later need more than regex scrubbing

The current scrubber is deliberately simple and dependency-free. If a manual
spot-check shows too much slipping through, the standard next steps are:

- **Named-entity recognition** (e.g. spaCy or Presidio) to catch arbitrary
  person/location names the regex can't, not just the author's own name.
- **Allow-list review of rare tokens** — surface low-frequency capitalized
  tokens for a human to confirm before release.
- **k-anonymity check on the metadata** — if a (week, domain, classification)
  combination maps to a single student, even pseudonymized rows can be singled
  out; suppress or generalize those.

## Handling and retention

- Treat every export as sensitive until you've reviewed it, even though it's
  pseudonymized — re-identification risk is never exactly zero with free text.
- Store exports in access-controlled locations, not shared drives or repos.
- Delete working copies when the training run is done; keep only what the
  research protocol requires.
