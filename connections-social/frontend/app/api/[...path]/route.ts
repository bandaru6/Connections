import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.BACKEND_URL || 'http://127.0.0.1:8000'

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params
  return proxyRequest(request, path, 'GET')
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params
  return proxyRequest(request, path, 'POST')
}

async function proxyRequest(
  request: NextRequest,
  pathSegments: string[],
  method: string
): Promise<NextResponse> {
  const path = '/' + pathSegments.join('/')
  const searchParams = request.nextUrl.searchParams.toString()
  const url = `${BACKEND_URL}${path}${searchParams ? '?' + searchParams : ''}`

  try {
    const contentType = request.headers.get('content-type') || ''
    const isMultipart = contentType.includes('multipart/form-data')
    const isJson = contentType.includes('application/json')

    const fetchOptions: RequestInit = {
      method,
    }

    // Forward body for POST requests
    if (method === 'POST') {
      if (isMultipart) {
        // For multipart/form-data, pass through the raw body and let fetch set headers
        const formData = await request.formData()
        fetchOptions.body = formData
        // Don't set Content-Type - let fetch handle it with proper boundary
      } else if (isJson) {
        fetchOptions.headers = { 'Content-Type': 'application/json' }
        try {
          const body = await request.text()
          if (body) {
            fetchOptions.body = body
          }
        } catch {
          // No body, that's fine
        }
      } else {
        // Default: try to pass through as text
        try {
          const body = await request.text()
          if (body) {
            fetchOptions.body = body
          }
        } catch {
          // No body, that's fine
        }
      }
    }

    const response = await fetch(url, fetchOptions)
    const data = await response.json()

    return NextResponse.json(data, { status: response.status })
  } catch (error) {
    console.error(`Proxy error for ${method} ${url}:`, error)
    return NextResponse.json(
      { error: 'Backend unavailable', detail: String(error) },
      { status: 502 }
    )
  }
}
