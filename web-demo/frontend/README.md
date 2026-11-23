<!-- 文件用途：说明宠物壁纸网页 Demo 前端结构、开发构建与测试命令。 -->

# 网页 Demo 前端

本目录基于 Vue 3 + TypeScript + Vite 实现横屏车机宠物壁纸交互 Demo，严格隔离系统控件层、模式控件层与 16:9 壁纸画布层，并将生成任务轮询状态与壁纸播放器状态解耦。

## 目录结构

- [`src/lib/hotzone.ts`](src/lib/hotzone.ts)：16:9 画面归一化坐标计算（`<34%` 左区、`34%–<66%` 中区、`66%–100%` 右区、留黑区拦截）
- [`src/lib/api.ts`](src/lib/api.ts)：后端 REST API 客户端与幂等键生成
- [`src/lib/preload.ts`](src/lib/preload.ts)：壁纸图片解码与视频元数据预加载校验
- [`src/stores/`](src/stores/)：`systemStore`、`petStore`、`playerStore` 与 `generationStore`
- [`src/views/`](src/views/)：欢迎页、首页常态、物种选择、照片录入、过场等待（3 秒先导 + 7 秒循环）与壁纸舞台
- [`src/components/`](src/components/)：顶栏系统控件、最高优先级驾驶安全提醒、演示验收抽屉、选宠与信息编辑弹窗

## 安装、开发与测试

```bash
cd web-demo/frontend
npm install
npm run dev      # 开发模式（端口 5173，/api 代理到 127.0.0.1:8080）
npm run test     # Vitest 单元测试
npm run typecheck
npm run build    # 构建产物输出到 dist/ 供 FastAPI 同源托管
```
