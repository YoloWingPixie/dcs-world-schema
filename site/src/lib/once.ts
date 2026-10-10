/** Promises shared by key for the page's lifetime; a rejected one is dropped so the next call retries. */
const memo = new Map<string, Promise<unknown>>();

/** Each key's resolved value, once its promise has resolved (failures are not kept). */
const resolved = new Map<string, unknown>();

export function once<T>(key: string, load: () => Promise<T>): Promise<T> {
  const hit = memo.get(key);
  if (hit) return hit as Promise<T>;
  const promise = load();
  promise.then(
    (value) => resolved.set(key, value),
    () => memo.delete(key),
  );
  memo.set(key, promise);
  return promise;
}

/** The value `once(key, …)` resolved to, if it has; undefined while loading, after a failure, or never asked. */
export function settled<T>(key: string): T | undefined {
  return resolved.get(key) as T | undefined;
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

/** Values made once per object and key, kept as long as the object is. */
export type PerObject<O extends object, V> = {
  /** `make()` once per `obj` and `key`; later calls return the same value. */
  cachedBy<T extends V>(obj: O, key: string, make: () => T): T;
  /** The value made for `obj` and `key`, if any (none is made). */
  peek(obj: O, key: string): V | undefined;
  /** Forgets one value, so the next `cachedBy` makes it again. */
  drop(obj: O, key: string): void;
};

/** A cache of values by object (a WeakMap) and then by key. */
export function perObject<O extends object, V = unknown>(): PerObject<O, V> {
  const caches = new WeakMap<O, Map<string, V>>();
  return {
    cachedBy<T extends V>(obj: O, key: string, make: () => T): T {
      let byKey = caches.get(obj);
      if (!byKey) {
        byKey = new Map();
        caches.set(obj, byKey);
      }
      if (byKey.has(key)) return byKey.get(key) as T;
      const value = make();
      byKey.set(key, value);
      return value;
    },
    peek: (obj, key) => caches.get(obj)?.get(key),
    drop: (obj, key) => {
      caches.get(obj)?.delete(key);
    },
  };
}

/** `url`'s JSON, or `fallback` when the fetch fails or answers with an error status. */
export function fetchJsonOr<T>(url: string, fallback: T): Promise<T> {
  return fetch(url)
    .then((r) => (r.ok ? (r.json() as Promise<T>) : fallback))
    .catch(() => fallback);
}
