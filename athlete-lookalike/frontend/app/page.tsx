'use client'

import { useState, useCallback } from 'react'
import { useDropzone } from 'react-dropzone'

interface Match {
  athlete_id: string
  name: string
  league: string
  team: string
  position: string
  similarity: number
  image_url: string | null
}

interface CompareResult {
  success: boolean
  message: string
  top_match: Match | null
  matches: Match[]
}

export default function Home() {
  const [result, setResult] = useState<CompareResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedLeague, setSelectedLeague] = useState<string>('')
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    const file = acceptedFiles[0]
    if (!file) return

    // Show preview
    setPreviewUrl(URL.createObjectURL(file))
    setLoading(true)
    setError(null)
    setResult(null)

    const formData = new FormData()
    formData.append('file', file)

    try {
      const url = new URL('http://localhost:8000/compare/upload')
      if (selectedLeague) {
        url.searchParams.set('league', selectedLeague)
      }

      console.log('Uploading to:', url.toString())

      const response = await fetch(url.toString(), {
        method: 'POST',
        body: formData,
      })

      console.log('Response status:', response.status)

      const data = await response.json()
      console.log('Response data:', data)

      if (!response.ok) {
        throw new Error(data.detail || 'Failed to compare face')
      }

      setResult(data)
    } catch (err) {
      console.error('Upload error:', err)
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }, [selectedLeague])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'image/*': ['.jpeg', '.jpg', '.png', '.webp'] },
    maxFiles: 1,
  })

  return (
    <div className="space-y-8">
      {/* Hero */}
      <div className="text-center space-y-4">
        <h2 className="text-4xl font-bold">
          Which Athlete Do You Look Like?
        </h2>
        <p className="text-gray-400 text-lg">
          Upload a photo and we'll find your NBA or NFL doppelganger!
        </p>
      </div>

      {/* League Filter */}
      <div className="flex justify-center gap-4">
        <button
          onClick={() => setSelectedLeague('')}
          className={`px-6 py-2 rounded-lg font-medium transition ${
            selectedLeague === ''
              ? 'bg-white text-gray-900'
              : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
          }`}
        >
          All Athletes
        </button>
        <button
          onClick={() => setSelectedLeague('nba')}
          className={`px-6 py-2 rounded-lg font-medium transition ${
            selectedLeague === 'nba'
              ? 'bg-orange-600 text-white'
              : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
          }`}
        >
          NBA Only
        </button>
        <button
          onClick={() => setSelectedLeague('nfl')}
          className={`px-6 py-2 rounded-lg font-medium transition ${
            selectedLeague === 'nfl'
              ? 'bg-blue-600 text-white'
              : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
          }`}
        >
          NFL Only
        </button>
      </div>

      {/* Upload Zone */}
      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition ${
          isDragActive
            ? 'border-orange-500 bg-orange-500/10'
            : 'border-gray-600 hover:border-gray-500 hover:bg-gray-800/50'
        }`}
      >
        <input {...getInputProps()} />
        {loading ? (
          <div className="space-y-4">
            <div className="animate-spin rounded-full h-12 w-12 border-4 border-orange-500 border-t-transparent mx-auto" />
            <p className="text-gray-400">Analyzing your face...</p>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="text-5xl">📸</div>
            <p className="text-xl">
              {isDragActive ? 'Drop your photo here!' : 'Drag & drop a photo, or click to select'}
            </p>
            <p className="text-gray-500 text-sm">
              Supports JPG, PNG, WebP
            </p>
          </div>
        )}
      </div>

      {/* Debug Info */}
      <div className="text-xs text-gray-500 text-center">
        Status: {loading ? 'Loading...' : result ? `Got ${result.matches?.length || 0} matches` : 'Ready'}
        {error && ` | Error: ${error}`}
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-900/50 border border-red-700 rounded-lg p-4 text-center">
          <p className="text-red-300">{error}</p>
        </div>
      )}

      {/* No matches message */}
      {result && result.success && (!result.matches || result.matches.length === 0) && (
        <div className="bg-yellow-900/50 border border-yellow-700 rounded-lg p-4 text-center">
          <p className="text-yellow-300">No matching athletes found. Try a different photo with a clearer face.</p>
        </div>
      )}

      {/* Results */}
      {result && result.success && (
        <div className="space-y-6">
          {/* Top Match */}
          {result.top_match && (
            <div className="bg-gradient-to-r from-orange-600/20 to-red-600/20 border border-orange-500/50 rounded-xl p-6">
              <div className="flex items-center gap-6">
                <div className="text-center">
                  {previewUrl ? (
                    <img
                      src={previewUrl}
                      alt="Your photo"
                      className="w-32 h-32 object-cover rounded-lg"
                      onError={(e) => {
                        console.error('Preview image failed to load');
                        e.currentTarget.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" fill="%23666"><rect width="128" height="128"/><text x="50%" y="50%" text-anchor="middle" dy=".3em" fill="%23999" font-size="14">You</text></svg>';
                      }}
                    />
                  ) : (
                    <div className="w-32 h-32 bg-gray-700 rounded-lg flex items-center justify-center">
                      <span className="text-gray-400">You</span>
                    </div>
                  )}
                  <p className="text-sm text-gray-400 mt-2">You</p>
                </div>
                <div className="text-4xl">=</div>
                <div className="text-center">
                  {result.top_match.image_url && (
                    <img
                      src={`http://localhost:8000${result.top_match.image_url}`}
                      alt={result.top_match.name}
                      className="w-32 h-32 object-cover rounded-lg bg-gray-700"
                    />
                  )}
                  <p className="text-sm text-gray-400 mt-2">{result.top_match.name}</p>
                </div>
                <div className="flex-1">
                  <p className="text-sm text-orange-400 uppercase tracking-wider">Your Top Match</p>
                  <h3 className="text-3xl font-bold">{result.top_match.name}</h3>
                  <div className="flex gap-3 mt-2">
                    <span className={`px-3 py-1 rounded-full text-sm ${
                      result.top_match.league === 'nba' ? 'bg-orange-600' : 'bg-blue-600'
                    }`}>
                      {result.top_match.league.toUpperCase()}
                    </span>
                    {result.top_match.team && (
                      <span className="px-3 py-1 bg-gray-700 rounded-full text-sm">
                        {result.top_match.team}
                      </span>
                    )}
                  </div>
                </div>
                <div className="text-right">
                  <p className="text-5xl font-bold text-orange-500">
                    {result.top_match.similarity}%
                  </p>
                  <p className="text-gray-400 text-sm">similarity</p>
                </div>
              </div>
            </div>
          )}

          {/* Other Matches */}
          {result.matches.length > 1 && (
            <div>
              <h4 className="text-xl font-semibold mb-4">Other Matches</h4>
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
                {result.matches.slice(1).map((match, i) => (
                  <div
                    key={match.athlete_id}
                    className="bg-gray-800 rounded-lg p-4 text-center"
                  >
                    {match.image_url && (
                      <img
                        src={`http://localhost:8000${match.image_url}`}
                        alt={match.name}
                        className="w-20 h-20 object-cover rounded-lg mx-auto mb-3 bg-gray-700"
                      />
                    )}
                    <p className="font-medium truncate">{match.name}</p>
                    <p className={`text-xs mt-1 ${
                      match.league === 'nba' ? 'text-orange-400' : 'text-blue-400'
                    }`}>
                      {match.league.toUpperCase()}
                    </p>
                    <p className="text-2xl font-bold text-gray-300 mt-2">
                      {match.similarity}%
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
