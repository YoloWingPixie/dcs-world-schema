import { tableAxis } from "../../src/lib/catalog";
import { catalogFor, type Model, storageOf } from "../../src/lib/db/reference";

/**
 * How the package reads one comparable field (`compareAs` set in its catalog) out of a
 * series' records (tools/package/site_views.py), into the database's `field_values`:
 *
 * - a plain or keyed path (`aero.maxTakeoffKg`, `flight.motorStages.*.impulseS`): its value;
 * - `samples`: a Mach-sampled list, stored as its record holds it (the list and its step);
 * - `curve`: a table column over the table's axis column, as `{x, y}`;
 * - `surfaces`: an envelope's grid, one `{rows, cols, z}` per table item holding it.
 *
 * `ref` names the series a field's ids point at (its catalog `ref`), whose names the package
 * stores beside the values.
 */
export type CompareField = {
  path: string;
  ref?: string[];
  samples?: { list: string; step: string };
  curve?: { table: string; x: string; y: string };
  surfaces?: { table: string; rows: string; cols: string; z: string };
};

export type CompareSeries = {
  /** Comparable fields, in catalog order. */
  fields: CompareField[];
  /** The item field naming each item of a keyed array, by the array's catalog path. */
  keyFields?: Record<string, string>;
  /** Keyed arrays that are a whole column: their keys name the concrete keyed paths. */
  keyed?: string[];
};

/** Per browsable series (companions under their parent's `flight.`), by series id. */
export type CompareFields = Record<string, CompareSeries>;

/** Every browsable series' comparable fields, as site/src/lib/compare-fields.json holds them. */
export function compareFields(model: Model): CompareFields {
  const out: CompareFields = {};
  const ids = model.series
    .filter((s) => !s.parent)
    .map((s) => s.id)
    .sort();
  for (const series of ids) {
    const catalog = catalogFor(model, series);
    const entries = Object.values(catalog.entries);
    const fields = entries.flatMap((e): CompareField[] => {
      if (e.compareAs === undefined) return [];
      const field: CompareField = { path: e.path };
      if (e.ref?.length) field.ref = [...e.ref];
      const axis = tableAxis(e);
      if (axis?.kind === "column") field.curve = { table: axis.table, x: axis.field, y: e.name };
      else if (axis?.kind === "surface") {
        field.surfaces = { table: axis.table, rows: axis.rows, cols: axis.cols, z: e.name };
      } else if (e.axis?.kind === "sampled") {
        field.samples = { list: e.name, step: e.axis.step.field };
      }
      return [field];
    });
    if (!fields.length) continue;
    const arrays = entries.filter((e) => e.keyField);
    const spec: CompareSeries = { fields };
    if (arrays.length) {
      spec.keyFields = Object.fromEntries(arrays.map((e) => [e.path, e.keyField as string]));
      const keyed = arrays.filter((e) => {
        const at = storageOf(model, series, e.path);
        return at && !at.json;
      });
      if (keyed.length) spec.keyed = keyed.map((e) => e.path);
    }
    out[series] = spec;
  }
  return out;
}
