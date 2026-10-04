// Minimal static server for the `out/` export (previews and Playwright). No dependencies.
// Like GitHub Pages: unknown paths get 404.html (the reference shell) with status 404, and
// files honour HTTP Range requests (the browser reads the SQLite database by ranges).
import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL("../out", import.meta.url)));
const port = Number(process.argv[2] ?? process.env.PORT ?? 3211);
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
  const range = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range ?? "");
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
