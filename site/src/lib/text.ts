/** `fixedwing` -> `Fixedwing`. */
export const capitalise = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** Lowercase with only letters and digits kept: "AIM-120C" and "aim 120c" both give "aim120c". */
export const squash = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "");
