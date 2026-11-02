"""Text helpers for the PDFs the app renders with fpdf2: the chat export and
the team submission.

fpdf2 is pure Python with no system dependencies, so it deploys anywhere. Its
core fonts are latin-1 only, so every string goes through pdf_safe first.
"""

import re


def pdf_safe(s: str) -> str:
    """Make text safe for fpdf2 core (latin-1) fonts."""
    if not s:
        return ""
    repl = {
        "‘": "'", "’": "'", "“": '"', "”": '"',
        "–": "-", "—": "-", "…": "...", "•": "-",
        " ": " ", "→": "->", "←": "<-", "✓": "[x]",
    }
    for k, v in repl.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def md_inline_clean(s: str) -> str:
    """Strip inline markdown markers so prose reads cleanly without artifacts."""
    s = re.sub(r"`([^`]*)`", r"\1", s)          # inline code
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)    # bold
    s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", s)  # italic
    s = re.sub(r"__([^_]+)__", r"\1", s)        # underline/bold
    s = re.sub(r"^\s{0,3}#{1,6}\s*", "", s, flags=re.M)  # headings
    return s


def render_message_body(pdf, text: str):
    """Write a message body, rendering fenced code blocks in a monospace box."""
    from fpdf.enums import XPos, YPos

    text = text or ""
    for part in re.split(r"(```.*?```)", text, flags=re.DOTALL):
        if not part:
            continue
        if part.startswith("```"):
            code = re.sub(r"^```[a-zA-Z0-9_+\-]*\n?", "", part)
            code = re.sub(r"```$", "", code).rstrip()
            pdf.set_font("Courier", "", 8.5)
            pdf.set_text_color(40, 40, 40)
            pdf.set_fill_color(244, 244, 246)
            pdf.multi_cell(0, 4.3, pdf_safe(code), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(0.5)
        else:
            clean = md_inline_clean(part).strip("\n")
            if clean.strip():
                pdf.set_font("Helvetica", "", 10)
                pdf.set_text_color(30, 30, 30)
                pdf.multi_cell(0, 5, pdf_safe(clean), new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def pei_rgb(pei):
    if pei is None:
        return (107, 101, 96)
    if pei <= 40:
        return (200, 16, 46)
    if pei <= 65:
        return (249, 115, 22)
    if pei <= 80:
        return (13, 148, 136)
    return (22, 163, 74)


_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")


def render_document_body(pdf, text: str):
    """Write a section of a team's shared document.

    Students write these as light markdown, so headings, bulleted and numbered
    lists and fenced code keep their shape; everything else is a paragraph.
    Blank lines separate paragraphs, single newlines are kept as line breaks."""
    from fpdf.enums import XPos, YPos

    def para(lines: list[str]):
        clean = md_inline_clean("\n".join(lines)).strip("\n")
        if clean.strip():
            pdf.set_font("Helvetica", "", 10.5)
            pdf.set_text_color(30, 30, 30)
            pdf.multi_cell(0, 5.4, pdf_safe(clean), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(1.8)

    for part in re.split(r"(```.*?```)", text or "", flags=re.DOTALL):
        if not part:
            continue
        if part.startswith("```"):
            code = re.sub(r"^```[a-zA-Z0-9_+\-]*\n?", "", part)
            code = re.sub(r"```$", "", code).rstrip()
            pdf.set_font("Courier", "", 9)
            pdf.set_text_color(40, 40, 40)
            pdf.set_fill_color(244, 244, 246)
            pdf.multi_cell(0, 4.5, pdf_safe(code), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(1.8)
            continue

        buf: list[str] = []
        for line in part.split("\n"):
            h, b, n = _HEADING.match(line), _BULLET.match(line), _NUMBERED.match(line)
            if not line.strip() or h or b or n:
                para(buf)
                buf = []
            if h:
                pdf.set_font("Helvetica", "B", max(10.5, 14 - len(h.group(1))))
                pdf.set_text_color(22, 18, 14)
                pdf.multi_cell(0, 6, pdf_safe(md_inline_clean(h.group(2))),
                               new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.ln(0.8)
            elif b or n:
                marker = "-" if b else f"{n.group(1)}."
                item = md_inline_clean(b.group(1) if b else n.group(2))
                pdf.set_font("Helvetica", "", 10.5)
                pdf.set_text_color(30, 30, 30)
                indent = 6
                pdf.set_x(pdf.l_margin + 2)
                pdf.cell(indent, 5.4, marker, new_x=XPos.RIGHT, new_y=YPos.TOP)
                pdf.multi_cell(pdf.epw - indent - 2, 5.4, pdf_safe(item),
                               new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.ln(0.6)
            elif line.strip():
                buf.append(line)
        para(buf)
