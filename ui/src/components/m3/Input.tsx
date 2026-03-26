interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
}

export function Input({ label, error, className = '', ...props }: InputProps) {
  return (
    <div className={className}>
      {label && <label className="block text-sm font-medium text-on-surface-variant mb-1">{label}</label>}
      <input
        className={`w-full px-4 py-3 bg-surface-container-high text-on-surface rounded-m3-sm border transition-colors focus:outline-none ${
          error ? 'border-error focus:border-error' : 'border-outline-variant focus:border-primary'
        }`}
        {...props}
      />
      {error && <p className="text-error text-xs mt-1">{error}</p>}
    </div>
  )
}
