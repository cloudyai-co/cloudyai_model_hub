#!/usr/bin/env node
// Syntax-check every ES module under frontend/js with `node --check`. No dependencies.
import { execFileSync } from "node:child_process";
import { readdirSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

function listModules(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return listModules(path);
    return name.endsWith(".js") || name.endsWith(".mjs") ? [path] : [];
  });
}

const files = [...listModules(join(root, "frontend", "js")), join(root, "tests", "js")].flatMap((entry) =>
  statSync(entry).isDirectory() ? listModules(entry) : [entry],
);

let failures = 0;
for (const file of files) {
  try {
    execFileSync(process.execPath, ["--check", file], { stdio: "pipe" });
  } catch (error) {
    failures += 1;
    process.stderr.write(`${relative(root, file)}\n${error.stderr}\n`);
  }
}
console.log(`Checked ${files.length} modules, ${failures} with syntax errors.`);
process.exitCode = failures ? 1 : 0;
