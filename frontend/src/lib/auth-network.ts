/** Bound interactive auth/profile requests; never automatically retry mutations. */
export const AUTH_FETCH_OPTIONS = { timeout: 15_000, retry: 0 } as const;

export function fetchWithTimeout(input: RequestInfo | URL, init: RequestInit = {}, timeoutMs = 20_000): Promise<Response> {
  const timeout = AbortSignal.timeout(timeoutMs);
  return fetch(input, {
    ...init,
    signal: init.signal ? AbortSignal.any([init.signal, timeout]) : timeout,
  });
}
