import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useState, type FormEvent } from "react"
import { getSheet, listCampaignContacts, listCampaigns, listProfiles, saveHeaderMap, saveSheet, syncSheet, updateCampaignContact } from "../api/catalog"
import { ApiError, messageOf } from "../api/client"
import { ErrorText, TextInput } from "../components/Controls"
import type { SyncSummary } from "../types"

const SAMPLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/demo-sheet/edit"

const MAP_FIELDS = [
  { key: "email", label: "Email", required: true },
  { key: "role", label: "Role", required: true },
  { key: "name", label: "Name", required: false },
  { key: "company", label: "Company", required: false },
  { key: "mobile", label: "Mobile", required: false },
  { key: "location", label: "Location", required: false },
  { key: "linkedin_url", label: "LinkedIn", required: false },
  { key: "job_description", label: "Job description", required: false },
  { key: "notes", label: "Notes", required: false },
] as const

const REVIEW_REASONS: Record<string, string> = {
  needs_review: "No profile match",
  ambiguous: "More than one profile matched",
  missing_resume: "Resume missing",
  missing_template: "Template missing",
  invalid: "Invalid row",
  duplicate_in_sheet: "Duplicate in the sheet",
}

const SUMMARY_ROWS: { key: keyof SyncSummary; label: string }[] = [
  { key: "rows_read", label: "Rows read" },
  { key: "valid", label: "Valid" },
  { key: "needs_review", label: "Needs review" },
  { key: "not_sent", label: "Not sent" },
  { key: "already_sent", label: "Already sent" },
  { key: "skipped_invalid", label: "Skipped, invalid" },
  { key: "skipped_duplicate", label: "Skipped, duplicate" },
]

type MappingRequest = {
  campaignId: string
  headers: string[]
}

export function SheetPage() {
  const queryClient = useQueryClient()
  const sheet = useQuery({
    queryKey: ["sheet"],
    queryFn: async () => {
      try {
        return await getSheet()
      } catch (error) {
        if (error instanceof ApiError && error.code === "not_found") {
          return null
        }
        throw error
      }
    },
  })
  const [url, setUrl] = useState<string | null>(null)
  const [tab, setTab] = useState<string | null>(null)
  const [summary, setSummary] = useState<SyncSummary | null>(null)
  const [syncedId, setSyncedId] = useState<string | null>(null)
  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: listCampaigns })
  const profiles = useQuery({ queryKey: ["profiles", "sheet"], queryFn: listProfiles })
  const campaignId = syncedId ?? campaigns.data?.items[0]?.id ?? null
  const contacts = useQuery({
    queryKey: ["campaign-contacts", campaignId],
    queryFn: () => listCampaignContacts(campaignId ?? ""),
    enabled: campaignId !== null,
  })
  const [mapping, setMapping] = useState<MappingRequest | null>(null)
  const [columns, setColumns] = useState<Record<string, string>>({ email: "", role: "" })
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const urlValue = url ?? sheet.data?.spreadsheet_url ?? ""
  const tabValue = tab ?? sheet.data?.sheet_name ?? ""

  async function sync(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError(null)
    setMapping(null)
    try {
      await saveSheet({ url: urlValue.trim(), sheet_name: tabValue.trim() || null })
      const result = await syncSheet()
      setSummary(result)
      setSyncedId(result.campaign_id)
      await queryClient.invalidateQueries({ queryKey: ["sheet"] })
      await queryClient.invalidateQueries({ queryKey: ["campaigns"] })
      await queryClient.invalidateQueries({ queryKey: ["campaign-contacts", result.campaign_id] })
    } catch (caught) {
      setSummary(null)
      if (caught instanceof ApiError && caught.code === "header_mapping_required") {
        const body = caught.body
        const headers = body && typeof body === "object" && "headers" in body && Array.isArray(body.headers) ? body.headers.map(String) : []
        const campaignId = body && typeof body === "object" && "campaign_id" in body ? String(body.campaign_id) : ""
        setMapping({ campaignId, headers })
        setColumns({ email: "", role: "" })
      }
      setError(messageOf(caught))
    } finally {
      setSaving(false)
    }
  }

  async function submitMapping(event: FormEvent) {
    event.preventDefault()
    if (!mapping) {
      return
    }
    setSaving(true)
    setError(null)
    const payload: Record<string, string> = {}
    for (const field of MAP_FIELDS) {
      const value = columns[field.key]?.trim()
      if (value) {
        payload[field.key] = value
      }
    }
    try {
      const result = await saveHeaderMap(mapping.campaignId, payload)
      setSummary(result)
      setSyncedId(result.campaign_id)
      setMapping(null)
      await queryClient.invalidateQueries({ queryKey: ["sheet"] })
      await queryClient.invalidateQueries({ queryKey: ["campaigns"] })
      await queryClient.invalidateQueries({ queryKey: ["campaign-contacts", result.campaign_id] })
    } catch (caught) {
      setError(messageOf(caught))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">Sheet</h1>
      <p className="mt-2 max-w-2xl text-sm text-stone-600">
        Paste the one spreadsheet link. Sync reads the rows, matches a profile, and opens a draft. It does not send email.
      </p>
      {sheet.isError ? <div className="mt-4"><ErrorText message={messageOf(sheet.error)} /></div> : null}
      <form className="mt-6 space-y-4 rounded-md border border-stone-200 bg-white p-5" onSubmit={(event) => void sync(event)}>
        <TextInput label="Spreadsheet link" value={urlValue} onChange={setUrl} />
        <TextInput label="Tab name" value={tabValue} onChange={setTab} />
        <p className="text-sm text-stone-500">Leave the tab blank to use the first tab.</p>
        <div className="flex flex-wrap gap-2">
          <button type="submit" className="btn" disabled={saving || urlValue.trim() === ""}>
            Sync
          </button>
          <button
            type="button"
            className="btn-ghost"
            onClick={() => {
              setUrl(SAMPLE_SHEET_URL)
              setTab("")
            }}
          >
            Use sample sheet
          </button>
        </div>
        {sheet.data?.last_synced_at ? (
          <p className="text-sm text-stone-500">Last sync {new Date(sheet.data.last_synced_at).toLocaleString()}</p>
        ) : null}
        <ErrorText message={error} />
      </form>
      {mapping ? (
        <form className="mt-6 space-y-4 rounded-md border border-stone-200 bg-white p-5" onSubmit={(event) => void submitMapping(event)}>
          <h2 className="text-lg font-medium">Map columns</h2>
          <p className="text-sm text-stone-600">Choose which columns hold the email address and the role.</p>
          <div className="grid gap-4 sm:grid-cols-2">
            {MAP_FIELDS.map((field) => (
              <label key={field.key} className="block">
                <span className="label">
                  {field.label}
                  {field.required ? "" : " (optional)"}
                </span>
                <select
                  className="field"
                  value={columns[field.key] ?? ""}
                  onChange={(event) => setColumns({ ...columns, [field.key]: event.target.value })}
                  required={field.required}
                >
                  <option value="">Select a column</option>
                  {mapping.headers.map((header) => (
                    <option key={header} value={header}>
                      {header}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
          <button type="submit" className="btn" disabled={saving}>
            Sync mapped columns
          </button>
        </form>
      ) : null}
      {contacts.data && contacts.data.items.length > 0 ? (
        <section className="mt-6 overflow-x-auto rounded-md border border-stone-200 bg-white">
          <table className="w-full min-w-[44rem] text-left text-sm">
            <thead className="border-b border-stone-200 text-stone-500">
              <tr>
                <th className="px-4 py-3 font-medium">Recipient</th>
                <th className="px-4 py-3 font-medium">Role</th>
                <th className="px-4 py-3 font-medium">Profile</th>
                <th className="px-4 py-3 font-medium">Resume</th>
                <th className="px-4 py-3 font-medium">Template</th>
                <th className="px-4 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {contacts.data.items.map((row) => {
                const editable = row.status === "PENDING" || row.status === "NEEDS_REVIEW"
                return (
                  <tr key={row.id} className={row.status === "NEEDS_REVIEW" ? "bg-amber-50" : "border-t border-stone-100"}>
                    <td className="px-4 py-3">{row.email}</td>
                    <td className="px-4 py-3">{row.role || "—"}</td>
                    <td className="px-4 py-3">
                      {editable ? (
                        <select
                          className="field"
                          value={row.profile_id ?? ""}
                          onChange={(event) => {
                            const profileId = event.target.value
                            if (!campaignId || profileId === "") {
                              return
                            }
                            setError(null)
                            void updateCampaignContact(campaignId, row.id, { profile_id: profileId })
                              .then(() => queryClient.invalidateQueries({ queryKey: ["campaign-contacts", campaignId] }))
                              .catch((caught: unknown) => setError(messageOf(caught)))
                          }}
                        >
                          <option value="">Select a profile</option>
                          {(profiles.data?.items ?? [])
                            .filter((profile) => profile.is_active)
                            .map((profile) => (
                              <option key={profile.id} value={profile.id}>
                                {profile.name}
                              </option>
                            ))}
                        </select>
                      ) : (
                        row.profile_name || "—"
                      )}
                    </td>
                    <td className="px-4 py-3">{row.resume_name || "—"}</td>
                    <td className="px-4 py-3">{row.template_name || "—"}</td>
                    <td className="px-4 py-3">
                      <div>{row.status === "NEEDS_REVIEW" ? "Needs review" : row.status === "PENDING" ? "Pending" : row.status}</div>
                      {row.skip_reason ? (
                        <div className="text-stone-500">{REVIEW_REASONS[row.skip_reason] ?? row.skip_reason}</div>
                      ) : null}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </section>
      ) : null}
      {summary ? (
        <section className="mt-6 rounded-md border border-stone-200 bg-white p-5">
          <h2 className="text-lg font-medium">Sync summary</h2>
          <p className="mt-1 text-sm text-stone-600">Draft run. No emails were queued.</p>
          <dl className="mt-4 grid gap-3 sm:grid-cols-2">
            {SUMMARY_ROWS.map((row) => (
              <div key={row.key} className="flex items-baseline justify-between gap-4 border-b border-stone-100 pb-2">
                <dt className="text-sm text-stone-600">{row.label}</dt>
                <dd className="text-sm font-medium">{summary[row.key]}</dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}
    </div>
  )
}
