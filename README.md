# 岚桥实验放量台 · LIFT LAB

把用户级随机实验从假设登记、异步统计分析连接到放量会议结论，保留可复算的证据。

## 场景与工作流

模拟客户为岚桥内容科技的 32 人增长团队。原流程从埋点导出 CSV，在表格里手算显著性，再把结论贴到会议纪要。前置收入差异、p 值误读和无法追溯的复算是三个主要痛点。上游为用户级随机分桶观测，下游为产品放量会议；本项目替代中间的分析、证据导出和结论归档。

演示数据为固定随机种子 42 生成的合成数据，2400 位独立用户，1:1 分组，前置和后置各 7 日收入。仅供演示，不是实际客户资料。三个演示假设复用同一数据以便体验，不能视作三个独立实验。

| 角色 | 页面 | 权限 | 典型动作 |
|---|---|---|---|
| admin | 全部六页 | 读、登记、运行、归档结论 | 实验负责人作会议结论 |
| analyst | 全部六页 | 读、登记、运行 | 分析师准备区间与导出 |
| viewer | 全部六页 | 只读与导出 | 产品观察员阅读证据 |

## 快速启动

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
docker compose exec -T backend python -m scripts.seed_demo
```

访问 [前端](http://localhost:18200)；[后端接口文档](http://localhost:19200/docs)。Nginx 将 `/api/` 去掉后代理到后端，直接访问后端不加 `/api` 前缀。

| 账号 | 密码 | 角色 |
|---|---|---|
| admin@lanqiao.demo | Lanqiao2026! | admin |
| analyst@lanqiao.demo | Lanqiao2026! | analyst |
| viewer@lanqiao.demo | Lanqiao2026! | viewer |

首次启动自动 seed（`SEED_DEMO=true`），失败记日志而不阻断服务。再次执行根据用户邮箱、数据集名称、实验名查重，不覆盖已经存在的行。数据库通过 ORM metadata 首次建表；`backend/migrations/` 提供索引与版本迁移脚本。启动只执行只增不删的兼容升级（补列、把旧观测归入 v1），其余结构修改仍需审查迁移。

## 一天的研究剧本

1. 09:00 林序以 admin 登录，检查 `lanqiao-paywall-2026-11.csv` 的 2400 条观测和校验和。
2. 09:05 林序在观测数据页上传新导出的 CSV，页面校验后发布 v2；若与已发布内容一致（即使行序不同）只记录一次重复导入，不新增版本。
3. 09:10 许禾以 analyst 登录，在实验配置登记“短文付费入口 v4”，并选定观测版本 v2。
4. 选择已冻结的付费入口数据，写明可检验的业务假设。
5. 固定收入指标、α=.05，打开 CUPED 校正，提交分析。
6. 后台 worker 从 Redis 队列取任务，使用 Python 计算 Welch 与 CUPED 结果；任务固定读取登记时的观测版本，v1 上的旧实验仍用原观测复算。
7. 09:15 在分析结果检查 1200/1200 样本量、p 值、区间和方差降低，并导出 CSV。
8. 周澄以 viewer 阅读同一证据；登记接口和归档接口均会拒绝该角色。
9. 10:00 林序记录“同意放量/继续观察/暂缓上线”及至少 8 字依据，在操作留痕追溯动作。

## 观测导入与数据集版本

观测数据页支持从浏览器直接导入 CSV，不再依赖 seed。每次成功导入会发布一个不可变的 `DatasetVersion`，观测行按版本隔离保存。

- **列**：`subject, arm, pre_value, value`，也接受 `user/group/pre/revenue` 与中文表头；分组接受 `control/treatment/对照组/候选组`。UTF-8（含 BOM）优先，无法解码时回退 GB18030。
- **去重**：同一匿名样本在同一批次内内容完全相同（分组、前置、后置数值一致）只保留一行，首行行号用于追溯；版本记录保留 `rows_received / rows_unique / duplicates_removed`。
- **冲突**：同一样本重复出现但分组或数值不同，整批拒绝，不写入任何观测；接口返回 `422` 和逐行错误（文件行号、样本、原因），导入记录同样可查。
- **幂等**：内容校验和按样本排序后计算，因此换行序重传识别为同一内容，返回 `200 + status=duplicate`，不新增版本；`409` 仅保留给并发发布冲突。
- **版本固定**：实验登记时必须选定版本（默认最新）；`analysis_runs` 记录入队时固定的版本，worker 只读该版本，新上传不会改变旧实验的复算依据。观测页展示每个版本被哪些实验登记使用。
- **权限**：admin / analyst 可导入与建数据集，viewer 只读。
- **接口**：`POST /datasets/{id}/import`（multipart：`file`、可选 `description`）、`GET /datasets/{id}/versions`、`GET /datasets/{id}/imports`、`GET /datasets/{id}/usage`、`GET /datasets/{id}/observations?version=N`。

已有数据库启动时会做增量升级：新增版本/导入表与版本列，把旧观测归入 v1，并替换旧的 `(dataset_id, subject)` 唯一约束（见 `backend/migrations/002_dataset_versions.sql`）。

## 计算口径

- **Welch t 检验**：输入用户级后置收入与分组；差异为候选均值减对照均值。标准误 `sqrt(sA²/nA+sB²/nB)`，Welch–Satterthwaite 自由度，使用 SciPy Student t 双侧尾概率和 `1-alpha` 区间。输出两组均值、样本量、差异、自由度、标准误、p 值和上下界。
- **CUPED**：输入分桶前协变量 X 与后置收入 Y；合并样本估计 `theta=cov(Y,X)/var(X)`，计算 `Y_adj=Y-theta*(X-mean(X))` 后再做 Welch。输出原始与校正结果，方差降低口径为 `1-SE_adj²/SE_raw²`（可能为负），不把它解释为业务增长。
- 至少每组 3 人；非有限值、空集、未知分组、组内零方差拒绝；启用 CUPED 时前置指标常量拒绝。固定种子、持久化观测与 SHA256 使结果可复算。算法见 `backend/src/services/statistics_service.py`。
- 假设用户独立随机分桶、协变量在分桶前取得；只支持单个预注册指标，未做序贯检验、多重比较、离群值稳健估计或聚类相关性校正。95% 区间仅在 α=.05 时成立，结果页按实际 alpha 标注。

## 功能与工程结构

六页：实验概览、观测数据（版本历史、导入记录、前100条预览）、实验配置（选择观测版本）、分析结果（真实 SVG 区间图，标注复算版本）、决策档案、操作留痕。实体 Dataset / DatasetVersion / DatasetImport / Observation / Experiment / AnalysisRun / Decision 各有数据模型与 API；API、前端 store、组件职责分开。

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11、FastAPI、SQLAlchemy、SciPy / NumPy |
| 前端 | React 18、TypeScript、Vite、Lucide、Noto Serif SC + Noto Sans SC |
| 持久化 | PostgreSQL 16、Redis 7 AOF |
| 交付 | 恰好 5 个 Compose 服务，Nginx SPA 回落 |

```
backend/src/{models,schemas,services,controllers,routes,middlewares,utils,constants,config}
backend/src/{main.py,worker.py}
backend/scripts/seed_demo.py
backend/tests/
backend/migrations/{001_initial,002_dataset_versions}.sql
frontend/src/{api,stores,types,components,hooks,pages,router,utils,constants}
```

后端 JWT 有效期 8 小时，PBKDF2-SHA256 存储密码；角色每次由数据库读取，不信任前端。审计覆盖登录、登记、运行完成和决策。两个独立中间件处理全局错误与登录频率限制（单进程内每 IP 每分钟30次）。文件导出需要认证。

共享枚举：角色位于 `backend/src/constants/roles.py` / `frontend/src/constants/enums.ts`，任务状态位于 `backend/src/constants/status.py` / `frontend/src/constants/enums.ts`；后端服务持久化与接口使用同名值。`ExperimentSummary` 在概览、结果与决策页共用，`DataTable`、`StatusBadge`、`Notice` 提供一致交互。

## 环境变量与 Docker

| 变量 | 默认值 | 说明 |
|---|---|---|
| COMPOSE_PROJECT_NAME | lift-lab | 容器和网络命名空间 |
| FRONTEND_PORT | 18200 | Nginx 前端 |
| BACKEND_PORT | 19200 | FastAPI |
| DB_PORT | 17700 | PostgreSQL 宿主映射 |
| JWT_SECRET | local-demo-lift-lab-change-this-key | 本地演示签名密钥，部署前更换 |
| SEED_DEMO | true | 后端启动时 seed |

命名卷 `db-data`、`redis-data`、`artifacts`；backend/worker 共享产物卷。worker 使用2秒阻塞轮询并持续写心跳；5个容器均有健康检查。后端等待 db/redis healthy，前端等待 backend healthy。单 worker 运行；进程意外退出时已标为 running 的任务需要人工重新提交，本地演示未提供自动重试。停止并清空本项目数据：

```bash
docker compose down -v --remove-orphans
```

## 本地开发与验证

安装 Python 3.11，`pip install -r backend/requirements.txt`（含 `python-multipart` 以支持页面上传）；将 `DATABASE_URL` / `REDIS_URL` 指向本机依赖，`cd backend && uvicorn src.main:app --reload`。前端 `cd frontend && npm install && npm run dev`；开发时需为 `/api` 配置反向代理到本地后端。标准启动以 Compose 为准。

后端测试（内存 SQLite，不依赖 Postgres/Redis）：`cd backend && python -m pytest tests -q`。覆盖解析去重与冲突行号、换序重传幂等、版本发布、实验固定版本与旧实验复算、multipart 接口与权限。

测试脚本、截图和真实结果在项目外 `../../test-artifacts/gb-0001/`。日志与 `.env` 不提交。该应用适合本地合成数据研究；不包含邮件外发、生产级多实例限流或任务恢复。CSV 导入限制为 20MB 并逐行校验。

## License

MIT，详见 LICENSE。
