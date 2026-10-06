import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import {
  createTemplate,
  deactivateTemplate,
  duplicateTemplate,
  listProfiles,
  listTemplates,
  previewTemplate,
  updateTemplate,
} from "../api/catalog"
import { messageOf } from "../api/client"
import { Checkbox, ErrorText, TextArea, TextInput } from "../components/Controls"
import type { PreviewFields, Template, TemplatePreview } from "../types"

const sampleDefaults: PreviewFields = {
  name: "Rahul Sharma",
  company: "Northwind",
  role: "Frontend Engineer",
  location: "Bengaluru",
  mobile: "+91 90000 00000",
  linkedin_url: "https://www.linkedin.com/in/example",
}

function emptyDraft() {
  return {
    name: "",
    subject: "Hello {{name}}",
    body: "Hi {{name}},\n\nI am writing about the {{role}} role at {{company}}.",
    active: true,
    isDefault: false,
    profileIds: [] as string[],
  }
}

export function TemplatesPage() {
  const queryClient = useQueryClient()
  const templates = useQuery({ queryKey: ["templates"], queryFn: listTemplates })
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: listProfiles })
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [draft, setDraft] = useState(emptyDraft)
  const [samples, setSamples] = useState<PreviewFields>(sampleDefaults)
  const [preview, setPreview] = useState<TemplatePreview | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const appliedKey = useRef("")

  const selected = templates.data?.items.find((template) => template.id === selectedId) ?? null
  const syncKey = selected
    ? `${selected.id}:${selected.updated_at}:${selected.subject}:${selected.body}:${selected.profile_ids.join(",")}:${selected.is_default}:${selected.is_active}`
    : ""

  useEffect(() => {
    if (creating || !selected || appliedKey.current === syncKey) {
      return
    }
    appliedKey.current = syncKey
    setDraft({
      name: selected.name,
      subject: selected.subject,
      body: selected.body,
      active: selected.is_active,
      isDefault: selected.is_default,
      profileIds: selected.profile_ids,
    })
    setError(null)
  }, [creating, selected, syncKey])

  useEffect(() => {
    const handle = window.setTimeout(() => {
      void previewTemplate({ subject: draft.subject, body: draft.body, ...samples })
        .then((rendered) => {
          setPreview(rendered)
          setPreviewError(null)
        })
        .catch((caught: unknown) => {
          setPreview(null)
          setPreviewError(messageOf(caught))
        })
    }, 300)
    return () => window.clearTimeout(handle)
  }, [draft.subject, draft.body, samples])

  function startCreate() {
    appliedKey.current = ""
    setCreating(true)
    setSelectedId(null)
    setDraft(emptyDraft())
    setError(null)
  }

  function selectTemplate(template: Template) {
    setCreating(false)
    setSelectedId(template.id)
  }

  function toggleProfile(id: string) {
    setDraft((current) => ({
      ...current,
      profileIds: current.profileIds.includes(id)
        ? current.profileIds.filter((item) => item !== id)
        : [...current.profileIds, id],
    }))
  }

  async function refresh(id: string | null) {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["templates"] }),
      queryClient.invalidateQueries({ queryKey: ["profiles"] }),
    ])
    setSelectedId(id)
    setCreating(false)
  }

  async function save() {
    setSaving(true)
    setError(null)
    const payload = {
      name: draft.name,
      subject: draft.subject,
      body: draft.body,
      is_active: draft.active,
      is_default: draft.active ? draft.isDefault : false,
      profile_ids: draft.profileIds,
    }
    try {
      if (creating) {
        const created = await createTemplate(payload)
        await refresh(created.id)
      } else if (selected) {
        await updateTemplate(selected.id, payload)
        await refresh(selected.id)
      }
    } catch (caught) {
      setError(messageOf(caught))
    } finally {
      setSaving(false)
    }
  }

  async function duplicate() {
    if (!selected) {
      return
    }
    setSaving(true)
    setError(null)
    try {
      const copy = await duplicateTemplate(selected.id)
      await refresh(copy.id)
    } catch (caught) {
      setError(messageOf(caught))
    } finally {
      setSaving(false)
    }
  }

  async function deactivate() {
    if (!selected) {
      return
    }
    setSaving(true)
    setError(null)
    try {
      await deactivateTemplate(selected.id)
      await refresh(selected.id)
    } catch (caught) {
      setError(messageOf(caught))
    } finally {
      setSaving(false)
    }
  }

  const editing = creating || selected !== null

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Email templates</h1>
        <button type="button" className="btn" onClick={startCreate}>
          New template
        </button>
      </div>
      {templates.isError ? <div className="mt-4"><ErrorText message={messageOf(templates.error)} /></div> : null}
      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
        <div className="space-y-2">
          {templates.isLoading ? <p className="text-sm text-stone-500">Loading templates…</p> : null}
          {templates.data?.items.length === 0 ? (
            <p className="text-sm text-stone-600">Create a template to use when a profile matches.</p>
          ) : null}
          {templates.data?.items.map((template) => (
            <button
              key={template.id}
              type="button"
              onClick={() => selectTemplate(template)}
              className={`block w-full rounded-md border px-4 py-3 text-left ${
                template.id === selectedId ? "border-stone-900 bg-white" : "border-stone-200 bg-white/70 hover:bg-white"
              }`}
            >
              <span className="flex items-center justify-between gap-3">
                <span className="font-medium">{template.name}</span>
                <span className="flex gap-2 text-sm">
                  {template.is_default ? <span className="text-stone-700">Default</span> : null}
                  <span className={template.is_active ? "text-emerald-800" : "text-stone-500"}>
                    {template.is_active ? "Active" : "Inactive"}
                  </span>
                </span>
              </span>
              <span className="mt-1 block truncate text-sm text-stone-500">{template.subject}</span>
            </button>
          ))}
        </div>
        {editing ? (
          <form
            className="space-y-4 rounded-md border border-stone-200 bg-white p-5"
            onSubmit={(event) => {
              event.preventDefault()
              void save()
            }}
          >
            <h2 className="text-lg font-medium">{creating ? "New template" : draft.name}</h2>
            <TextInput label="Name" value={draft.name} onChange={(name) => setDraft({ ...draft, name })} />
            <TextInput label="Subject" value={draft.subject} onChange={(subject) => setDraft({ ...draft, subject })} />
            <TextArea label="Body" value={draft.body} onChange={(body) => setDraft({ ...draft, body })} rows={8} mono />
            <div className="flex flex-wrap gap-4">
              <Checkbox
                label="Active"
                checked={draft.active}
                onChange={(active) => setDraft({ ...draft, active, isDefault: active ? draft.isDefault : false })}
              />
              <Checkbox
                label="Default"
                checked={draft.isDefault}
                disabled={!draft.active}
                onChange={(isDefault) => setDraft({ ...draft, isDefault })}
              />
            </div>
            <fieldset>
              <legend className="label">Assigned profiles</legend>
              <div className="grid gap-2 sm:grid-cols-2">
                {profiles.data?.items.map((profile) => (
                  <Checkbox
                    key={profile.id}
                    label={profile.name}
                    checked={draft.profileIds.includes(profile.id)}
                    onChange={() => toggleProfile(profile.id)}
                  />
                ))}
              </div>
            </fieldset>
            <ErrorText message={error} />
            <div className="flex flex-wrap gap-2">
              <button type="submit" className="btn" disabled={saving}>
                Save
              </button>
              {selected ? (
                <button type="button" className="btn-ghost" disabled={saving} onClick={() => void duplicate()}>
                  Duplicate
                </button>
              ) : null}
              {selected?.is_active ? (
                <button type="button" className="btn-ghost" disabled={saving} onClick={() => void deactivate()}>
                  Deactivate
                </button>
              ) : null}
            </div>
            <div className="border-t border-stone-200 pt-4">
              <h3 className="text-sm font-medium text-stone-700">Sample values</h3>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <TextInput label="Name" value={samples.name} onChange={(name) => setSamples({ ...samples, name })} />
                <TextInput
                  label="Company"
                  value={samples.company}
                  onChange={(company) => setSamples({ ...samples, company })}
                />
                <TextInput label="Role" value={samples.role} onChange={(role) => setSamples({ ...samples, role })} />
                <TextInput
                  label="Location"
                  value={samples.location}
                  onChange={(location) => setSamples({ ...samples, location })}
                />
                <TextInput label="Mobile" value={samples.mobile} onChange={(mobile) => setSamples({ ...samples, mobile })} />
                <TextInput
                  label="LinkedIn"
                  value={samples.linkedin_url}
                  onChange={(linkedin_url) => setSamples({ ...samples, linkedin_url })}
                />
              </div>
              <div className="mt-4 rounded-md bg-stone-50 p-4">
                <p className="text-sm text-stone-500">Preview</p>
                {previewError ? <ErrorText message={previewError} /> : null}
                {preview ? (
                  <div className="mt-2 space-y-2">
                    <p className="font-medium">{preview.subject}</p>
                    <p className="whitespace-pre-wrap text-sm">{preview.body}</p>
                    {preview.empty_variables.length > 0 ? (
                      <p className="text-sm text-amber-800">Empty: {preview.empty_variables.join(", ")}</p>
                    ) : null}
                    {preview.unknown_tokens.length > 0 ? (
                      <p className="text-sm text-amber-800">
                        Unknown tokens left unchanged: {preview.unknown_tokens.join(", ")}
                      </p>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </div>
          </form>
        ) : (
          <section className="rounded-md border border-stone-200 bg-white p-5">
            <p className="text-sm text-stone-600">Select a template to edit it, or create one.</p>
          </section>
        )}
      </div>
    </div>
  )
}
