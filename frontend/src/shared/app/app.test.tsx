import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./app";

describe("应用占位", () => {
  it("明确说明业务 API 尚未接入且不伪造任务成功", () => {
    render(<App />);
    expect(screen.getByText("工程骨架已启动")).toBeInTheDocument();
    expect(screen.getByText(/不会创建或模拟修复任务/)).toBeInTheDocument();
  });
});
