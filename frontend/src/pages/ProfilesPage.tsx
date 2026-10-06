import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import {
  createProfile,
  deactivateProfile,
  listProfiles,
  listResumes,
  listTemplates,
  replaceKeywords,
  updateProfile,
} from "../api/catalog"
import { messageOf } from "../api/client"
import { Checkbox, ErrorText, SelectInput, TextArea, TextInput } from "../components/Controls"
import type { Profile } from "../types"

function keywordLines(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
}

function emptyDraft() {
  return {
    name: "",
    priority: "0",
    resumeId: "",
    templateId: "",
    keywords: "",
    active: true,
  }
}

export function ProfilesPage() {
  const queryClient = useQueryClient()
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: listProfiles })
  const resumes = useQuery({ queryKey: ["resumes"], queryFn: listResumes })
  const templates = useQuery({ queryKey: ["templates"], queryFn: listTemplates })
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [draft, setDraft] = useState(emptyDraft)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const appliedKey = useRef("")

  const selected = profiles.data?.items.find((profile) => profile.id === selectedId) ?? null
  const syncKey = selected ? `${selected.id}:${selected.updated_at}:${selected.keywords.join("|")}` : ""

  useEffect(() => {
    if (creating || !selected || appliedKey.current === syncKey) {
      return
    }
    appliedKey.current = syncKey
    setDraft({
      name: selected.name,
      priority: String(selected.priority),
      resumeId: selected.resume_id ?? "",
      templateId: selected.email_template_id ?? "",
      keywords: selected.keywords.join("\n"),
      active: selected.is_active,
    })
    setError(null)
  }, [creating, selected, syncKey])

  function startCreate() {
    appliedKey.current = ""
    setCreating(true)
    setSelectedId(null)
    setDraft(emptyDraft())
    setError(null)
  }

  function selectProfile(profile: Profile) {
    setCreating(false)
    setSelectedId(profile.id)
  }

  async function refresh(id: string | null) {
    await queryClient.invalidateQueries({ queryKey: ["profiles"] })
    setSelectedId(id)
    setCreating(false)
  }

  async function save() {
    const priority = Number(draft.priority)
    if (!Number.isInteger(priority)) {
      setError("Priority must be a whole number")
      return
    }
    setSaving(true)
    setError(null)
    const payload = {
      name: draft.name,
      resume_id: draft.resumeId || null,
      email_template_id: draft.templateId || null,
      priority,
      is_active: draft.active,
    }
    try {
      if (creating) {
        const created = await createProfile({ ...payload, keywords: keywordLines(draft.keywords) })
        await refresh(created.id)
      } else if (selected) {
        await updateProfile(selected.id, payload)
        await replaceKeywords(selected.id, keywordLines(draft.keywords))
        await refresh(selected.id)
      }
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
      await deactivateProfile(selected.id)
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
        <h1 className="text-2xl font-semibold tracking-tight">Profiles</h1>
        <button type="button" className="btn" onClick={startCreate}>
          New profile
        </button>
      </div>
      {profiles.isError ? <ErrorText message={messageOf(profiles.error)} /> : null}
      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <div className="space-y-2">
          {profiles.isLoading ? <p className="text-sm text-stone-500">Loading profiles…</p> : null}
          {profiles.data?.items.map((profile) => (
            <button
              key={profile.id}
              type="button"
              onClick={() => selectProfile(profile)}
              className={`block w-full rounded-md border px-4 py-3 text-left ${
                profile.id === selectedId ? "border-stone-900 bg-white" : "border-stone-200 bg-white/70 hover:bg-white"
              }`}
            >
              <span className="flex items-center justify-between gap-3">
                <span className="font-medium">{profile.name}</span>
                <span className={profile.is_active ? "text-sm text-emerald-800" : "text-sm text-stone-500"}>
                  {profile.is_active ? "Active" : "Inactive"}
                </span>
              </span>
              <span className="mt-1 block truncate text-sm text-stone-500">{profile.keywords.join(", ")}</span>
            </button>
          ))}
          {profiles.data && profiles.data.total > profiles.data.items.length ? (
            <p className="text-sm text-stone-500">
              Showing {profiles.data.items.length} of {profiles.data.total}.
            </p>
          ) : null}
        </div>
        <section className="rounded-md border border-stone-200 bg-white p-5">
          {editing ? (
            <form
              className="space-y-4"
              onSubmit={(event) => {
                event.preventDefault()
                void save()
              }}
            >
              <h2 className="text-lg font-medium">{creating ? "New profile" : draft.name}</h2>
              <TextInput label="Name" value={draft.name} onChange={(name) => setDraft({ ...draft, name })} />
              <TextInput
                label="Priority"
                type="number"
                value={draft.priority}
                onChange={(priority) => setDraft({ ...draft, priority })}
              />
              <SelectInput label="Resume" value={draft.resumeId} onChange={(resumeId) => setDraft({ ...draft, resumeId })}>
                <option value="">None</option>
                {resumes.data?.items.map((resume) => (
                  <option key={resume.id} value={resume.id}>
                    {resume.name}
                    {resume.is_active ? "" : " (inactive)"}
                  </option>
                ))}
              </SelectInput>
              <SelectInput
                label="Template"
                value={draft.templateId}
                onChange={(templateId) => setDraft({ ...draft, templateId })}
              >
                <option value="">None</option>
                {templates.data?.items.map((template) => (
                  <option key={template.id} value={template.id}>
                    {template.name}
                    {template.is_active ? "" : " (inactive)"}
                  </option>
                ))}
              </SelectInput>
              <TextArea
                label="Keywords"
                value={draft.keywords}
                onChange={(keywords) => setDraft({ ...draft, keywords })}
                rows={8}
              />
              <p className="text-sm text-stone-500">One keyword per line. The profile name is kept automatically.</p>
              <Checkbox label="Active" checked={draft.active} onChange={(active) => setDraft({ ...draft, active })} />
              <ErrorText message={error} />
              <div className="flex flex-wrap gap-2">
                <button type="submit" className="btn" disabled={saving}>
                  Save
                </button>
                {selected?.is_active ? (
                  <button type="button" className="btn-ghost" disabled={saving} onClick={() => void deactivate()}>
                    Deactivate
                  </button>
                ) : null}
              </div>
            </form>
          ) : (
            <p className="text-sm text-stone-600">Select a profile to edit it, or create one.</p>
          )}
        </section>
      </div>
    </div>
  )
}
