import { useEffect, useRef, useState } from "react";

/**
 * `load(key)`'s value, loaded again whenever `key` changes: null while loading, on failure,
 * and for an answer that arrives after the key moved on. The loader is read from a ref, so
 * an inline function does not reload.
 */
export function useLoaded<T>(load: (key: string) => Promise<T>, key = ""): T | null {
  const [value, setValue] = useState<T | null>(null);
  const loader = useRef(load);
  loader.current = load;
  useEffect(() => {
    let live = true;
    setValue(null);
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
