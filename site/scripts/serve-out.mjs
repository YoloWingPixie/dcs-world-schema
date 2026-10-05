// Minimal static server for the `out/` export (previews and Playwright). No dependencies.
// Like Cloudflare Pages: `/<prefix>/* <target> 200` rules in _redirects serve the target,
// other unknown paths get 404.html (the reference shell) with status 404. Files honour
// HTTP Range requests (single-file mode reads the SQLite database by ranges).
// SERVE_NO_RANGES=1 answers Range requests with the whole file, as Cloudflare Pages does.
//   node scripts/serve-out.mjs [port] [root]
import { createReadStream, existsSync, readFileSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(process.argv[3] ?? fileURLToPath(new URL("../out", import.meta.url)));
const port = Number(process.argv[2] ?? process.env.PORT ?? 3211);
const rewrites = existsSync(join(root, "_redirects"))
  ? readFileSync(join(root, "_redirects"), "utf8")
      .split("\n")
      .map((line) => line.trim().split(/\s+/))
      .filter(([from, to, status]) => from?.endsWith("/*") && to && status === "200")
      .map(([from, to]) => ({ prefix: from.slice(0, -1), to }))
  : [];
const types = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".woff": "font/woff",
  ".txt": "text/plain",
  ".ico": "image/x-icon",
  ".wasm": "application/wasm",
  ".sqlite": "application/octet-stream",
};

createServer((req, res) => {
  const url = new URL(req.url ?? "/", "http://localhost");
  let path = normalize(join(root, decodeURIComponent(url.pathname)));
  if (!path.startsWith(root)) {
    res.writeHead(403).end();
    return;
  }
  const rewrite = rewrites.find((r) => url.pathname.startsWith(r.prefix));
  if (rewrite) path = join(root, rewrite.to);
  if (existsSync(path) && statSync(path).isDirectory()) path = join(path, "index.html");
  if (!existsSync(path)) {
    res.writeHead(404, { "content-type": types[".html"] });
    if (req.method === "HEAD") {
      res.end();
      return;
    }
    createReadStream(join(root, "404.html")).pipe(res);
    return;
  }
  const size = statSync(path).size;
  const type = types[extname(path)] ?? "application/octet-stream";
  const range = !process.env.SERVE_NO_RANGES && /^bytes=(\d*)-(\d*)$/.exec(req.headers.range ?? "");
  if (range) {
    const start = range[1] ? Number(range[1]) : Math.max(0, size - Number(range[2]));
    const end = range[1] && range[2] ? Math.min(Number(range[2]), size - 1) : size - 1;
    if (start >= size || start > end) {
      res.writeHead(416, { "content-range": `bytes */${size}` }).end();
      return;
    }
    res.writeHead(206, {
      "content-type": type,
      "content-length": end - start + 1,
      "content-range": `bytes ${start}-${end}/${size}`,
      "accept-ranges": "bytes",
    });
    if (req.method === "HEAD") res.end();
    else createReadStream(path, { start, end }).pipe(res);
    return;
  }
  res.writeHead(200, { "content-type": type, "content-length": size, "accept-ranges": "bytes" });
  if (req.method === "HEAD") res.end();
  else createReadStream(path).pipe(res);
}).listen(port, "127.0.0.1", () => console.log(`serving ${root} on http://127.0.0.1:${port}`));
