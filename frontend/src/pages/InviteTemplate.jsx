import { useEffect, useMemo, useState } from 'react'

const TILE = { borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }

const inputStyle = {
  width: '100%',
  padding: '9px 12px',
  borderRadius: '8px',
  border: '1.5px solid #E7E0D8',
  fontSize: '13px',
  background: '#FDFCFB',
  color: '#16120E',
  fontFamily: 'inherit',
  outline: 'none',
  boxSizing: 'border-box',
}

const labelStyle = {
  fontSize: '11px',
  fontWeight: 700,
  color: '#9A948E',
  textTransform: 'uppercase',
  letterSpacing: '0.06em',
  marginBottom: '6px',
  display: 'block',
}

const btnPrimary = {
  padding: '8px 14px',
  borderRadius: '8px',
  border: 'none',
  background: '#C8102E',
  color: '#fff',
  fontSize: '13px',
  fontWeight: 600,
  cursor: 'pointer',
}

const btnSecondary = {
  padding: '8px 14px',
  borderRadius: '8px',
  border: '1.5px solid #E7E0D8',
  background: 'transparent',
  color: '#4A4440',
  fontSize: '13px',
  fontWeight: 600,
  cursor: 'pointer',
}

const SECTION_LABEL = {
  fontSize: '11px',
  fontWeight: 700,
  color: '#9A948E',
  textTransform: 'uppercase',
  letterSpacing: '0.06em',
  marginBottom: '10px',
}

const EMAIL_HEADER_FONT = "'Instrument Serif', Georgia, 'Times New Roman', serif"
const EMAIL_BODY_FONT = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif"

function escapeHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function safeUrl(raw) {
  const t = (raw || '').trim()
  if (!t) return ''
  return /^(https?:|mailto:)/i.test(t) ? t : ''
}

function buildSubject() {
  return `You're invited to try HuskyAI - a 15 minute AIMES Lab prompt coaching pilot`
}

function buildBodyPlain({
  recipientName,
  senderName,
  senderTitle,
  className,
  joinCode,
  signupUrl,
  feedbackUrl,
  deadline,
  customNote,
}) {
  const greet = recipientName.trim() ? `Hi ${recipientName.trim()},` : 'Hi,'
  const cls = className.trim() || '[ADD CLASS NAME]'
  const code = joinCode.trim() || '[ADD JOIN CODE]'
  const url = signupUrl.trim() || '[ADD SIGNUP URL]'
  const sender = senderName.trim() || '[YOUR NAME]'
  const title = senderTitle.trim()
  const note = customNote.trim()
  const fb = feedbackUrl.trim()
  const by = deadline.trim()

  const lines = []
  lines.push(greet)
  lines.push('')
  lines.push(
    "We're running a pilot of HuskyAI, an AI prompting skills platform we built at Northeastern's AIMES Lab. It scores your prompts as you write them on five research-grounded dimensions, so you can see what makes a prompt work and what doesn't.",
  )
  lines.push('')
  lines.push("It takes about 15 minutes total, and we'd really value your feedback.")
  lines.push('')
  lines.push('THE PILOT · 15 MINUTES')
  lines.push('')
  lines.push(`  1. Sign up at: ${url}`)
  lines.push('')
  lines.push('  2. Join the pilot section')
  lines.push(`       Class name: ${cls}`)
  lines.push(`       Join code:  ${code}`)
  lines.push('       (After signing up, open the Classroom tab and either enter the')
  lines.push('       code or use the section search.)')
  lines.push('')
  lines.push('  3. Have one short Workspace conversation')
  lines.push('       Any 4-5 turn chat about something you are actually working on.')
  lines.push('       The PEI score panel updates after each turn.')
  lines.push('')
  lines.push('  4. Try 2-3 challenges')
  lines.push('       Pick any 2-3 from the Challenges tab. Real, open-ended tasks;')
  lines.push('       your prompting is scored after every turn.')
  lines.push('')
  lines.push('FEEDBACK · 5 MINUTES')
  lines.push('')
  lines.push('  Reply to this email with whatever you are thinking. We are')
  lines.push('  particularly interested in three things:')
  lines.push('')
  lines.push('  1. Overall experience. Was the site usable and easy to navigate?')
  lines.push('     Anything confusing, broken, or missing?')
  lines.push('')
  lines.push('  2. The evaluation agent. Did the PEI scores and suggestions feel')
  lines.push('     accurate and useful? Did the feedback help your next prompt?')
  lines.push('')
  lines.push('  3. Would you use it? For your own work, in a class, or not at all,')
  lines.push('     and what would make it more helpful for you?')
  lines.push('')
  lines.push(fb ? `  Or, here's a 3-minute survey: ${fb}` : `  Or, here's a 3-minute survey: link: .....`)
  lines.push('')
  if (note) {
    lines.push(note)
    lines.push('')
  }
  lines.push(by ? `Thanks a lot. Replies by ${by} would be ideal.` : 'Thanks a lot. Any feedback is appreciated.')
  lines.push('')
  lines.push(sender)
  if (title) lines.push(title)
  return lines.join('\n')
}

function buildBodyHTML(fields) {
  const {
    recipientName,
    senderName,
    senderTitle,
    className,
    joinCode,
    signupUrl,
    feedbackUrl,
    deadline,
    customNote,
  } = fields

  const greet = recipientName.trim() ? `Hi ${escapeHtml(recipientName.trim())},` : 'Hi,'
  const cls = escapeHtml(className.trim() || '[ADD CLASS NAME]')
  const code = escapeHtml(joinCode.trim() || '[ADD JOIN CODE]')
  const urlSafe = safeUrl(signupUrl)
  const urlText = escapeHtml(signupUrl.trim() || '[ADD SIGNUP URL]')
  const sender = escapeHtml(senderName.trim() || '[YOUR NAME]')
  const title = escapeHtml(senderTitle.trim())
  const note = escapeHtml(customNote.trim())
  const fbSafe = safeUrl(feedbackUrl)
  const fbText = escapeHtml(feedbackUrl.trim())
  const by = escapeHtml(deadline.trim())

  const signupLink = urlSafe
    ? `<a href="${escapeHtml(urlSafe)}" style="color:#C8102E;text-decoration:underline;">${urlText}</a>`
    : urlText

  const surveyLine = fbSafe
    ? `<p style="margin:0;font-family:${EMAIL_BODY_FONT};font-size:15px;line-height:1.65;color:#1A1612;">Or, here's a 3-minute survey: <a href="${escapeHtml(fbSafe)}" style="color:#C8102E;text-decoration:underline;font-weight:500;">${fbText}</a></p>`
    : `<p style="margin:0;font-family:${EMAIL_BODY_FONT};font-size:15px;line-height:1.65;color:#1A1612;">Or, here's a 3-minute survey: <span style="color:#9A948E;font-style:italic;">link: .....</span></p>`

  const closing = by
    ? `Thanks a lot. Replies by <span style="font-weight:500;">${by}</span> would be ideal.`
    : `Thanks a lot. Any feedback is appreciated.`

  const stepsIcon = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#C8102E" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;"><path d="m3 17 2 2 4-4"/><path d="m3 7 2 2 4-4"/><path d="M13 6h8"/><path d="M13 12h8"/><path d="M13 18h8"/></svg>`

  const feedbackIcon = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#C8102E" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`

  const eyebrowStyle = `font-family:${EMAIL_BODY_FONT};font-size:11px;font-weight:600;color:#C8102E;letter-spacing:1.2px;text-transform:uppercase;`
  const hairline = `<div style="border-top:1px solid #E7E0D8;line-height:0;font-size:0;">&nbsp;</div>`

  return `<div style="font-family:${EMAIL_BODY_FONT};max-width:640px;margin:0 auto;color:#1A1612;line-height:1.65;background:#FDFCFB;padding:40px 16px;-webkit-font-smoothing:antialiased;">
  <div style="max-width:580px;margin:0 auto;">

    <!-- Header -->
    <div style="padding-bottom:28px;">
      <div style="width:36px;height:3px;background:#C8102E;margin-bottom:16px;border-radius:2px;"></div>
      <div style="font-family:${EMAIL_HEADER_FONT};font-size:26px;font-weight:400;color:#1A1612;line-height:1.1;">HuskyAI</div>
      <div style="font-family:${EMAIL_BODY_FONT};font-size:11px;font-weight:500;color:#9A948E;letter-spacing:1.2px;text-transform:uppercase;margin-top:6px;">AIMES Lab &middot; Northeastern University</div>
    </div>

    ${hairline}

    <!-- Intro -->
    <div style="padding:28px 0;">
      <p style="margin:0 0 16px;font-size:15px;line-height:1.65;">${greet}</p>
      <p style="margin:0 0 16px;font-size:15px;line-height:1.65;">We're running a pilot of <span style="font-weight:500;">HuskyAI</span>, an AI prompting skills platform we built at Northeastern's <span style="font-weight:500;">AIMES Lab</span>. It scores your prompts as you write them on five research-grounded dimensions, so you can see what makes a prompt work and what doesn't.</p>
      <p style="margin:0;font-size:15px;line-height:1.65;">It takes about 15 minutes total, and we'd really value your feedback.</p>
    </div>

    ${hairline}

    <!-- Steps -->
    <div style="padding:28px 0;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:14px;border-collapse:collapse;">
        <tr>
          <td valign="middle" style="padding-right:8px;line-height:0;">${stepsIcon}</td>
          <td valign="middle"><span style="${eyebrowStyle}">The pilot &middot; 15 minutes</span></td>
        </tr>
      </table>
      <ol style="margin:0;padding-left:22px;font-size:15px;line-height:1.7;color:#1A1612;">
        <li style="margin-bottom:12px;">Sign up at ${signupLink}.</li>
        <li style="margin-bottom:12px;">Open the Classroom tab and join the pilot section. Class name: <span style="font-weight:500;">${cls}</span>. Join code: <span style="display:inline-block;font-weight:600;color:#C8102E;letter-spacing:0.5px;background:#FDE8EC;padding:2px 9px;border-radius:5px;font-size:14px;">${code}</span>.</li>
        <li style="margin-bottom:12px;">Have one short Workspace conversation, any 4-5 turn chat about something you're actually working on. The PEI score panel updates after each turn.</li>
        <li style="margin-bottom:0;">Try 2-3 challenges from the Challenges tab.</li>
      </ol>
    </div>

    ${hairline}

    <!-- Feedback -->
    <div style="padding:28px 0;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:14px;border-collapse:collapse;">
        <tr>
          <td valign="middle" style="padding-right:8px;line-height:0;">${feedbackIcon}</td>
          <td valign="middle"><span style="${eyebrowStyle}">Feedback &middot; 5 minutes</span></td>
        </tr>
      </table>
      <p style="margin:0 0 16px;font-size:15px;line-height:1.65;">Reply to this email with whatever you're thinking. We're particularly interested in three things:</p>
      <ol style="margin:0 0 18px;padding-left:22px;font-size:15px;line-height:1.7;color:#1A1612;">
        <li style="margin-bottom:12px;"><span style="font-weight:500;">Overall experience.</span> Was the site usable and easy to navigate? Anything confusing, broken, or missing?</li>
        <li style="margin-bottom:12px;"><span style="font-weight:500;">The evaluation agent.</span> Did the PEI scores and suggestions feel accurate and useful? Did the feedback help your next prompt?</li>
        <li style="margin-bottom:0;"><span style="font-weight:500;">Would you use it?</span> For your own work, in a class, or not at all, and what would make it more helpful for you?</li>
      </ol>
      ${surveyLine}
    </div>

    ${note ? `${hairline}<div style="padding:28px 0;"><p style="margin:0;font-size:15px;line-height:1.65;color:#1A1612;">${note.replace(/\n/g, '<br/>')}</p></div>` : ''}

    ${hairline}

    <!-- Sign-off -->
    <div style="padding-top:28px;">
      <p style="margin:0 0 22px;font-size:15px;line-height:1.65;color:#1A1612;">${closing}</p>
      <div style="font-family:${EMAIL_HEADER_FONT};font-size:19px;font-weight:400;color:#1A1612;">${sender}</div>
      ${title ? `<div style="font-family:${EMAIL_BODY_FONT};font-size:12px;color:#9A948E;margin-top:3px;">${title}</div>` : ''}
    </div>

    <!-- Footer -->
    <div style="margin-top:36px;padding-top:18px;border-top:1px solid #E7E0D8;text-align:center;">
      <div style="font-family:${EMAIL_BODY_FONT};font-size:11px;color:#9A948E;letter-spacing:1px;text-transform:uppercase;font-weight:500;">AIMES Lab &middot; Northeastern University</div>
    </div>

  </div>
</div>`
}

export default function InviteTemplate() {
  const storedUser = useMemo(() => {
    try { return JSON.parse(localStorage.getItem('user') || 'null') } catch { return null }
  }, [])

  const [recipientName, setRecipientName] = useState('')
  const [senderName, setSenderName] = useState(storedUser?.name || '')
  const [senderTitle, setSenderTitle] = useState('AIMES Lab, Northeastern University')
  const [className, setClassName] = useState('HuskyAI Pilot')
  const [joinCode, setJoinCode] = useState('TRYHUSKY')
  const [signupUrl, setSignupUrl] = useState('https://huskyai-production-4c59.up.railway.app/login?tab=register')
  const [feedbackUrl, setFeedbackUrl] = useState('')
  const [deadline, setDeadline] = useState('')
  const [customNote, setCustomNote] = useState('')
  const [previewMode, setPreviewMode] = useState('rich') // 'rich' | 'plain'
  const [copyMsg, setCopyMsg] = useState('')

  useEffect(() => {
    if (!copyMsg) return
    const t = window.setTimeout(() => setCopyMsg(''), 2200)
    return () => window.clearTimeout(t)
  }, [copyMsg])

  const fields = {
    recipientName,
    senderName,
    senderTitle,
    className,
    joinCode,
    signupUrl,
    feedbackUrl,
    deadline,
    customNote,
  }
  const subject = buildSubject()
  const bodyPlain = useMemo(() => buildBodyPlain(fields), [fields])
  const bodyHtml = useMemo(() => buildBodyHTML(fields), [fields])

  const copyPlain = async (text, label) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopyMsg(`${label} copied`)
    } catch {
      setCopyMsg('Copy failed - select the text and copy manually')
    }
  }

  const copyRich = async () => {
    try {
      if (typeof window !== 'undefined' && 'ClipboardItem' in window) {
        const item = new window.ClipboardItem({
          'text/html': new Blob([bodyHtml], { type: 'text/html' }),
          'text/plain': new Blob([bodyPlain], { type: 'text/plain' }),
        })
        await navigator.clipboard.write([item])
        setCopyMsg('Rich email copied - paste into Gmail or Outlook')
      } else {
        await navigator.clipboard.writeText(bodyPlain)
        setCopyMsg('Rich copy unsupported here; plain text copied instead')
      }
    } catch {
      setCopyMsg('Copy failed - your browser may have blocked clipboard access')
    }
  }

  const mailtoHref = useMemo(() => {
    const params = new URLSearchParams()
    params.set('subject', subject)
    params.set('body', bodyPlain)
    return `mailto:?${params.toString().replace(/\+/g, '%20')}`
  }, [subject, bodyPlain])

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 380px) 1fr', gap: '20px', maxWidth: '1180px' }}>

      {/* ── Form ── */}
      <div className="bg-[#FDFCFB] rounded-[14px] p-5" style={TILE}>
        <div style={SECTION_LABEL}>Invitation details</div>

        <div style={{ marginBottom: '14px' }}>
          <label style={labelStyle}>Recipient name (optional)</label>
          <input
            style={inputStyle}
            value={recipientName}
            onChange={e => setRecipientName(e.target.value)}
            placeholder="Alex"
          />
        </div>

        <div style={{ marginBottom: '14px' }}>
          <label style={labelStyle}>Your name</label>
          <input
            style={inputStyle}
            value={senderName}
            onChange={e => setSenderName(e.target.value)}
            placeholder="Your full name"
          />
        </div>

        <div style={{ marginBottom: '14px' }}>
          <label style={labelStyle}>Your title / affiliation</label>
          <input
            style={inputStyle}
            value={senderTitle}
            onChange={e => setSenderTitle(e.target.value)}
            placeholder="AIMES Lab, Northeastern University"
          />
        </div>

        <div style={{ height: '1px', background: '#F0EBE5', margin: '6px 0 14px' }} />

        <div style={{ marginBottom: '14px' }}>
          <label style={labelStyle}>Pilot section name</label>
          <input
            style={inputStyle}
            value={className}
            onChange={e => setClassName(e.target.value)}
            placeholder="HuskyAI Pilot"
          />
        </div>

        <div style={{ marginBottom: '14px' }}>
          <label style={labelStyle}>Class join code</label>
          <input
            style={{ ...inputStyle, letterSpacing: '0.08em', fontWeight: 600 }}
            value={joinCode}
            onChange={e => setJoinCode(e.target.value.toUpperCase())}
            placeholder="TRYHUSKY"
            maxLength={16}
          />
          <div style={{ fontSize: '11px', color: '#9A948E', marginTop: '4px', lineHeight: 1.55 }}>
            Default is the seeded "HuskyAI Pilot" section (every challenge linked). Change if you have a different pilot section.
          </div>
        </div>

        <div style={{ marginBottom: '14px' }}>
          <label style={labelStyle}>Signup URL</label>
          <input
            style={inputStyle}
            value={signupUrl}
            onChange={e => setSignupUrl(e.target.value)}
            placeholder="https://..."
          />
        </div>

        <div style={{ height: '1px', background: '#F0EBE5', margin: '6px 0 14px' }} />

        <div style={{ marginBottom: '14px' }}>
          <label style={labelStyle}>Feedback form URL (optional)</label>
          <input
            style={inputStyle}
            value={feedbackUrl}
            onChange={e => setFeedbackUrl(e.target.value)}
            placeholder="Google Form / Typeform link"
          />
          <div style={{ fontSize: '11px', color: '#9A948E', marginTop: '4px', lineHeight: 1.55 }}>
            If set, the email points recipients here. If blank, the email asks for a reply.
          </div>
        </div>

        <div style={{ marginBottom: '14px' }}>
          <label style={labelStyle}>Reply-by date (optional)</label>
          <input
            style={inputStyle}
            value={deadline}
            onChange={e => setDeadline(e.target.value)}
            placeholder="e.g. Fri May 23"
          />
        </div>

        <div style={{ marginBottom: '6px' }}>
          <label style={labelStyle}>Personal note (optional)</label>
          <textarea
            style={{ ...inputStyle, resize: 'vertical', minHeight: '72px', fontFamily: "'DM Sans', sans-serif" }}
            value={customNote}
            onChange={e => setCustomNote(e.target.value)}
            placeholder="One or two lines, added just before the signoff."
          />
        </div>
      </div>

      {/* ── Preview + actions ── */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>

        <div className="bg-[#FDFCFB] rounded-[14px] p-5" style={TILE}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', gap: '12px', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
              <div style={SECTION_LABEL}>Preview</div>
              <div style={{ display: 'inline-flex', background: '#F7F3EE', padding: '3px', borderRadius: '8px', border: '1px solid #E7E0D8' }}>
                {[
                  { id: 'rich', label: 'Rich' },
                  { id: 'plain', label: 'Plain' },
                ].map(opt => (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => setPreviewMode(opt.id)}
                    style={{
                      padding: '4px 12px',
                      borderRadius: '6px',
                      fontSize: '12px',
                      fontWeight: 600,
                      border: 'none',
                      cursor: 'pointer',
                      background: previewMode === opt.id ? '#FDFCFB' : 'transparent',
                      color: previewMode === opt.id ? '#16120E' : '#6B6560',
                      boxShadow: previewMode === opt.id ? '0 1px 3px rgba(22,18,14,0.06)' : 'none',
                    }}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              <button type="button" style={btnSecondary} onClick={() => copyPlain(subject, 'Subject')}>
                Copy subject
              </button>
              {previewMode === 'rich' ? (
                <button type="button" style={btnPrimary} onClick={copyRich}>
                  Copy rich email
                </button>
              ) : (
                <button type="button" style={btnPrimary} onClick={() => copyPlain(bodyPlain, 'Plain body')}>
                  Copy plain body
                </button>
              )}
              <a href={mailtoHref} style={{ ...btnSecondary, textDecoration: 'none', display: 'inline-block' }}>
                Open in mail app
              </a>
            </div>
          </div>

          {copyMsg && (
            <div style={{
              marginBottom: '12px',
              fontSize: '12px',
              color: copyMsg.includes('failed') || copyMsg.includes('unsupported') ? '#C8102E' : '#15803D',
              fontWeight: 600,
            }}>
              {copyMsg}
            </div>
          )}

          <div style={{
            background: '#F7F3EE',
            border: '1.5px solid #E7E0D8',
            borderRadius: '10px',
            padding: '12px 14px',
            marginBottom: '12px',
          }}>
            <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '4px' }}>
              Subject
            </div>
            <div style={{ fontSize: '14px', fontWeight: 600, color: '#16120E', lineHeight: 1.45 }}>
              {subject}
            </div>
          </div>

          {previewMode === 'rich' ? (
            <div style={{
              background: '#EDEAE4',
              border: '1.5px solid #E7E0D8',
              borderRadius: '10px',
              padding: '0',
              maxHeight: '640px',
              overflowY: 'auto',
            }}>
              <div
                // eslint-disable-next-line react/no-danger
                dangerouslySetInnerHTML={{ __html: bodyHtml }}
              />
            </div>
          ) : (
            <pre style={{
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              fontFamily: "'DM Sans', sans-serif",
              fontSize: '13px',
              color: '#16120E',
              lineHeight: 1.65,
              background: '#FDFCFB',
              border: '1.5px solid #E7E0D8',
              borderRadius: '10px',
              padding: '14px 16px',
              margin: 0,
              maxHeight: '560px',
              overflowY: 'auto',
            }}>
              {bodyPlain}
            </pre>
          )}
        </div>

        <div className="bg-[#FDFCFB] rounded-[14px] p-4" style={TILE}>
          <div style={SECTION_LABEL}>Tips</div>
          <ul style={{ margin: 0, paddingLeft: '18px', color: '#4A4440', fontSize: '12px', lineHeight: 1.7 }}>
            <li>
              <strong style={{ color: '#16120E' }}>Rich</strong> mode copies styled HTML to your clipboard. Paste straight into Gmail compose, Outlook web, or Apple Mail and it keeps the formatting.
            </li>
            <li>
              <strong style={{ color: '#16120E' }}>Plain</strong> mode is for terminals, Slack, or fallback. The mail-app button always opens with the plain version.
            </li>
            <li>
              Default join code is <strong style={{ color: '#16120E' }}>TRYHUSKY</strong> ("HuskyAI Pilot"). Restart the backend once so the seeded pilot section gets all challenges linked.
            </li>
          </ul>
        </div>
      </div>
    </div>
  )
}
