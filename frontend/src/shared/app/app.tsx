import { Alert, ConfigProvider, Layout, Typography } from "antd";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import styles from "./app.module.css";

const router = createBrowserRouter([
  {
    path: "*",
    element: (
      <Layout className={styles.shell}>
        <main className={styles.content}>
          <Typography.Title level={2}>Repair AI Image</Typography.Title>
          <Alert
            type="info"
            showIcon
            message="工程骨架已启动"
            description="业务页面将在后续阶段接入真实 API；当前不会创建或模拟修复任务。"
          />
        </main>
      </Layout>
    ),
  },
]);

export function App() {
  return (
    <ConfigProvider>
      <RouterProvider router={router} />
    </ConfigProvider>
  );
}
