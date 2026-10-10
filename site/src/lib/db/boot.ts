/**
 * Startup downloads, started from an inline script in <head> before any bundle runs:
 * /data/reference.json, then the model (`model` in reference.json) and, in chunked mode,
 * the database parts every page reads first (`boot`, scripts/split-sqlite.ts), in
 * parallel. Parts are immutable, so the worker's reads of them later come from the HTTP
 * cache. lib/db/browser.ts picks up the config and model promises from
 * `window.__dcsRefConfig` and `window.__dcsModel`.
 */

import { BASE_PATH } from "../base-path";

/** Override with NEXT_PUBLIC_REFERENCE_CONFIG (absolute URL or site path) at build time. */
export const CONFIG_URL =
  process.env.NEXT_PUBLIC_REFERENCE_CONFIG ?? `${BASE_PATH}/data/reference.json`;
/** Changes when the worker or wasm does (next.config.ts): their URLs are cached for good. */
const REV = process.env.NEXT_PUBLIC_SQLITE_REV ?? "0";
export const WORKER_URL = `${BASE_PATH}/sqlite/sqlite.worker.js?v=${REV}`;
export const WASM_URL = `${BASE_PATH}/sqlite/sql-wasm.wasm?v=${REV}`;

/** Hand-written record and field notes (lib/client-data.ts `loadOverlays`). */
export const OVERLAYS_URL = `${BASE_PATH}/overlays/reference.json`;

/**
 * Pages that read no database (the home page, the reference contents, search): the model,
 * reference.json and the search rows are all they show. They leave the worker, its wasm and the startup parts
 * until they have loaded (lib/db/browser.ts), so those do not compete with the page.
 */
export const DB_FREE_PATHS = `^${BASE_PATH}(/|/reference/|/search/)?$`;

/**
 * The inline script. Besides the parts every page reads, API pages fetch the API docs'
 * parts, and the search page the search rows (`window.__dcsNames`). Pages that read the
 * reference overlays (records, browse tables, compare, search) preload them; the home page,
 * the reference contents and API pages do not. The rest preload the worker and its wasm.
 */
export function bootScript(): string {
  const api = `^${BASE_PATH}/api(/|$)`;
  const search = `^${BASE_PATH}/search(/|$)`;
  const noOverlays = `^${BASE_PATH}(/|/reference/|/api(/.*)?)?$`;
  const preload = (href: string, as: string, cors: boolean) =>
    `var e=document.createElement("link");e.rel="preload";e.as=${JSON.stringify(as)};${cors ? 'e.crossOrigin="anonymous";' : ""}e.href=${JSON.stringify(href)};document.head.appendChild(e);`;
  return `(function(){try{var d=new RegExp(${JSON.stringify(DB_FREE_PATHS)}).test(location.pathname);if(!d){${preload(WASM_URL, "fetch", true)}${preload(WORKER_URL, "script", false)}}if(!new RegExp(${JSON.stringify(noOverlays)}).test(location.pathname)){var k=document.createElement("link");k.rel="preload";k.as="fetch";k.crossOrigin="anonymous";k.href=${JSON.stringify(OVERLAYS_URL)};document.head.appendChild(k)}var u=new URL(${JSON.stringify(CONFIG_URL)},location.href);var p=fetch(u).then(function(r){if(!r.ok)throw new Error(u+": HTTP "+r.status);return r.json()});window.__dcsRefConfig=p;var j=function(k){var m=p.then(function(c){var f=new URL(c[k],u);return fetch(f).then(function(r){if(!r.ok)throw new Error(f+": HTTP "+r.status);return r.json()})});m.catch(function(){});return m};window.__dcsModel=j("model");if(new RegExp(${JSON.stringify(search)}).test(location.pathname))window.__dcsNames=j("names");p.then(function(c){var b=c.boot;if(c.serverMode!=="chunked"||!b||d)return;var l=location.pathname,g=b.core.slice();if(new RegExp(${JSON.stringify(api)}).test(l))g=g.concat(b.api);g.forEach(function(i){var s=String(i);while(s.length<c.suffixLength)s="0"+s;fetch(new URL(c.urlPrefix+s,u),{priority:"low"}).catch(function(){})})}).catch(function(){})}catch(e){}})();`;
}
