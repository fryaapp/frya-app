import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Card, Icon } from '../components/m3'
import { useTheme } from '../hooks/useTheme'
import { api } from '../lib/api'

type Theme = 'light' | 'dark' | 'system'
type Formality = 'du' | 'sie'

const TOTAL_STEPS = 3

const themeOptions: { value: Theme; label: string; icon: string }[] = [
  { value: 'light', label: 'Hell', icon: 'light_mode' },
  { value: 'dark', label: 'Dunkel', icon: 'dark_mode' },
  { value: 'system', label: 'System', icon: 'contrast' },
]

const formalityOptions: { value: Formality; label: string; description: string }[] = [
  { value: 'du', label: 'Du', description: 'Lockerer, freundlicher Ton' },
  { value: 'sie', label: 'Sie', description: 'Formeller, respektvoller Ton' },
]

function StepDots({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex gap-2 justify-center">
      {Array.from({ length: total }, (_, i) => (
        <div
          key={i}
          className={`w-2.5 h-2.5 rounded-full transition-colors duration-300 ${
            i === current ? 'bg-primary' : 'bg-outline-variant'
          }`}
        />
      ))}
    </div>
  )
}

function FryaAvatar() {
  return (
    <div className="w-20 h-20 rounded-full bg-primary-container flex items-center justify-center shadow-lg">
      <span className="text-3xl font-display font-bold text-on-primary-container">F</span>
    </div>
  )
}

export function OnboardingPage() {
  const navigate = useNavigate()
  const { theme, setTheme } = useTheme()
  const [step, setStep] = useState(0)
  const [formality, setFormality] = useState<Formality>('du')
  const [disclaimerAccepted, setDisclaimerAccepted] = useState(false)
  const [saving, setSaving] = useState(false)

  const handleFinish = useCallback(async () => {
    setSaving(true)
    try {
      await Promise.all([
        api.put('/preferences/theme', { value: theme }),
        api.put('/preferences/formality_level', { value: formality }),
      ])
    } catch {
      // Silently continue — settings will sync later
    }
    navigate('/', { replace: true })
  }, [theme, formality, navigate])

  return (
    <div className="fixed inset-0 bg-surface flex flex-col items-center justify-between py-12 px-6 overflow-auto">
      {/* Top: Avatar */}
      <div className="flex flex-col items-center">
        <FryaAvatar />
      </div>

      {/* Center: Step content with transitions */}
      <div className="flex-1 flex items-center justify-center w-full max-w-lg">
        {/* Step 1: Theme */}
        <div
          className={`w-full transition-all duration-300 ${
            step === 0 ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4 absolute pointer-events-none'
          }`}
        >
          {step === 0 && (
            <div className="flex flex-col items-center gap-6">
              <div className="text-center">
                <h1 className="text-2xl font-display font-bold text-on-surface mb-2">
                  Willkommen bei FRYA!
                </h1>
                <p className="text-sm text-on-surface-variant">
                  Wähle dein bevorzugtes Erscheinungsbild.
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 w-full">
                {themeOptions.map((opt) => (
                  <Card
                    key={opt.value}
                    variant="outlined"
                    className={`flex flex-col items-center gap-3 py-6 transition-all duration-200 ${
                      theme === opt.value
                        ? 'border-primary border-2 bg-primary-container/20'
                        : ''
                    }`}
                    onClick={() => setTheme(opt.value)}
                  >
                    <Icon name={opt.icon} size={36} className="text-on-surface" />
                    <span className="text-sm font-semibold text-on-surface">{opt.label}</span>
                  </Card>
                ))}
              </div>

              <Button onClick={() => setStep(1)}>
                Weiter
              </Button>
            </div>
          )}
        </div>

        {/* Step 2: Formality */}
        <div
          className={`w-full transition-all duration-300 ${
            step === 1 ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4 absolute pointer-events-none'
          }`}
        >
          {step === 1 && (
            <div className="flex flex-col items-center gap-6">
              <div className="text-center">
                <h1 className="text-2xl font-display font-bold text-on-surface mb-2">
                  Wie soll ich dich ansprechen?
                </h1>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 w-full max-w-sm">
                {formalityOptions.map((opt) => (
                  <Card
                    key={opt.value}
                    variant="outlined"
                    className={`flex flex-col items-center gap-2 py-8 transition-all duration-200 ${
                      formality === opt.value
                        ? 'border-primary border-2 bg-primary-container/20'
                        : ''
                    }`}
                    onClick={() => setFormality(opt.value)}
                  >
                    <span className="text-2xl font-display font-bold text-on-surface">{opt.label}</span>
                    <span className="text-xs text-on-surface-variant text-center">{opt.description}</span>
                  </Card>
                ))}
              </div>

              <div className="flex gap-3">
                <Button variant="outlined" onClick={() => setStep(0)}>
                  Zurück
                </Button>
                <Button onClick={() => setStep(2)}>
                  Weiter
                </Button>
              </div>
            </div>
          )}
        </div>

        {/* Step 3: AI Disclaimer */}
        <div
          className={`w-full transition-all duration-300 ${
            step === 2 ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4 absolute pointer-events-none'
          }`}
        >
          {step === 2 && (
            <div className="flex flex-col items-center gap-6">
              <div className="text-center">
                <h1 className="text-2xl font-display font-bold text-on-surface mb-2">
                  Bevor es losgeht
                </h1>
              </div>

              <Card variant="outlined" className="w-full">
                <div className="flex flex-col gap-4 py-2">
                  <div className="flex justify-center">
                    <Icon name="smart_toy" size={40} className="text-primary" />
                  </div>
                  <p className="text-sm text-on-surface leading-relaxed">
                    FRYA ist KI-gestützt. Alle Buchungsvorschläge werden automatisch erstellt.
                  </p>
                  <p className="text-sm text-on-surface leading-relaxed">
                    Bitte prüfe jeden Vorschlag sorgfältig, bevor du ihn freigibst.
                  </p>
                  <p className="text-sm text-on-surface leading-relaxed">
                    Du behältst jederzeit die volle Kontrolle über deine Buchhaltung.
                  </p>
                </div>
              </Card>

              <label className="flex items-start gap-3 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={disclaimerAccepted}
                  onChange={(e) => setDisclaimerAccepted(e.target.checked)}
                  className="mt-0.5 w-5 h-5 accent-primary rounded"
                />
                <span className="text-sm text-on-surface leading-snug">
                  Ich habe verstanden, dass FRYA KI-gestützte Vorschläge macht.
                </span>
              </label>

              <div className="flex gap-3">
                <Button variant="outlined" onClick={() => setStep(1)}>
                  Zurück
                </Button>
                <Button
                  disabled={!disclaimerAccepted || saving}
                  onClick={handleFinish}
                >
                  {saving ? 'Wird gespeichert…' : "Los geht's!"}
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Bottom: Stepper dots */}
      <StepDots current={step} total={TOTAL_STEPS} />
    </div>
  )
}
