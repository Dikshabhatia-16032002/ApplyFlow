import { request } from "./client"
import type {
  Campaign,
  CampaignContact,
  Page,
  PreviewFields,
  Profile,
  Resume,
  GoogleStatus,
  SheetConnection,
  SyncSummary,
  Template,
  TemplatePreview,
} from "../types"

export function googleStatus() {
  return request<GoogleStatus>("/auth/google/status")
}

export function startGoogle() {
  return request<{ authorization_url: string }>("/auth/google/start")
}

export function disconnectGoogle() {
  return request<GoogleStatus>("/auth/google/disconnect", { method: "POST" })
}

export function getSheet() {
  return request<SheetConnection>("/sheet")
}

export function saveSheet(body: { url: string; sheet_name: string | null }) {
  return request<SheetConnection>("/sheet", { method: "PUT", body: JSON.stringify(body) })
}

export function syncSheet() {
  return request<SyncSummary>("/sheet/sync", { method: "POST" })
}

export function listCampaigns() {
  return request<Page<Campaign>>("/campaigns?limit=20")
}

export function listCampaignContacts(campaignId: string) {
  return request<Page<CampaignContact>>(`/campaigns/${campaignId}/contacts?limit=200`)
}

export function updateCampaignContact(campaignId: string, rowId: string, body: { profile_id: string }) {
  return request<CampaignContact>(`/campaigns/${campaignId}/contacts/${rowId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  })
}

export function saveHeaderMap(campaignId: string, body: Record<string, string>) {
  return request<SyncSummary>(`/campaigns/${campaignId}/mapping`, { method: "POST", body: JSON.stringify(body) })
}

export function listProfiles() {
  return request<Page<Profile>>("/profiles?limit=200")
}

export function createProfile(body: {
  name: string
  keywords: string[]
  resume_id: string | null
  email_template_id: string | null
  priority: number
  is_active: boolean
}) {
  return request<Profile>("/profiles", { method: "POST", body: JSON.stringify(body) })
}

export function updateProfile(
  id: string,
  body: {
    name: string
    resume_id: string | null
    email_template_id: string | null
    priority: number
    is_active: boolean
  },
) {
  return request<Profile>(`/profiles/${id}`, { method: "PATCH", body: JSON.stringify(body) })
}

export function replaceKeywords(id: string, keywords: string[]) {
  return request<Profile>(`/profiles/${id}/keywords`, {
    method: "PUT",
    body: JSON.stringify({ keywords }),
  })
}

export function deactivateProfile(id: string) {
  return request<Profile>(`/profiles/${id}`, { method: "DELETE" })
}

export function listResumes() {
  return request<Page<Resume>>("/resumes?limit=200")
}

export function uploadResume(file: File, fields: { name: string; isActive: boolean; isDefault: boolean; profileIds: string[] }) {
  const body = new FormData()
  body.append("file", file)
  body.append("name", fields.name)
  body.append("is_active", String(fields.isActive))
  body.append("is_default", String(fields.isDefault))
  if (fields.profileIds.length > 0) {
    body.append("profile_ids", fields.profileIds.join(","))
  }
  return request<Resume>("/resumes", { method: "POST", body })
}

export function updateResume(
  id: string,
  body: { name?: string; is_active?: boolean; is_default?: boolean; profile_ids?: string[] },
) {
  return request<Resume>(`/resumes/${id}`, { method: "PATCH", body: JSON.stringify(body) })
}

export function replaceResumeFile(id: string, file: File) {
  const body = new FormData()
  body.append("file", file)
  return request<Resume>(`/resumes/${id}/replace`, { method: "POST", body })
}

export function listTemplates() {
  return request<Page<Template>>("/templates?limit=200")
}

export function createTemplate(body: {
  name: string
  subject: string
  body: string
  is_active: boolean
  is_default: boolean
  profile_ids: string[]
}) {
  return request<Template>("/templates", { method: "POST", body: JSON.stringify(body) })
}

export function updateTemplate(
  id: string,
  body: {
    name: string
    subject: string
    body: string
    is_active: boolean
    is_default: boolean
    profile_ids: string[]
  },
) {
  return request<Template>(`/templates/${id}`, { method: "PATCH", body: JSON.stringify(body) })
}

export function deactivateTemplate(id: string) {
  return request<Template>(`/templates/${id}`, { method: "DELETE" })
}

export function duplicateTemplate(id: string) {
  return request<Template>(`/templates/${id}/duplicate`, { method: "POST" })
}

export function previewTemplate(body: PreviewFields & { subject: string; body: string }) {
  return request<TemplatePreview>("/templates/preview", { method: "POST", body: JSON.stringify(body) })
}
