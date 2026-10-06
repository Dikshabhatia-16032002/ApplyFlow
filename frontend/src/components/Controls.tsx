import type { ReactNode } from "react"

export function ErrorText({ message }: { message: string | null }) {
  if (!message) {
    return null
  }
  return <p className="text-sm text-rose-800">{message}</p>
}

export function TextInput({
  label,
  value,
  onChange,
  type = "text",
}: {
  label: string
  value: string
  onChange: (value: string) => void
  type?: string
}) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      <input className="field" type={type} value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  )
}

export function TextArea({
  label,
  value,
  onChange,
  rows = 6,
  mono = false,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  rows?: number
  mono?: boolean
}) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      <textarea
        className={`field ${mono ? "font-mono" : ""}`}
        rows={rows}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  )
}

export function SelectInput({
  label,
  value,
  onChange,
  children,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  children: ReactNode
}) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      <select className="field" value={value} onChange={(event) => onChange(event.target.value)}>
        {children}
      </select>
    </label>
  )
}

export function Checkbox({
  label,
  checked,
  onChange,
  disabled = false,
}: {
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
}) {
  return (
    <label className="flex items-center gap-2 text-sm text-stone-800">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      {label}
    </label>
  )
}
