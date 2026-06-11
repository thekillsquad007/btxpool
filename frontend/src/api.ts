/** Pool API base URL. Empty = same origin (pool serves UI + API together). */
export const POOL_API_BASE = (import.meta.env.VITE_POOL_API_URL || "").replace(/\/$/, "");

export function apiUrl(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  return POOL_API_BASE ? `${POOL_API_BASE}${p}` : p;
}