// Runs the Worker's fetch handler (src/index.js) in Node for local testing - unlike `wrangler dev`, Node can
// reach OpenAI through a proxy (NODE_USE_ENV_PROXY=1). Env: OPENAI_API_KEY, DEV_CODE, ALLOWED_ORIGINS, PORT.
//   node test/dev_server.mjs
import { build } from "esbuild";
import http from "node:http";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.join(here, ".server.mjs");
await build({ entryPoints: [path.join(here, "..", "src", "index.js")], bundle: true, platform: "neutral", format: "esm",
  outfile: out, logLevel: "error", mainFields: ["module", "main"] });
const worker = (await import(pathToFileURL(out).href)).default;
const env = {
  OPENAI_API_KEY: process.env.OPENAI_API_KEY, DEV_CODE: process.env.DEV_CODE,
  ALLOWED_ORIGINS: process.env.ALLOWED_ORIGINS || "https://cognicoachai.com,https://www.cognicoachai.com",
  RATE_LIMIT_PER_MINUTE: "30", DAILY_MODEL_LIMIT: "300",
};
const port = Number(process.env.PORT || 8787);
http.createServer(async (req, res) => {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const body = ["GET", "HEAD", "OPTIONS"].includes(req.method) ? undefined : Buffer.concat(chunks);
  const request = new Request(`http://localhost:${port}${req.url}`, { method: req.method, headers: req.headers, body });
  const waits = [];
  const resp = await worker.fetch(request, env, { waitUntil: (p) => waits.push(p) });
  res.writeHead(resp.status, Object.fromEntries(resp.headers));
  res.end(Buffer.from(await resp.arrayBuffer()));
}).listen(port, () => console.log(`worker dev server on http://localhost:${port}`));
