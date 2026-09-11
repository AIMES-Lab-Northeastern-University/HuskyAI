"""Coverage guard: every UI surface that can show a teammate's section content
must emit read events.

This is the requirement that stops a future display surface -- a review view, a
printable export, an instructor preview -- from silently going unlogged. It is a
static check over the frontend source rather than a runtime assertion, because
the failure it guards against is "somebody added a new component", which no
runtime test would ever exercise.

The rule: any frontend file that renders section content must also reference the
read-tracking hook. Exemptions must be listed explicitly below with a reason, so
skipping the rule is a visible decision rather than an omission.

Proof that it bites: temporarily delete the useSectionReadTracking call from
ArtifactPanel.jsx and this test fails. That was verified, not assumed.
"""

import re
from pathlib import Path

import pytest

FRONTEND_SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"

# The marker a surface must use to be considered instrumented.
TRACKING_HOOK = "useSectionReadTracking"

# Signals that a file renders ARTIFACT section content to a human.
#
# Deliberately narrow. This codebase overloads the word "section": a classroom
# section (a class) is unrelated to an artifact section, and matching on
# `sections.map(` alone flagged Admin.jsx and Instructor.jsx, which only render
# class names in a dropdown. A rule that cries wolf gets switched off, so the
# signal is "reads the .content field off a section-shaped thing", or "handles
# one of the artifact websocket payloads that carry content".
# Direct display: the file reads the .content field off a section and can put it
# in front of a student. A file matching this may NEVER be exempted.
DIRECT_RENDER_PATTERNS = [
    re.compile(r"\bsec(?:tion)?\w*\s*\.\s*content\b"),   # sec.content, sectionRow.content
]

# Indirect: the file handles an artifact payload that carries content. That covers
# real display surfaces AND pure state containers that route the data to one
# (GroupChat.jsx holds artifact state and hands it to ArtifactPanel). Those may be
# exempted -- but only if they do not ALSO match DIRECT_RENDER_PATTERNS, which is
# what stops an exemption from quietly hiding an actual display surface.
PAYLOAD_HANDLER_PATTERNS = [
    re.compile(r"\bartifact_state\b"),
    re.compile(r"\bsection_updated\b"),
]

CONTENT_RENDER_PATTERNS = DIRECT_RENDER_PATTERNS + PAYLOAD_HANDLER_PATTERNS

# Files that match the heuristic but genuinely do not display section content to
# a student. Each needs a reason; an empty reason fails the test.
EXEMPT: dict[str, str] = {
    "lib/readTracking.js": "the tracker itself; instruments others, displays nothing",
    "pages/GroupChat.jsx": (
        "state container only -- holds artifact state from the websocket and "
        "passes it to ArtifactPanel, which is instrumented. Renders no section "
        "content itself; the assertion below enforces that."
    ),
}


def _frontend_files() -> list[Path]:
    if not FRONTEND_SRC.exists():
        pytest.skip(f"frontend source not found at {FRONTEND_SRC}")
    out: list[Path] = []
    for p in FRONTEND_SRC.rglob("*"):
        if p.suffix not in (".jsx", ".js"):
            continue
        if "node_modules" in p.parts or "dist" in p.parts:
            continue
        out.append(p)
    return out


# A mention is not a call. The first version of this check looked for the hook
# name anywhere in the file, and ArtifactPanel.jsx's own docstring says "must use
# useSectionReadTracking" -- so deleting the actual call still passed. The guard
# has to require an invocation, in code, with comments stripped.
TRACKING_CALL = re.compile(rf"\b{TRACKING_HOOK}\s*\(")

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"(?<!:)//[^\n]*")


def strip_comments(text: str) -> str:
    """Remove JS comments so neither the content check nor the hook check can be
    satisfied by prose. The `(?<!:)` keeps URLs like https:// intact."""
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


def _renders_directly(text: str) -> bool:
    """Reads .content off a section, i.e. can actually show it to a student."""
    return any(pat.search(strip_comments(text)) for pat in DIRECT_RENDER_PATTERNS)


def _renders_section_content(text: str) -> bool:
    return any(pat.search(strip_comments(text)) for pat in CONTENT_RENDER_PATTERNS)


def _is_instrumented(text: str) -> bool:
    return bool(TRACKING_CALL.search(strip_comments(text)))


def test_every_section_display_surface_emits_read_events():
    offenders: list[str] = []
    checked = 0

    for path in _frontend_files():
        rel = path.relative_to(FRONTEND_SRC).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if not _renders_section_content(text):
            continue
        checked += 1
        if rel in EXEMPT:
            assert EXEMPT[rel].strip(), f"{rel} is exempted without a reason"
            # An exemption may never cover a file that actually renders section
            # content, or the list becomes a way to opt out of read logging.
            assert not _renders_directly(text), (
                f"{rel} is on the exempt list but reads section .content directly. "
                "Exemptions are only for files that route the payload without "
                "displaying it. Instrument it instead of exempting it."
            )
            continue
        if not _is_instrumented(text):
            offenders.append(rel)

    assert checked > 0, (
        "No frontend file appears to render section content. Either the artifact "
        "UI was removed or the detection patterns have gone stale -- either way "
        "this guard is no longer protecting anything, which is itself a failure."
    )
    assert not offenders, (
        "These files can display a teammate's section content but do not use "
        f"{TRACKING_HOOK}, so engaging with a section there would go unlogged:\n  "
        + "\n  ".join(offenders)
        + f"\n\nAdd {TRACKING_HOOK} to the surface, or add an explicit entry to "
          "EXEMPT in this test with a reason."
    )


def test_the_guard_itself_detects_an_uninstrumented_surface():
    """Prove the rule has teeth against a hypothetical new surface.

    Rather than trusting that the check would catch a future component, run the
    same rule over a synthetic file that displays section content without the
    hook, and assert it is flagged.
    """
    hypothetical = """
    export default function TeammateReviewView({ sections }) {
      return sections.map(sec => <div key={sec.key}>{sec.content}</div>)
    }
    """
    assert _renders_section_content(hypothetical), (
        "the detector failed to recognise a component that plainly renders "
        "section content -- the guard would not catch a real new surface"
    )
    assert not _is_instrumented(hypothetical)  # and so it would be reported


def test_a_comment_mentioning_the_hook_is_not_enough():
    """Regression: mentioning the hook in prose must not satisfy the rule.

    The first version of this guard checked for the hook name anywhere in the
    file. ArtifactPanel.jsx's own docstring names it, so deleting the real call
    still passed -- the guard was toothless. Verified by deleting the call and
    watching this go red.
    """
    only_a_mention = '''
    /** This component must use useSectionReadTracking. */
    export default function Thing({ sections }) {
      return sections.map(sec => <div>{sec.content}</div>)
    }
    '''
    assert _renders_section_content(only_a_mention)
    assert not _is_instrumented(only_a_mention), (
        "a comment mentioning the hook satisfied the check -- the guard would "
        "not catch a surface that merely talks about read tracking"
    )

    real_call = '''
    export default function Thing({ sections, send }) {
      const tracker = useSectionReadTracking({ send, surface: 'x' })
      return sections.map(sec => <div>{sec.content}</div>)
    }
    '''
    assert _is_instrumented(real_call)


def test_detector_does_not_flag_unrelated_files():
    """Guard against the rule being so broad it becomes noise."""
    unrelated = """
    export default function Sidebar({ items }) {
      return items.map(i => <div key={i.id}>{i.label}</div>)
    }
    """
    assert not _renders_section_content(unrelated)


def test_detector_does_not_flag_classroom_sections():
    """A 'section' here also means a class. Those must not trip the rule.

    An earlier, broader version of this check flagged Admin.jsx and
    Instructor.jsx, which only render class names in a roster and a dropdown. A
    guard that fires on unrelated files gets disabled, so this pins the
    distinction.
    """
    classroom_roster = """
    {data.sections.map(s => (
      <span key={s.id}>{s.name} · {s.role}</span>
    ))}
    """
    classroom_dropdown = """
    {sections.map(s => (<option key={s.id} value={s.id}>{s.name}</option>))}
    """
    assert not _renders_section_content(classroom_roster)
    assert not _renders_section_content(classroom_dropdown)
