import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import net from "node:net";
import path from "node:path";
import { assertPortAvailable, getDevCommands, runManaged } from "./dev.mjs";

test("dev launcher starts Vite from the frontend directory", () => {
  const projectRoot = path.resolve("C:/workspace");
  const commands = getDevCommands(projectRoot);
  assert.equal(commands[0].cwd, path.join(projectRoot, "frontend"));
  assert.equal(commands[1].cwd, projectRoot);
});

test("占用端口会被明确拒绝", async () => {
  const server = net.createServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  try {
    await assert.rejects(assertPortAvailable(port), new RegExp(`端口 ${port} 已被占用`));
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test("任一子进程异常退出后会终止其余进程且不用 shell", async () => {
  const spawned = [];
  const spawnFake = (file, args, options) => {
    const child = new EventEmitter();
    child.exitCode = null;
    child.signalCode = null;
    child.kill = () => {
      child.exitCode = 0;
      queueMicrotask(() => child.emit("exit", 0, null));
    };
    spawned.push({ child, file, args, options });
    return child;
  };
  const running = runManaged([
    { file: "node", args: ["api"], cwd: "." },
    { file: "node", args: ["ui"], cwd: "." },
  ], spawnFake);
  assert.equal(spawned.length, 2);
  assert.ok(spawned.every(({ options }) => options.shell === false));
  spawned[0].child.exitCode = 1;
  spawned[0].child.emit("exit", 1, null);
  assert.equal(await running, 1);
  assert.equal(spawned[1].child.exitCode, 0);
});
