/** Promises shared by key for the page's lifetime; a rejected one is dropped so the next call retries. */
const memo = new Map<string, Promise<unknown>>();

export function once<T>(key: string, load: () => Promise<T>): Promise<T> {
  const hit = memo.get(key);
  if (hit) return hit as Promise<T>;
  const promise = load();
  promise.catch(() => memo.delete(key));
  memo.set(key, promise);
  return promise;
}

/** `url`'s JSON, or `fallback` when the fetch fails or answers with an error status. */
export function fetchJsonOr<T>(url: string, fallback: T): Promise<T> {
  return fetch(url)
    .then((r) => (r.ok ? (r.json() as Promise<T>) : fallback))
    .catch(() => fallback);
}
