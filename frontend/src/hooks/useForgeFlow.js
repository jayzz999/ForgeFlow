import { useState, useCallback, useEffect } from 'react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export function useForgeFlow() {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const forge = useCallback(async (message) => {
    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const resp = await fetch(`${API_URL}/api/forge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
      })

      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)

      const data = await resp.json()
      setResult(data)
      return data
    } catch (err) {
      setError(err.message)
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  return { forge, loading, result, error }
}

export function useProviderStatus() {
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const resp = await fetch(`${API_URL}/api/status`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      setStatus(await resp.json())
    } catch (err) {
      setStatus(null)
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  return { status, loading, error, refresh }
}
