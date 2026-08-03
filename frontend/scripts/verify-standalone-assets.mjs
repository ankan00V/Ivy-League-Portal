import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { existsSync } from "node:fs";
import { spawn } from "node:child_process";

const __filename = fileURLToPath(import.meta.url);
const projectRoot = path.resolve(path.dirname(__filename), "..");
const standaloneRoot = path.join(projectRoot, ".next", "standalone", "frontend");
const standaloneServer = path.join(standaloneRoot, "server.js");
const port = Number.parseInt(process.env.STANDALONE_VERIFY_PORT || "3102", 10);
const baseUrl = `http://127.0.0.1:${port}`;

function request(url) {
  return new Promise((resolve, reject) => {
    const requestHandle = http.get(url, (response) => {
      const chunks = [];
      response.on("data", (chunk) => chunks.push(chunk));
      response.on("end", () => {
        resolve({
          statusCode: response.statusCode || 0,
          headers: response.headers,
          body: Buffer.concat(chunks).toString("utf8"),
        });
      });
    });
    requestHandle.setTimeout(3_000, () => requestHandle.destroy(new Error(`Timed out requesting ${url}`)));
    requestHandle.on("error", reject);
  });
}

async function waitForHealthyServer() {
  const deadline = Date.now() + 30_000;
  let lastError = "server did not respond";
  while (Date.now() < deadline) {
    try {
      const response = await request(`${baseUrl}/api/health`);
      if (response.statusCode === 200) {
        return;
      }
      lastError = `health status=${response.statusCode}`;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Standalone server did not become healthy: ${lastError}`);
}

function pathsFromHtml(html, expression) {
  return [...html.matchAll(expression)].map((match) => match[1]);
}

async function assertAssetPaths(html, expression, expectedType, label) {
  const assetPaths = pathsFromHtml(html, expression);
  if (assetPaths.length === 0) {
    throw new Error(`Standalone page did not reference any ${label} assets.`);
  }

  for (const assetPath of assetPaths) {
    const response = await request(new URL(assetPath, `${baseUrl}/`).toString());
    const contentType = String(response.headers["content-type"] || "");
    if (response.statusCode !== 200 || !contentType.includes(expectedType)) {
      throw new Error(
        `Standalone ${label} asset failed: path=${assetPath}, status=${response.statusCode}, content-type=${contentType || "missing"}`,
      );
    }
  }
}

async function stopProcess(child) {
  if (child.exitCode !== null || child.killed) {
    return;
  }
  await new Promise((resolve) => {
    const timeout = setTimeout(resolve, 5_000);
    child.once("exit", () => {
      clearTimeout(timeout);
      resolve();
    });
    child.kill("SIGTERM");
  });
}

if (!existsSync(standaloneServer)) {
  throw new Error("Standalone server bundle not found. Run `npm run build` first.");
}

const standaloneProcess = spawn(process.execPath, [standaloneServer], {
  cwd: standaloneRoot,
  env: {
    ...process.env,
    HOSTNAME: "127.0.0.1",
    PORT: String(port),
  },
  stdio: "inherit",
});

try {
  await waitForHealthyServer();
  const homepage = await request(`${baseUrl}/`);
  if (homepage.statusCode !== 200) {
    throw new Error(`Standalone homepage failed with status=${homepage.statusCode}.`);
  }
  await assertAssetPaths(homepage.body, /href="([^"?]+\.css(?:\?[^\"]*)?)"/g, "text/css", "stylesheet");
  await assertAssetPaths(homepage.body, /src="([^"?]+\.js(?:\?[^\"]*)?)"/g, "javascript", "JavaScript");
  console.log("Standalone asset delivery verified.");
} finally {
  await stopProcess(standaloneProcess);
}
