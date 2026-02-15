import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptPath = fileURLToPath(import.meta.url);
const root = path.resolve(path.dirname(scriptPath), "..", "..");
const source = path.join(root, "data", "static", "voices-site.json");
const outDir = path.join(root, "site", "public", "data");
const target = path.join(outDir, "voices-site.json");

if (!fs.existsSync(source)) {
  console.error(`Missing source file: ${source}`);
  process.exit(1);
}

fs.mkdirSync(outDir, { recursive: true });
fs.copyFileSync(source, target);
console.log(`Copied ${source} -> ${target}`);
