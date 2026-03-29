import { useState } from 'react'
import { Icon, Button, Card, Chip } from '../components/m3'
import { api } from '../lib/api'

const TABS = [
  'Datenschutz',
  'AVV',
  'TOMs',
  'Impressum',
  'AGB',
  'VVT',
  'Verfahrensdoku',
] as const

type Tab = (typeof TABS)[number]

const TAB_CONTENT: Record<Tab, string> = {
  Datenschutz:
    'Datenschutzerklärung gemäß Art. 13, 14 DSGVO. Diese Seite informiert Sie über die Verarbeitung Ihrer personenbezogenen Daten bei der Nutzung unserer Plattform. Verantwortlich für die Datenverarbeitung ist der Betreiber dieser Anwendung.',
  AVV:
    'Auftragsverarbeitungsvertrag gemäß Art. 28 DSGVO. Dieser Vertrag regelt die Rechte und Pflichten der Parteien im Zusammenhang mit der Auftragsverarbeitung personenbezogener Daten.',
  TOMs:
    'Technische und organisatorische Maßnahmen gemäß Art. 32 DSGVO. Beschreibung der implementierten Sicherheitsmaßnahmen zum Schutz personenbezogener Daten.',
  Impressum:
    'Angaben gemäß § 5 TMG. Informationen zum Diensteanbieter, Kontaktdaten und Vertretungsberechtigte.',
  AGB:
    'Allgemeine Geschäftsbedingungen für die Nutzung der Plattform. Es gelten die zum Zeitpunkt des Vertragsabschlusses aktuellen Bedingungen.',
  VVT:
    'Verzeichnis von Verarbeitungstätigkeiten gemäß Art. 30 DSGVO. Übersicht aller Verarbeitungstätigkeiten mit personenbezogenen Daten.',
  Verfahrensdoku:
    'Verfahrensdokumentation gemäß GoBD. Beschreibung der eingesetzten IT-Systeme, Verfahren und internen Kontrollen.',
}

export function LegalPage() {
  const [activeTab, setActiveTab] = useState<Tab>('Datenschutz')
  const [exporting, setExporting] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const handleExport = async () => {
    setExporting(true)
    try {
      const blob = await api.getBlob('/gdpr/export')
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'datenexport.json'
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      /* export may not be available yet */
    } finally {
      setExporting(false)
    }
  }

  const handleDelete = async () => {
    const confirmed = window.confirm(
      'Möchten Sie Ihren Account und alle zugehörigen Daten unwiderruflich löschen? Diese Aktion kann nicht rückgängig gemacht werden.'
    )
    if (!confirmed) return
    setDeleting(true)
    try {
      await api.post('/gdpr/delete', {})
    } catch {
      /* deletion may not be available yet */
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="flex flex-col h-full bg-surface">
      {/* TopBar */}
      <div className="flex items-center gap-3 px-5 py-4 bg-surface-container">
        <Icon name="gavel" size={24} className="text-primary" />
        <h1 className="text-lg font-display font-bold text-on-surface">Rechtliches</h1>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {/* Tab navigation */}
        <div className="flex gap-2 flex-wrap">
          {TABS.map((tab) => (
            <Chip
              key={tab}
              label={tab}
              color={activeTab === tab ? 'primary' : 'default'}
              onClick={() => setActiveTab(tab)}
            />
          ))}
        </div>

        {/* Tab content */}
        <Card variant="outlined">
          <p className="text-sm font-semibold text-on-surface mb-2">{activeTab}</p>
          <p className="text-sm text-on-surface-variant leading-relaxed">
            {TAB_CONTENT[activeTab]}
          </p>
        </Card>

        {/* DSGVO Actions */}
        <div className="space-y-3 pt-4 pb-8">
          <Button
            variant="outlined"
            icon="download"
            onClick={handleExport}
            disabled={exporting}
            className="w-full"
          >
            {exporting ? 'Wird exportiert...' : 'Daten exportieren'}
          </Button>
          <Button
            variant="text"
            icon="delete"
            onClick={handleDelete}
            disabled={deleting}
            className="w-full text-error"
          >
            {deleting ? 'Wird gelöscht...' : 'Account löschen'}
          </Button>
        </div>
      </div>
    </div>
  )
}
