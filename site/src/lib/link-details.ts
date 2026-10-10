/**
 * Short facts that tell same-named records apart in a list of links: an airbase's three
 * beacons are all "KERMAN", so each reads "KERMAN · TACAN 97", "KERMAN · VOR/DME 112.00 MHz".
 * Applied only where names collide in one list (lib/db/reference.ts); a series without an
 * entry here keeps its plain names.
 */
import { constantLabel } from "./names";
import { formatNumber } from "./units";

type Row = Record<string, unknown>;

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** "112.00 MHz", "395 kHz". */
export function frequencyText(hz: number): string {
  return hz >= 1e6 ? `${(hz / 1e6).toFixed(2)} MHz` : `${formatNumber(hz / 1e3)} kHz`;
}

/** Beacon types tuned by channel rather than frequency. */
const CHANNELLED = /^BEACON_TYPE_(TACAN|RSBN|PRMG_)/;

export const LINK_DETAILS: Record<string, (row: Row) => string | null> = {
  beacons: (r) => {
    const typeName = typeof r.typeName === "string" ? r.typeName : null;
    const channel = num(r.channel);
    const hz = num(r.frequencyHz);
    const tuning =
      typeName && CHANNELLED.test(typeName) && channel !== null
        ? String(channel)
        : hz !== null
          ? frequencyText(hz)
          : channel !== null
            ? `ch ${channel}`
            : null;
    const parts = [typeName ? constantLabel(typeName) : null, tuning].filter(Boolean);
    return parts.length ? parts.join(" ") : null;
  },
};

/** Ids whose name occurs more than once among `pairs`. */
export function collidingIds(pairs: Array<[id: string, name: string]>): string[] {
  const seen = new Map<string, number>();
  for (const [, name] of pairs) seen.set(name, (seen.get(name) ?? 0) + 1);
  return pairs.filter(([, name]) => (seen.get(name) ?? 0) > 1).map(([id]) => id);
}

export const withDetail = (name: string, detail: string | null) =>
  detail ? `${name} · ${detail}` : name;
