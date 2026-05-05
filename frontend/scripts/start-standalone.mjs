import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const __filename = fileURLToPath(import.meta.url);
const projectRoot = path.resolve(path.dirname(__filename), "..");
const standaloneRoot = path.join(projectRoot, ".next", "standalone", "frontend");
const standaloneServer = path.join(standaloneRoot, "server.js");
const sourceStaticDir = path.join(projectRoot, ".next", "static");
const targetStaticDir = path.join(standaloneRoot, ".next", "static");
const sourcePublicDir = path.join(projectRoot, "public");
const targetPublicDir = path.join(standaloneRoot, "public");

function syncDir(sourceDir, targetDir) {
  if (!existsSync(sourceDir)) {
    return;
  }
  rmSync(targetDir, { recursive: true, force: true });
  mkdirSync(path.dirname(targetDir), { recursive: true });
  cpSync(sourceDir, targetDir, { recursive: true });
}

if (!existsSync(standaloneServer)) {
  console.error("Standalone server bundle not found. Run `npm run build` first.");
  process.exit(1);
}

syncDir(sourceStaticDir, targetStaticDir);
syncDir(sourcePublicDir, targetPublicDir);

const child = spawn(process.execPath, [standaloneServer], {
  cwd: standaloneRoot,
  stdio: "inherit",
  env: {
    ...process.env,
    HOSTNAME: process.env.HOSTNAME || "127.0.0.1",
    PORT: process.env.PORT || "3000",
  },
});

const forwardSignal = (signal) => {
  if (!child.killed) {
    child.kill(signal);
  }
};

process.on("SIGINT", () => forwardSignal("SIGINT"));
process.on("SIGTERM", () => forwardSignal("SIGTERM"));

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
