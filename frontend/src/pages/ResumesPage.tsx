import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState, type FormEvent } from "react"
import { listProfiles, listResumes, replaceResumeFile, updateResume, uploadResume } from "../api/catalog"
import { messageOf } from "../api/client"
import { Checkbox, ErrorText, TextInput } from "../components/Controls"
import type { Resume } from "../types"

function formatBytes(size: number): string {
  if (size < 1024) {
    return `${size} B`
  }
  return `${(size / 1024).toFixed(size < 1024 * 10 ? 1 : 0)} KB`
}

export function ResumesPage() {
  const queryClient = useQueryClient()
  const resumes = useQuery({ queryKey: ["resumes"], queryFn: listResumes })
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: listProfiles })
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [name, setName] = useState("")
  const [active, setActive] = useState(true)
  const [isDefault, setIsDefault] = useState(false)
  const [profileIds, setProfileIds] = useState<string[]>([])
  const [uploadName, setUploadName] = useState("")
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadDefault, setUploadDefault] = useState(false)
  const [uploadKey, setUploadKey] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const appliedKey = useRef("")

  const selected = resumes.data?.items.find((resume) => resume.id === selectedId) ?? null
  const syncKey = selected
    ? `${selected.id}:${selected.updated_at}:${selected.name}:${selected.profile_ids.join(",")}:${selected.is_default}:${selected.is_active}`
    : ""

  useEffect(() => {
    if (!selected || appliedKey.current === syncKey) {
      return
    }
    appliedKey.current = syncKey
    setName(selected.name)
    setActive(selected.is_active)
    setIsDefault(selected.is_default)
    setProfileIds(selected.profile_ids)
    setError(null)
  }, [selected, syncKey])

  async function refresh(id: string | null) {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["resumes"] }),
      queryClient.invalidateQueries({ queryKey: ["profiles"] }),
    ])
    setSelectedId(id)
  }

  function toggleProfile(id: string) {
    setProfileIds((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]))
  }

  async function upload(event: FormEvent) {
    event.preventDefault()
    if (!uploadFile) {
      setUploadError("Choose a PDF file")
      return
    }
    setSaving(true)
    setUploadError(null)
    try {
      const created = await uploadResume(uploadFile, {
        name: uploadName,
        isActive: true,
        isDefault: uploadDefault,
        profileIds: [],
      })
      setUploadName("")
      setUploadFile(null)
      setUploadDefault(false)
      setUploadKey((current) => current + 1)
      await refresh(created.id)
    } catch (caught) {
      setUploadError(messageOf(caught))
    } finally {
      setSaving(false)
    }
  }

  async function save() {
    if (!selected) {
      return
    }
    setSaving(true)
    setError(null)
    try {
      await updateResume(selected.id, {
        name,
        is_active: active,
        is_default: active ? isDefault : false,
        profile_ids: profileIds,
      })
      await refresh(selected.id)
    } catch (caught) {
      setError(messageOf(caught))
    } finally {
      setSaving(false)
    }
  }

  async function replace(file: File) {
    if (!selected) {
      return
    }
    setSaving(true)
    setError(null)
    try {
      await replaceResumeFile(selected.id, file)
      await refresh(selected.id)
    } catch (caught) {
      setError(messageOf(caught))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">Resumes</h1>
      <form className="mt-6 space-y-4 rounded-md border border-stone-200 bg-white p-5" onSubmit={(event) => void upload(event)}>
        <h2 className="text-lg font-medium">Upload PDF</h2>
        <TextInput label="Name" value={uploadName} onChange={setUploadName} />
        <label className="block">
          <span className="label">PDF file</span>
          <input
            key={uploadKey}
            className="block text-sm"
            type="file"
            accept="application/pdf,.pdf"
            onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <Checkbox label="Default resume" checked={uploadDefault} onChange={setUploadDefault} />
        <ErrorText message={uploadError} />
        <button type="submit" className="btn" disabled={saving}>
          Upload
        </button>
      </form>
      {resumes.isError ? <div className="mt-4"><ErrorText message={messageOf(resumes.error)} /></div> : null}
      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <div className="space-y-2">
          {resumes.isLoading ? <p className="text-sm text-stone-500">Loading resumes…</p> : null}
          {resumes.data?.items.length === 0 ? <p className="text-sm text-stone-600">Upload a PDF to add a resume.</p> : null}
          {resumes.data?.items.map((resume) => (
            <button
              key={resume.id}
              type="button"
              onClick={() => setSelectedId(resume.id)}
              className={`block w-full rounded-md border px-4 py-3 text-left ${
                resume.id === selectedId ? "border-stone-900 bg-white" : "border-stone-200 bg-white/70 hover:bg-white"
              }`}
            >
              <span className="flex items-center justify-between gap-3">
                <span className="font-medium">{resume.name}</span>
                <ResumeMarks resume={resume} />
              </span>
              <span className="mt-1 block text-sm text-stone-500">
                {resume.original_filename} · {formatBytes(resume.size_bytes)}
              </span>
            </button>
          ))}
        </div>
        <section className="rounded-md border border-stone-200 bg-white p-5">
          {selected ? (
            <form
              className="space-y-4"
              onSubmit={(event) => {
                event.preventDefault()
                void save()
              }}
            >
              <h2 className="text-lg font-medium">{selected.name}</h2>
              <TextInput label="Name" value={name} onChange={setName} />
              <p className="text-sm text-stone-500">
                File {selected.original_filename} · {formatBytes(selected.size_bytes)}
              </p>
              <a className="text-sm text-stone-800 underline" href={`/api/v1/resumes/${selected.id}/file`}>
                Download PDF
              </a>
              <label className="block">
                <span className="label">Replace file</span>
                <input
                  className="block text-sm"
                  type="file"
                  accept="application/pdf,.pdf"
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (file) {
                      void replace(file)
                    }
                    event.target.value = ""
                  }}
                />
              </label>
              <Checkbox
                label="Active"
                checked={active}
                onChange={(next) => {
                  setActive(next)
                  if (!next) {
                    setIsDefault(false)
                  }
                }}
              />
              <Checkbox label="Default" checked={isDefault} disabled={!active} onChange={setIsDefault} />
              <fieldset>
                <legend className="label">Assigned profiles</legend>
                <div className="space-y-2">
                  {profiles.data?.items.map((profile) => (
                    <Checkbox
                      key={profile.id}
                      label={profile.name}
                      checked={profileIds.includes(profile.id)}
                      onChange={() => toggleProfile(profile.id)}
                    />
                  ))}
                </div>
              </fieldset>
              <ErrorText message={error} />
              <button type="submit" className="btn" disabled={saving}>
                Save
              </button>
            </form>
          ) : (
            <p className="text-sm text-stone-600">Select a resume to rename it, assign profiles, or replace the file.</p>
          )}
        </section>
      </div>
    </div>
  )
}

function ResumeMarks({ resume }: { resume: Resume }) {
  return (
    <span className="flex gap-2 text-sm">
      {resume.is_default ? <span className="text-stone-700">Default</span> : null}
      <span className={resume.is_active ? "text-emerald-800" : "text-stone-500"}>
        {resume.is_active ? "Active" : "Inactive"}
      </span>
    </span>
  )
}
