// src/lib/api.ts
// API client — all requests go through Next.js rewrites proxy to Django

export async function fetcher<T = unknown>(path: string): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
  });

  if (!res.ok) {
    let message = `${res.status}: ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) message = body.detail;
      else if (body?.errors?.[0]?.message) message = body.errors[0].message;
    } catch {
      // ignore parse error
    }
    const error = new Error(message) as Error & { status: number };
    error.status = res.status;
    throw error;
  }

  return res.json() as Promise<T>;
}
