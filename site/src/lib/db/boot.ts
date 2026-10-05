/**
 * Startup downloads, started from an inline script in <head> before any bundle runs:
 * /data/reference.json, then (chunked mode) the database parts every page reads first
 * (`boot` in reference.json, scripts/split-sqlite.ts), in parallel. Parts are immutable,
 * so the worker's reads of them later come from the HTTP cache. lib/db/browser.ts picks
 * up the config promise from `window.__dcsRefConfig`.
 */

const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
/** Override with NEXT_PUBLIC_REFERENCE_CONFIG (absolute URL or site path) at build time. */
export const CONFIG_URL =
  process.env.NEXT_PUBLIC_REFERENCE_CONFIG ?? `${BASE_PATH}/data/reference.json`;
/** Changes when the worker or wasm does (next.config.ts): their URLs are cached for good. */
const REV = process.env.NEXT_PUBLIC_SQLITE_REV ?? "0";
export const WORKER_URL = `${BASE_PATH}/sqlite/sqlite.worker.js?v=${REV}`;
export const WASM_URL = `${BASE_PATH}/sqlite/sql-wasm.wasm?v=${REV}`;

/**
 * The inline script. Besides the parts every page reads, API pages fetch the API docs'
 * parts and the search page the search index's.
 */
export function bootScript(): string {
  const api = `^${BASE_PATH}/api(/|$)`;
  const search = `^${BASE_PATH}/search(/|$)`;
  return `(function(){try{var u=new URL(${JSON.stringify(CONFIG_URL)},location.href);var p=fetch(u).then(function(r){if(!r.ok)throw new Error(u+": HTTP "+r.status);return r.json()});window.__dcsRefConfig=p;p.then(function(c){var b=c.boot;if(c.serverMode!=="chunked"||!b)return;var l=location.pathname,g=b.core.slice();if(new RegExp(${JSON.stringify(api)}).test(l))g=g.concat(b.api);if(new RegExp(${JSON.stringify(search)}).test(l))g=g.concat(b.search);g.forEach(function(i){var s=String(i);while(s.length<c.suffixLength)s="0"+s;fetch(new URL(c.urlPrefix+s,u),{priority:"low"}).catch(function(){})})}).catch(function(){})}catch(e){}})();`;
}
