import { spawn, spawnSync } from "node:child_process";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));

export function getDevCommands(projectRoot = root) {
  const pythonRunner = fileURLToPath(new URL("./run-python.mjs", import.meta.url));
  const vite = fileURLToPath(new URL("../node_modules/vite/bin/vite.js", import.meta.url));
  return [
    {
      file: process.execPath,
      args: [vite, "--host", "127.0.0.1", "--port", "3000", "--strictPort"],
      cwd: path.join(projectRoot, "frontend"),
    },
    {
      file: process.execPath,
      args: [pythonRunner, "-m", "uvicorn", "api.app:app", "--app-dir", "src", "--host", "127.0.0.1", "--port", "8000"],
      cwd: projectRoot,
    },
  ];
}

export async function assertPortAvailable(port, host = "127.0.0.1") {
  await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", (error) => {
      if (error.code === "EADDRINUSE") reject(new Error(`端口 ${port} 已被占用`));
      else reject(error);
    });
    server.listen(port, host, () => server.close(resolve));
  });
}

function terminate(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  if (process.platform === "win32" && child.pid) {
    spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore", windowsHide: true });
  } else {
    child.kill("SIGTERM");
  }
}

export function runManaged(commands, spawnProcess = spawn) {
  const children = [];
  let stopping = false;
  let settled = false;

  return new Promise((resolve) => {
    const stop = (code = 0) => {
      if (stopping) return;
      stopping = true;
      for (const child of children) terminate(child);
      const finish = () => {
        if (!settled && children.every((child) => child.exitCode !== null || child.signalCode !== null)) {
          settled = true;
          resolve(code);
        }
      };
      for (const child of children) child.once("exit", finish);
      finish();
    };

    for (const command of commands) {
      const child = spawnProcess(command.file, command.args, {
        cwd: command.cwd,
        stdio: "inherit",
        windowsHide: true,
        shell: false,
      });
      children.push(child);
      child.once("error", () => stop(1));
      child.once("exit", (code, signal) => {
        if (!stopping) stop(code ?? (signal ? 1 : 0));
      });
    }

    process.once("SIGINT", onInterrupt);
    process.once("SIGTERM", onInterrupt);
    function onInterrupt() {
      stop(0);
    }
  });
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  try {
    await assertPortAvailable(3000);
    await assertPortAvailable(8000);
  } catch (error) {
    console.error(error.message);
    process.exit(1);
  }
  const code = await runManaged(getDevCommands());
  process.exit(code);
}
