/** Core fetch utility for Seeker OS API client. */

export const API_BASE =
  typeof window === "undefined"
    ? process.env["SERVER_API_URL"] || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
    : "";

export async function fetchAPI<T>(path: string, options?: RequestInit): Promise<T> {
  const isFormData = options?.body instanceof FormData;
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      // Don't set Content-Type for FormData — browser sets multipart boundary
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    // FastAPI validation errors return detail as an array of {msg, ...} objects
    const detail = error.detail;
    let message: string;
    if (typeof detail === "string") {
      message = detail;
    } else if (Array.isArray(detail)) {
      message = detail.map((e: { msg?: string; message?: string } | string) =>
        typeof e === "string" ? e : e.msg || e.message || JSON.stringify(e)
      ).join("; ");
    } else if (detail && typeof detail === "object") {
      message = detail.msg || detail.message || JSON.stringify(detail);
    } else {
      message = `API error: ${res.status}`;
    }
    throw new Error(message);
  }
  return res.json();
}
