import { useState, useRef, useEffect } from 'react'

// Small "i" affordance: click/tap to toggle a popover, click outside to close.
// Deliberately not hover-only -- hover has no equivalent on touch devices.
export default function InfoIcon({ text, className = '' }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    function onOutside(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onOutside)
    return () => document.removeEventListener('mousedown', onOutside)
  }, [open])

  if (!text) return null

  return (
    <span ref={ref} className={`relative inline-flex ${className}`}>
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); setOpen(o => !o) }}
        aria-label="More info"
        aria-expanded={open}
        className="w-3.5 h-3.5 rounded-full border border-[#D8D0C6] text-[#9A948E] flex items-center justify-center text-[9px] font-bold leading-none hover:bg-[#F7F3EE] hover:text-[#4A4440] hover:border-[#C8BEB2] transition-colors flex-shrink-0"
        style={{ borderWidth: '1px', textTransform: 'none' }}
      >
        i
      </button>
      {open && (
        <div
          className="absolute z-20 top-5 right-0 w-44 bg-[#FDFCFB] border border-[#E7E0D8] rounded-[10px] p-2 text-[11px] text-[#6B6560] leading-[1.45]"
          style={{
            borderWidth: '1.5px',
            boxShadow: '0 4px 16px rgba(22,18,14,0.12)',
            textTransform: 'none',
            maxWidth: 'calc(100vw - 24px)',
          }}
        >
          {text}
        </div>
      )}
    </span>
  )
}
