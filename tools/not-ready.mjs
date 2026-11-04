const feature = process.argv[2] ?? "检查";
const phase = process.argv[3] ?? "后续阶段";
console.error(`${feature} 尚未在 ${phase} 实现；此命令不会以空操作报告成功。`);
process.exitCode = 2;
