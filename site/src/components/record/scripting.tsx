import { Fragment } from "react";
import type { ScriptingRow, ScriptingText } from "@/lib/types";
import { RefLink } from "../ref-link";

export const SCRIPTING_ID = "scripting";

/** Long Lua names break after their dots, not mid-name. */
function breakable(text: string) {
  return text.split(/(?<=[.[])/).map((part, i, all) => (
    // biome-ignore lint/suspicious/noArrayIndexKey: fixed pieces of one string
    <Fragment key={i}>
      {part}
      {i < all.length - 1 ? <wbr /> : null}
    </Fragment>
  ));
}

function Text({ t }: { t: ScriptingText }) {
  const body = t.code ? <code>{breakable(t.text)}</code> : t.text;
  return t.href ? <RefLink href={t.href}>{body}</RefLink> : body;
}

/**
 * A record's Scripting rows (`RecordDoc["scripting"]`), labelled as the record's own fields:
 * the API member or role, a leader, the value.
 */
export function ScriptingBlock({ rows }: { rows: ScriptingRow[] }) {
  return (
    <div className="fields script-fields">
      {rows.map((r) => (
        <div key={r.id} className="field script-field" data-scripting={r.id}>
          <span className="field-label">
            <span className="script-label">
              <Text t={r.label} />
              {r.verb ? <span className="script-verb"> {r.verb}</span> : null}
            </span>
          </span>
          <span className="field-value">
            <Text t={r.value} />
            {r.note ? <span className="secondary">{r.note}</span> : null}
          </span>
        </div>
      ))}
    </div>
  );
}
