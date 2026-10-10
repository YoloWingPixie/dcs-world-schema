import { useEffect, useRef, useState } from "react";

/**
 * `load(key)`'s value, loaded again whenever `key` changes: null while loading, on failure,
 * for an answer that arrives after the key moved on, and while `key` is null (idle). The
 * loader is read from a ref, so an inline function does not reload: anything else it reads
 * comes through its closure, and `key` names what the value depends on.
 */
export function useLoaded<T>(load: (key: string) => Promise<T>, key: string | null = ""): T | null {
  const [value, setValue] = useState<T | null>(null);
  const loader = useRef(load);
  loader.current = load;
  useEffect(() => {
    setValue(null);
    if (key === null) return;
    let live = true;
    loader.current(key).then(
      (v) => live && setValue(v),
      () => live && setValue(null),
    );
    return () => {
      live = false;
    };
  }, [key]);
  return value;
}
