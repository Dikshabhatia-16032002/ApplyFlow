export class ApiError extends Error {
  readonly detail: string
  readonly code: string | null
  readonly body: unknown

  constructor(detail: string, code: string | null = null, body: unknown = null) {
    super(detail)
    this.detail = detail
    this.code = code
    this.body = body
  }
}

export function messageOf(error: unknown): string {
  return error instanceof ApiError ? error.detail : "Request failed"
}

function errorDetail(body: unknown): string {
  if (!body || typeof body !== "object" || !("detail" in body)) {
    return "Request failed"
  }
  const detail = body.detail
  if (typeof detail === "string") {
    return detail
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          return String(item.msg)
        }
        return String(item)
      })
      .join(" ")
  }
  return "Request failed"
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }
  const response = await fetch(`/api/v1${path}`, { ...init, headers })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const code = body && typeof body === "object" && "code" in body && typeof body.code === "string" ? body.code : null
    throw new ApiError(errorDetail(body), code, body)
  }
  return response.json() as Promise<T>
}
