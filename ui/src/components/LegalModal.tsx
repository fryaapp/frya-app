import { useState } from 'react'

type LegalTab = 'datenschutz' | 'impressum' | 'agb'

interface LegalModalProps {
  open: boolean
  initialTab?: LegalTab
  onClose: () => void
}

const TAB_LABELS: Record<LegalTab, string> = {
  datenschutz: 'Datenschutz',
  impressum: 'Impressum',
  agb: 'AGB',
}

export function LegalModal({ open, initialTab = 'datenschutz', onClose }: LegalModalProps) {
  const [activeTab, setActiveTab] = useState<LegalTab>(initialTab)

  if (!open) return null

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      {/* Backdrop */}
      <div style={{
        position: 'absolute', inset: 0,
        background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)',
      }} />

      {/* Modal */}
      <div style={{
        position: 'relative',
        width: '90%', maxWidth: 560, maxHeight: '80vh',
        background: 'var(--frya-surface-container)',
        borderRadius: 20, overflow: 'hidden',
        display: 'flex', flexDirection: 'column',
        boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
      }}>
        {/* Header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '16px 20px 0', flexShrink: 0,
        }}>
          <span style={{
            fontSize: 16, fontWeight: 700,
            fontFamily: "'Outfit', sans-serif",
            color: 'var(--frya-on-surface)',
          }}>
            Rechtliches
          </span>
          <button
            onClick={onClose}
            aria-label="Schliessen"
            style={{
              width: 32, height: 32, borderRadius: 8,
              border: 'none', background: 'transparent',
              color: 'var(--frya-on-surface-variant)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              cursor: 'pointer',
            }}
          >
            <span className="material-symbols-rounded" style={{ fontSize: 20 }}>close</span>
          </button>
        </div>

        {/* Tabs */}
        <div style={{
          display: 'flex', gap: 4, padding: '12px 20px 0',
          borderBottom: '1px solid var(--frya-outline-variant)',
          flexShrink: 0,
        }}>
          {(Object.keys(TAB_LABELS) as LegalTab[]).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{
                padding: '8px 16px',
                border: 'none',
                background: activeTab === tab ? 'var(--frya-primary-container)' : 'transparent',
                color: activeTab === tab ? 'var(--frya-on-primary-container)' : 'var(--frya-on-surface-variant)',
                borderRadius: '12px 12px 0 0',
                fontSize: 13, fontWeight: activeTab === tab ? 600 : 400,
                fontFamily: "'Plus Jakarta Sans', sans-serif",
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
            >
              {TAB_LABELS[tab]}
            </button>
          ))}
        </div>

        {/* Content */}
        <div style={{
          flex: 1, overflowY: 'auto', padding: '20px',
          fontSize: 13, lineHeight: 1.7,
          color: 'var(--frya-on-surface)',
          fontFamily: "'Plus Jakarta Sans', sans-serif",
        }}>
          {activeTab === 'datenschutz' && <DatenschutzContent />}
          {activeTab === 'impressum' && <ImpressumContent />}
          {activeTab === 'agb' && <AgbContent />}
        </div>
      </div>
    </div>
  )
}

function DatenschutzContent() {
  return (
    <div>
      <h3 style={{ fontSize: 15, fontWeight: 600, marginTop: 0, marginBottom: 12, fontFamily: "'Outfit', sans-serif" }}>
        Datenschutzerkl\u00e4rung
      </h3>
      <p style={{ color: 'var(--frya-on-surface-variant)' }}>
        Die Datenschutzerkl\u00e4rung wird aktuell erstellt.
        Bei Fragen wende dich an{' '}
        <span style={{ color: 'var(--frya-primary)' }}>datenschutz@myfrya.de</span>.
      </p>
      <p style={{ color: 'var(--frya-on-surface-variant)', marginTop: 16 }}>
        FRYA verarbeitet deine Daten ausschlie\u00dflich zur Bereitstellung der Buchhaltungs-
        und Rechnungsfunktionen. Alle Daten werden in der EU gespeichert und verschl\u00fcsselt
        \u00fcbertragen. Eine Weitergabe an Dritte erfolgt nicht ohne deine ausdr\u00fcckliche Zustimmung.
      </p>
    </div>
  )
}

function ImpressumContent() {
  return (
    <div>
      <h3 style={{ fontSize: 15, fontWeight: 600, marginTop: 0, marginBottom: 12, fontFamily: "'Outfit', sans-serif" }}>
        Impressum
      </h3>
      <p style={{ color: 'var(--frya-on-surface-variant)' }}>
        Angaben gem\u00e4\u00df \u00a7 5 TMG:
      </p>
      <div style={{
        background: 'var(--frya-surface)', borderRadius: 12, padding: 16,
        marginTop: 12, marginBottom: 16,
      }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>FRYA — Intelligente Buchhaltung</div>
        <div style={{ color: 'var(--frya-on-surface-variant)', lineHeight: 1.8 }}>
          E-Mail: kontakt@myfrya.de<br />
          Website: myfrya.de
        </div>
      </div>
      <p style={{ fontSize: 12, color: 'var(--frya-on-surface-variant)' }}>
        Verantwortlich f\u00fcr den Inhalt nach \u00a7 55 Abs. 2 RStV:<br />
        Die vollst\u00e4ndigen Impressumsdaten werden nach Gr\u00fcndung der Betreibergesellschaft erg\u00e4nzt.
      </p>
    </div>
  )
}

function AgbContent() {
  return (
    <div>
      <h3 style={{ fontSize: 15, fontWeight: 600, marginTop: 0, marginBottom: 12, fontFamily: "'Outfit', sans-serif" }}>
        Allgemeine Gesch\u00e4ftsbedingungen
      </h3>
      <p style={{ color: 'var(--frya-on-surface-variant)' }}>
        Die AGB werden aktuell erstellt. FRYA befindet sich in der Alpha-Phase.
        Die Nutzung erfolgt auf eigenes Risiko. Eine Haftung f\u00fcr die Richtigkeit
        der KI-generierten Buchhaltungsdaten ist ausgeschlossen.
      </p>
      <p style={{ color: 'var(--frya-on-surface-variant)', marginTop: 16, fontSize: 12 }}>
        Stand: Alpha 0.9 — April 2026
      </p>
    </div>
  )
}

/* Footer bar with legal links — use in GreetingScreen and ChatView */
export function LegalFooter({ onOpen }: { onOpen: (tab: LegalTab) => void }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'center', gap: 16,
      padding: '8px 0',
      fontSize: 11, color: 'var(--frya-on-surface-variant)',
      fontFamily: "'Plus Jakarta Sans', sans-serif",
      opacity: 0.7,
    }}>
      <button onClick={() => onOpen('datenschutz')} style={footerLinkStyle}>Datenschutz</button>
      <span style={{ opacity: 0.4 }}>·</span>
      <button onClick={() => onOpen('impressum')} style={footerLinkStyle}>Impressum</button>
      <span style={{ opacity: 0.4 }}>·</span>
      <button onClick={() => onOpen('agb')} style={footerLinkStyle}>AGB</button>
    </div>
  )
}

const footerLinkStyle: React.CSSProperties = {
  background: 'none', border: 'none', padding: 0,
  color: 'inherit', cursor: 'pointer',
  fontSize: 'inherit', fontFamily: 'inherit',
  textDecoration: 'underline',
  textUnderlineOffset: 2,
}
