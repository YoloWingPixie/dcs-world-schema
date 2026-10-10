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

/**
 * `load` behind a cache of its last `size` keys' promises (in-flight ones included), most
 * recently used kept; a failure is dropped unless a newer promise already replaced it.
 */
export function boundedCache<T>(size: number, load: (key: string) => Promise<T>) {
  const recent = new Map<string, Promise<T>>();
  return (key: string): Promise<T> => {
    const hit = recent.get(key);
    if (hit) {
      recent.delete(key);
      recent.set(key, hit);
      return hit;
    }
    const promise = load(key);
    recent.set(key, promise);
    promise.catch(() => {
      if (recent.get(key) === promise) recent.delete(key);
    });
    for (const old of recent.keys()) {
      if (recent.size <= size) break;
      recent.delete(old);
    }
    return promise;
  };
}

/** `url`'s JSON, or `fallback` when the fetch fails or answers with an error status. */
export function fetchJsonOr<T>(url: string, fallback: T): Promise<T> {
  return fetch(url)
    .then((r) => (r.ok ? (r.json() as Promise<T>) : fallback))
    .catch(() => fallback);
}
