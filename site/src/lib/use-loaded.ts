import { useEffect, useRef, useState } from "react";

/**
 * `load(key)`'s value, loaded again whenever `key` changes: null while loading, on failure,
 * for an answer that arrives after the key moved on, and while `key` is null (idle). The
 * loader is read from a ref, so an inline function does not reload: anything else it reads
 * comes through its closure, and `key` names what the value depends on. `known(key)` gives
 * a value already loaded (undefined if none), so a fresh mount renders it at once.
 */
export function useLoaded<T>(
  load: (key: string) => Promise<T>,
  key: string | null = "",
  known?: (key: string) => T | undefined,
): T | null {
  const [value, setValue] = useState<T | null>(() =>
    key === null ? null : (known?.(key) ?? null),
  );
  const loader = useRef({ load, known });
  loader.current = { load, known };
  useEffect(() => {
    if (key === null) {
      setValue(null);
      return;
    }
    const ready = loader.current.known?.(key);
    if (ready !== undefined) {
      setValue(ready);
      return;
    }
    setValue(null);
    let live = true;
    loader.current.load(key).then(
      (v) => live && setValue(v),
      () => live && setValue(null),
    );
    return () => {
      live = false;
    };
  }, [key]);
  return value;
}
