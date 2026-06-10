import { existsSync, readFileSync } from "fs";
import { join } from "path";
import { $ } from "bun";

const ROOT = import.meta.dir;
const VENV_DIR = join(ROOT, ".venv");
const VENV_PYTHON =
  process.platform === "win32"
    ? join(VENV_DIR, "Scripts", "python.exe")
    : join(VENV_DIR, "bin", "python");
const VENV_PIP =
  process.platform === "win32"
    ? join(VENV_DIR, "Scripts", "pip.exe")
    : join(VENV_DIR, "bin", "pip");

const PORT = process.env.PORT ?? "8000";
const HOST = process.env.HOST ?? "0.0.0.0";

function load_env_file(path: string): Record<string, string> {
  if (!existsSync(path)) return {};
  const env: Record<string, string> = {};
  for (const line of readFileSync(path, "utf8").split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    env[trimmed.slice(0, eq).trim()] = trimmed.slice(eq + 1).trim();
  }
  return env;
}

async function ensure_venv() {
  if (!existsSync(VENV_PYTHON)) {
    console.log("Creating Python venv at .venv …");
    await $`python3 -m venv ${VENV_DIR}`.cwd(ROOT);
  }

  console.log("Installing Python dependencies …");
  await $`${VENV_PIP} install -r requirements.txt -q`.cwd(ROOT);
}

async function main() {
  await ensure_venv();

  const env = {
    ...process.env,
    ...load_env_file(join(ROOT, ".env")),
    ...load_env_file(join(ROOT, ".env.local")),
    PORT,
    HOST,
  };

  console.log("");
  console.log("  Pitch Engine");
  console.log(`  UI + API  →  http://localhost:${PORT}`);
  console.log(`  API docs  →  http://localhost:${PORT}/docs`);
  console.log("");

  // FastAPI serves the static UI and the API from one process.
  const proc = Bun.spawn(
    [
      VENV_PYTHON,
      "-m",
      "uvicorn",
      "main:app",
      "--host",
      HOST,
      "--port",
      PORT,
      "--reload",
    ],
    {
      cwd: ROOT,
      env,
      stdout: "inherit",
      stderr: "inherit",
      stdin: "inherit",
    },
  );

  process.on("SIGINT", () => proc.kill());
  process.on("SIGTERM", () => proc.kill());

  await proc.exited;
  process.exit(proc.exitCode ?? 0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
