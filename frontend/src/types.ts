export type Page<T> = {
  items: T[]
  limit: number
  offset: number
  total: number
}

export type Profile = {
  id: string
  name: string
  resume_id: string | null
  email_template_id: string | null
  is_active: boolean
  priority: number
  keywords: string[]
  created_at: string
  updated_at: string
}

export type Resume = {
  id: string
  name: string
  original_filename: string
  content_type: string
  size_bytes: number
  sha256: string
  is_active: boolean
  is_default: boolean
  profile_ids: string[]
  created_at: string
  updated_at: string
}

export type Template = {
  id: string
  name: string
  subject: string
  body: string
  is_active: boolean
  is_default: boolean
  profile_ids: string[]
  created_at: string
  updated_at: string
}

export type TemplatePreview = {
  subject: string
  body: string
  empty_variables: string[]
  unknown_tokens: string[]
}

export type GoogleStatus = {
  connected: boolean
  email: string | null
  scopes: string[]
  connected_at: string | null
}

export type SheetConnection = {
  spreadsheet_id: string
  spreadsheet_url: string
  sheet_name: string | null
  header_map: Record<string, string> | null
  last_synced_at: string | null
}

export type Campaign = {
  id: string
  name: string
  status: string
  created_at: string
}

export type CampaignContact = {
  id: string
  email: string
  name: string | null
  company: string | null
  role: string | null
  original_role: string | null
  status: string
  skip_reason: string | null
  profile_id: string | null
  profile_name: string | null
  match_confidence: string | null
  match_method: string | null
  matched_keywords: string[]
  resume_id: string | null
  resume_name: string | null
  template_id: string | null
  template_name: string | null
  resume_overridden: boolean
  template_overridden: boolean
}

export type SyncSummary = {
  campaign_id: string
  rows_read: number
  valid: number
  needs_review: number
  not_sent: number
  already_sent: number
  skipped_invalid: number
  skipped_duplicate: number
}

export type PreviewFields = {
  name: string
  company: string
  role: string
  location: string
  mobile: string
  linkedin_url: string
}
