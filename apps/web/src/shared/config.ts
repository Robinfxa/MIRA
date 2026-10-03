/** Public, same-origin configuration only. Server secrets have no browser representation. */
export interface PublicConfig {
  readonly apiBase: string;
  readonly pollIntervalMs: number;
}
export function loadPublicConfig(): PublicConfig {
  return Object.freeze({ apiBase: '/api/v1', pollIntervalMs: 200 });
}
