"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { updateQuery } from "./history";

/**
 * A text box's value kept in one query parameter (`?q=`), so the view is shareable: the
 * state starts from the address and is written back, trimmed, `delay` ms after the last
 * change, keeping the other parameters. Also returns the parameter as the address has it.
 */
export function useQueryParam(
  name: string,
  delay = 250,
): [value: string, setValue: (value: string) => void, inUrl: string] {
  const inUrl = useSearchParams().get(name) ?? "";
  const [value, setValue] = useState(inUrl);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const v = value.trim();
      updateQuery((p) => {
        if (v) p.set(name, v);
        else p.delete(name);
      });
    }, delay);
    return () => window.clearTimeout(timer);
  }, [name, value, delay]);
  return [value, setValue, inUrl];
}
