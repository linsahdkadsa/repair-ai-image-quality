import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const generated = path.join(root, "frontend/src/shared/api/generated.ts");

const temporary = mkdtempSync(path.join(os.tmpdir(), "rai-openapi-"));
try {
  const exportResult = spawnSync(process.execPath, ["tools/run-python.mjs", "-m", "api.export_openapi"], {
    cwd: root,
    stdio: "inherit",
    windowsHide: true,
  });
  if (exportResult.status !== 0) throw new Error("OpenAPI 导出失败");
  const typescript = spawnSync(process.execPath, [
    "node_modules/openapi-typescript/bin/cli.js",
    "backend/openapi.json",
    "-o",
    path.join(temporary, "generated.ts"),
  ], { cwd: root, stdio: "inherit", windowsHide: true });
  if (typescript.status !== 0) throw new Error("OpenAPI TypeScript 生成失败");
  const current = readFileSync(generated, "utf8").replaceAll("\r\n", "\n");
  const expected = readFileSync(path.join(temporary, "generated.ts"), "utf8").replaceAll("\r\n", "\n");
  if (current !== expected) {
    console.error("OpenAPI 类型已漂移，请运行 npm run api:generate 并检查 diff");
    process.exitCode = 1;
  } else {
    console.log("OpenAPI 类型与生成文件一致");
  }
} finally {
  rmSync(temporary, { recursive: true, force: true });
}
