import { existsSync } from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const python = fileURLToPath(new URL("../backend/.venv/Scripts/python.exe", import.meta.url));

if (!existsSync(python)) {
  console.error("Python 环境尚未准备。请运行：python -m venv backend/.venv，然后使用 uv 安装 backend/requirements.lock");
  process.exit(2);
}

const result = spawnSync(python, process.argv.slice(2), {
  cwd: fileURLToPath(new URL("../backend/", import.meta.url)),
  env: {
    ...process.env,
    PYTHONPATH: [fileURLToPath(new URL("../backend/src/", import.meta.url)), process.env.PYTHONPATH]
      .filter(Boolean)
      .join(path.delimiter),
  },
  stdio: "inherit",
  windowsHide: true,
});

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 1);
