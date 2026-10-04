/**
 * The global search registry: every prebuilt index and live provider the palette merges.
 * Contract and how to add a source: ./README.md.
 */
import { API_PROVIDER } from "../api/search-provider";
import { REFERENCE_PROVIDER } from "./reference-sources";
import type { SearchProvider, SearchSource } from "./types";

export type { SearchProvider, SearchResultItem, SearchSource, StoredDoc } from "./types";

/** Prebuilt MiniSearch indexes, loaded whole on first use. */
export const SEARCH_SOURCES: SearchSource[] = [];

/** Searches that query their own backend per keystroke (results grouped by the provider). */
export const SEARCH_PROVIDERS: SearchProvider[] = [REFERENCE_PROVIDER, API_PROVIDER];

export function sourceById(id: string): SearchSource | undefined {
  return SEARCH_SOURCES.find((s) => s.id === id);
}
