export interface ApiResponse<T = unknown> {
  data: T | null
  error: string | null
  status: number
}

export async function apiFetch<T = unknown>(
  endpoint: string,
  options: RequestInit = {}
): Promise<ApiResponse<T>> {
  const url = `/api${endpoint.startsWith('/') ? endpoint : '/' + endpoint}`

  try {
    const response = await fetch(url, {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
      ...options,
    })

    const data = await response.json()

    if (!response.ok) {
      return {
        data: null,
        error: data.detail || data.error || `HTTP ${response.status}`,
        status: response.status,
      }
    }

    return {
      data: data as T,
      error: null,
      status: response.status,
    }
  } catch (err) {
    return {
      data: null,
      error: err instanceof Error ? err.message : 'Network error',
      status: 0,
    }
  }
}

// Convenience methods
export const api = {
  get: <T = unknown>(endpoint: string) =>
    apiFetch<T>(endpoint, { method: 'GET' }),

  post: <T = unknown>(endpoint: string, body?: unknown) =>
    apiFetch<T>(endpoint, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
    }),
}
