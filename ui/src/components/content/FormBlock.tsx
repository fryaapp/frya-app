import React from 'react'

interface FormField {
  name: string
  label: string
  type: 'text' | 'email' | 'phone' | 'textarea' | 'number' | 'currency' | 'date' | 'select' | 'line_items'
  placeholder?: string
  required?: boolean
  options?: Array<{ label: string; value: string }>
  default_value?: any
  columns?: Array<{ key: string; label: string; type?: string }>
}

interface FormBlockData {
  title?: string
  form_type?: string
  submit_label?: string
  cancel_label?: string
  fields: FormField[]
}

interface LineItem {
  beschreibung: string
  menge: number
  einzelpreis: number
  mwst: number
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  background: 'var(--frya-surface-container)',
  border: '1px solid var(--frya-outline-variant)',
  borderRadius: 8,
  padding: '8px 10px',
  fontSize: 12,
  fontFamily: 'Plus Jakarta Sans, sans-serif',
  color: 'var(--frya-on-surface)',
  outline: 'none',
  boxSizing: 'border-box',
  transition: 'border-color 0.15s ease',
}

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 11,
  fontWeight: 500,
  color: 'var(--frya-on-surface-variant)',
  fontFamily: 'Plus Jakarta Sans, sans-serif',
  marginBottom: 4,
}

export function FormBlock({
  data,
  onSubmit,
}: {
  data: FormBlockData
  onSubmit?: (formType: string, formData: Record<string, any>) => void
}) {
  const [values, setValues] = React.useState<Record<string, any>>(() => {
    const init: Record<string, any> = {}
    data.fields.forEach((f) => {
      if (f.type === 'line_items') {
        init[f.name] = [{ beschreibung: '', menge: 1, einzelpreis: 0, mwst: 19 }]
      } else {
        init[f.name] = f.default_value ?? ''
      }
    })
    return init
  })

  const [focusedField, setFocusedField] = React.useState<string | null>(null)

  const setValue = (name: string, value: any) => {
    setValues((prev) => ({ ...prev, [name]: value }))
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSubmit?.(data.form_type || 'generic', values)
  }

  return (
    <form
      onSubmit={handleSubmit}
      style={{
        background: 'var(--frya-surface-container-low)',
        borderRadius: 12,
        padding: 14,
      }}
    >
      {data.title && (
        <div
          style={{
            fontSize: 13,
            fontWeight: 700,
            color: 'var(--frya-on-surface)',
            fontFamily: 'Plus Jakarta Sans, sans-serif',
            marginBottom: 12,
          }}
        >
          {data.title}
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {data.fields.map((field) => (
          <div key={field.name}>
            {field.type === 'line_items' ? (
              <LineItemsField
                field={field}
                items={values[field.name] as LineItem[]}
                onChange={(items) => setValue(field.name, items)}
              />
            ) : (
              <>
                <label style={labelStyle}>
                  {field.label}
                  {field.required && (
                    <span style={{ color: 'var(--frya-error)', marginLeft: 2 }}>*</span>
                  )}
                </label>
                {renderField(field, values[field.name], (v) => setValue(field.name, v), focusedField === field.name, () => setFocusedField(field.name), () => setFocusedField(null))}
              </>
            )}
          </div>
        ))}
      </div>

      {/* Buttons */}
      <div style={{ display: 'flex', gap: 8, marginTop: 14, justifyContent: 'flex-end' }}>
        {data.cancel_label && (
          <button
            type="button"
            style={{
              background: 'transparent',
              border: '1px solid var(--frya-outline-variant)',
              borderRadius: 18,
              padding: '6px 14px',
              fontSize: 11,
              fontWeight: 500,
              fontFamily: 'Plus Jakarta Sans, sans-serif',
              color: 'var(--frya-on-surface-variant)',
              cursor: 'pointer',
            }}
          >
            {data.cancel_label}
          </button>
        )}
        <button
          type="submit"
          style={{
            background: 'var(--frya-primary)',
            border: 'none',
            borderRadius: 18,
            padding: '6px 16px',
            fontSize: 11,
            fontWeight: 600,
            fontFamily: 'Plus Jakarta Sans, sans-serif',
            color: 'var(--frya-on-primary)',
            cursor: 'pointer',
          }}
        >
          {data.submit_label || 'Absenden'}
        </button>
      </div>
    </form>
  )
}

function renderField(
  field: FormField,
  value: any,
  onChange: (v: any) => void,
  isFocused: boolean,
  onFocus: () => void,
  onBlur: () => void,
) {
  const focusStyle: React.CSSProperties = isFocused
    ? { borderColor: 'var(--frya-primary)' }
    : {}

  switch (field.type) {
    case 'textarea':
      return (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={onFocus}
          onBlur={onBlur}
          placeholder={field.placeholder}
          rows={3}
          style={{ ...inputStyle, ...focusStyle, resize: 'vertical', minHeight: 60 }}
        />
      )

    case 'select':
      return (
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={onFocus}
          onBlur={onBlur}
          style={{ ...inputStyle, ...focusStyle }}
        >
          <option value="">{field.placeholder || 'Bitte ausw\u00e4hlen...'}</option>
          {field.options?.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      )

    case 'number':
    case 'currency':
      return (
        <input
          type="number"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={onFocus}
          onBlur={onBlur}
          placeholder={field.placeholder}
          step={field.type === 'currency' ? '0.01' : undefined}
          style={{ ...inputStyle, ...focusStyle, fontFamily: 'Outfit, sans-serif' }}
        />
      )

    case 'date':
      return (
        <input
          type="date"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={onFocus}
          onBlur={onBlur}
          style={{ ...inputStyle, ...focusStyle }}
        />
      )

    case 'email':
      return (
        <input
          type="email"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={onFocus}
          onBlur={onBlur}
          placeholder={field.placeholder}
          style={{ ...inputStyle, ...focusStyle }}
        />
      )

    case 'phone':
      return (
        <input
          type="tel"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={onFocus}
          onBlur={onBlur}
          placeholder={field.placeholder}
          style={{ ...inputStyle, ...focusStyle }}
        />
      )

    default:
      return (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={onFocus}
          onBlur={onBlur}
          placeholder={field.placeholder}
          style={{ ...inputStyle, ...focusStyle }}
        />
      )
  }
}

/* ─── Line Items Sub-Component ─── */

function LineItemsField({
  field,
  items,
  onChange,
}: {
  field: FormField
  items: LineItem[]
  onChange: (items: LineItem[]) => void
}) {
  const updateItem = (index: number, key: keyof LineItem, value: any) => {
    const updated = [...items]
    updated[index] = { ...updated[index], [key]: value }
    onChange(updated)
  }

  const addRow = () => {
    onChange([...items, { beschreibung: '', menge: 1, einzelpreis: 0, mwst: 19 }])
  }

  const removeRow = (index: number) => {
    if (items.length > 1) {
      onChange(items.filter((_, i) => i !== index))
    }
  }

  // Calculate totals
  const netto = items.reduce((sum, item) => sum + item.menge * item.einzelpreis, 0)
  const mwstTotal = items.reduce(
    (sum, item) => sum + item.menge * item.einzelpreis * (item.mwst / 100),
    0,
  )
  const brutto = netto + mwstTotal

  const cellInput: React.CSSProperties = {
    ...inputStyle,
    padding: '5px 6px',
    fontSize: 11,
    borderRadius: 6,
  }

  const headerCell: React.CSSProperties = {
    fontSize: 10,
    fontWeight: 600,
    color: 'var(--frya-on-surface-variant)',
    fontFamily: 'Plus Jakarta Sans, sans-serif',
    padding: '0 2px 4px',
  }

  return (
    <div>
      <label style={labelStyle}>{field.label}</label>

      {/* Header */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 60px 80px 60px 28px',
          gap: 4,
          marginBottom: 4,
        }}
      >
        <div style={headerCell}>Beschreibung</div>
        <div style={headerCell}>Menge</div>
        <div style={headerCell}>Einzelpreis</div>
        <div style={headerCell}>MwSt %</div>
        <div />
      </div>

      {/* Rows */}
      {items.map((item, i) => (
        <div
          key={i}
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 60px 80px 60px 28px',
            gap: 4,
            marginBottom: 4,
          }}
        >
          <input
            type="text"
            value={item.beschreibung}
            onChange={(e) => updateItem(i, 'beschreibung', e.target.value)}
            placeholder="Position..."
            style={cellInput}
          />
          <input
            type="number"
            value={item.menge}
            onChange={(e) => updateItem(i, 'menge', Number(e.target.value))}
            min={1}
            style={{ ...cellInput, fontFamily: 'Outfit, sans-serif' }}
          />
          <input
            type="number"
            value={item.einzelpreis}
            onChange={(e) => updateItem(i, 'einzelpreis', Number(e.target.value))}
            step="0.01"
            min={0}
            style={{ ...cellInput, fontFamily: 'Outfit, sans-serif' }}
          />
          <input
            type="number"
            value={item.mwst}
            onChange={(e) => updateItem(i, 'mwst', Number(e.target.value))}
            min={0}
            max={100}
            style={{ ...cellInput, fontFamily: 'Outfit, sans-serif' }}
          />
          <button
            type="button"
            onClick={() => removeRow(i)}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--frya-error)',
              cursor: items.length > 1 ? 'pointer' : 'default',
              fontSize: 14,
              padding: 0,
              opacity: items.length > 1 ? 1 : 0.3,
            }}
            disabled={items.length <= 1}
          >
            &#x2715;
          </button>
        </div>
      ))}

      {/* Add row */}
      <button
        type="button"
        onClick={addRow}
        style={{
          background: 'transparent',
          border: '1px dashed var(--frya-outline-variant)',
          borderRadius: 8,
          padding: '5px 10px',
          fontSize: 11,
          fontFamily: 'Plus Jakarta Sans, sans-serif',
          color: 'var(--frya-primary)',
          cursor: 'pointer',
          width: '100%',
          marginTop: 2,
        }}
      >
        + Position hinzuf\u00fcgen
      </button>

      {/* Totals */}
      <div
        style={{
          marginTop: 10,
          borderTop: '1px solid var(--frya-outline-variant)',
          paddingTop: 8,
          display: 'flex',
          flexDirection: 'column',
          gap: 3,
          alignItems: 'flex-end',
        }}
      >
        {[
          { label: 'Netto', value: netto },
          { label: 'MwSt', value: mwstTotal },
          { label: 'Brutto', value: brutto },
        ].map((row) => (
          <div
            key={row.label}
            style={{
              display: 'flex',
              gap: 12,
              fontSize: row.label === 'Brutto' ? 13 : 11,
              fontFamily: 'Plus Jakarta Sans, sans-serif',
              fontWeight: row.label === 'Brutto' ? 700 : 400,
            }}
          >
            <span style={{ color: 'var(--frya-on-surface-variant)' }}>{row.label}:</span>
            <span
              style={{
                color: 'var(--frya-on-surface)',
                fontFamily: 'Outfit, sans-serif',
                fontWeight: row.label === 'Brutto' ? 700 : 600,
                minWidth: 70,
                textAlign: 'right',
              }}
            >
              {row.value.toLocaleString('de-DE', {
                style: 'currency',
                currency: 'EUR',
              })}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
