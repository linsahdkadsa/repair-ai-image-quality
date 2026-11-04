import { createHash } from "node:crypto";
import { readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

function sha256(file) {
  return createHash("sha256").update(readFileSync(file)).digest("hex").toUpperCase();
}

function readJson(root, relative, errors) {
  try {
    return JSON.parse(readFileSync(path.join(root, relative), "utf8"));
  } catch (error) {
    errors.push(`${relative}: 无法读取 JSON (${error.message})`);
    return null;
  }
}

function verifyOutputs(root, handoff, label, errors) {
  if (!Array.isArray(handoff.outputs) || handoff.outputs.length === 0) {
    errors.push(`${label}: outputs 不能为空`);
    return;
  }
  for (const output of handoff.outputs) {
    if (!output.path || !output.sha256) {
      errors.push(`${label}: 输出缺少 path 或 sha256`);
      continue;
    }
    const absolute = path.resolve(root, output.path);
    if (!absolute.startsWith(`${path.resolve(root)}${path.sep}`)) {
      errors.push(`${label}: 输出路径越出项目根目录: ${output.path}`);
      continue;
    }
    const stats = statSync(absolute, { throwIfNoEntry: false });
    if (!stats?.isFile()) {
      errors.push(`${label}: 缺少输出 ${output.path}`);
      continue;
    }
    if (output.bytes !== undefined && stats.size !== output.bytes) errors.push(`${label}: 字节数不符 ${output.path}`);
    if (sha256(absolute) !== output.sha256.toUpperCase()) errors.push(`${label}: SHA-256 不符 ${output.path}`);
  }
}

export function checkHandoff(root, phase) {
  const errors = [];
  const current = readJson(root, `docs/handoffs/${phase}.json`, errors);
  if (!current) return errors;
  if (current.phase !== phase) errors.push(`${phase}: phase 不匹配`);
  if (!String(current.status).startsWith("accepted")) errors.push(`${phase}: 交接状态未接受`);
  if (phase === "P02") {
    for (const previousPhase of ["P00", "P01"]) {
      const previous = readJson(root, `docs/handoffs/${previousPhase}.json`, errors);
      if (!previous) continue;
      if (!String(previous.status).startsWith("accepted")) errors.push(`${previousPhase}: 前置阶段未接受`);
      verifyOutputs(root, previous, previousPhase, errors);
    }
    if (current.previousHandoff !== "docs/handoffs/P01.json") errors.push("P02: previousHandoff 必须指向 P01");
  }
  verifyOutputs(root, current, phase, errors);
  for (const check of current.verification ?? []) {
    if (check.exitCode !== 0) errors.push(`${phase}: 验证未通过: ${check.command}`);
    if (!check.report) {
      errors.push(`${phase}: 验证缺少 report: ${check.command}`);
      continue;
    }
    const report = path.resolve(root, check.report);
    if (!report.startsWith(`${path.resolve(root)}${path.sep}`)) {
      errors.push(`${phase}: 验证报告路径越出项目根目录: ${check.report}`);
      continue;
    }
    if (!statSync(report, { throwIfNoEntry: false })?.isFile()) {
      errors.push(`${phase}: 缺少验证报告 ${check.report}`);
    }
  }
  return errors;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const phase = process.argv[2];
  if (!/^P\d{2}$/.test(phase ?? "")) {
    console.error("用法: npm run check:handoff -- P02");
    process.exit(2);
  }
  const root = fileURLToPath(new URL("../", import.meta.url));
  const errors = checkHandoff(root, phase);
  if (errors.length) {
    console.error(errors.join("\n"));
    process.exit(1);
  }
  console.log(`${phase} 交接文件及其前置产物校验通过`);
}
