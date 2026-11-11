# 招聘信息助手

上传招聘 Markdown、TXT 或 PDF 后，可以查询岗位细节、比较不同公司的要求，也可以用自然语言筛选结构化岗位。

这是面向求职场景的本地演示项目。完整流程、技术边界及验收记录见 [项目交付说明](docs/项目交付说明.md)。

![岗位筛选与资料缺失时的回答](docs/demo-v1.jpg)

| 用户问题 | 查询方式 |
| --- | --- |
| 睿联技术的嵌入式软件开发工程师在哪个城市，招哪一届？ | BGE 生成向量，Chroma 检索文档，DeepSeek 依据检索片段回答 |
| 筛选合肥实习时长不超过 3 个月的岗位 | DeepSeek 生成 `search_jobs` 的筛选参数，FastAPI 执行参数化 SQLite 查询，再把结果交给模型整理 |

网页支持批量上传、展开检索片段、显示 SQLite 筛选结果。当前的 32 份样例包括 30 份招聘公告快照和 2 份实习岗位说明。每份匹配格式的 Markdown 对应一条 SQLite 记录。公告列出多个岗位和地点时，记录保留原文与对应关系说明。

## 本地启动

需要 [uv](https://docs.astral.sh/uv/getting-started/installation/) 和满足 [前端 package.json](frontend/package.json) 中 `engines.node` 要求的 Node.js。uv 可以为项目准备 Python 3.12。

在项目根目录新建 `.env`，设置 `DEEPSEEK_API_KEY`。模型默认使用 `deepseek-flash`，可以用 `DEEPSEEK_MODEL` 指定支持工具调用的 DeepSeek 模型。[DeepSeek 工具调用文档](https://api-docs.deepseek.com/guides/tool_calls/)

在项目根目录运行以下 PowerShell 命令。

```powershell
uv venv --python 3.12
uv pip install --python .\.venv\Scripts\python.exe -r requirements-lock.txt
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

已有 `.venv` 时可以从安装依赖的命令开始。首次启动会加载本地 BGE 模型，缓存缺失时会下载模型。构建完成后，FastAPI 在 [http://127.0.0.1:8000](http://127.0.0.1:8000) 提供 Vue 页面。开发时可另开终端运行 `npm.cmd --prefix frontend run dev`，由 Vite 代理 API。

环境准备完成后，日常可双击根目录的 `start.cmd`，等窗口显示 `Application startup complete` 后打开网页。保持窗口开启，按 `Ctrl+C` 停止。已有服务占用 8000 端口时，直接使用现有页面，不要重复启动。修改前端后需重新构建并重启服务。

`requirements-lock.txt` 是本机 Windows / Python 3.12 的已安装版本快照，包含测试依赖；未验证其他操作系统。`requirements.txt` 保留直接依赖列表。若 `uv` 不在 PATH，使用已安装 uv 的系统 Python 执行 `python -m uv` 替代；不要在未安装 uv 的虚拟环境中执行该替代命令。

## 演示步骤

1. 在页面批量上传 [samples](samples) 下的 Markdown。全新知识库导入 32 份后，左侧会列出对应文件。上传同名文件会更新索引。
2. 问「睿联技术的嵌入式软件开发工程师在哪个城市，招哪一届？」。预期回答深圳、2027 届，可展开检索片段核对。
3. 问「筛选合肥的实习岗位，实习时长不超过 3 个月」。预期只返回美的冰箱事业部，实习 3 个月、每周 4 天。也可以在 [FastAPI 接口文档](http://127.0.0.1:8000/docs) 中直接试用 `GET /api/jobs`。
4. 问「美的冰箱事业部这个 AI 实习岗位提供住宿吗？」。预期提示资料未提供或无法确认。

`app/rag.py` 负责 Chroma 检索和 DeepSeek 调用，`app/jobs.py` 负责从岗位 Markdown 提取字段并查询 SQLite，`frontend/src/App.vue` 负责上传和结果展示。SQLite 在启动、上传和清空时与当前 Chroma 集合中的文档同步。上传文件、向量库和 SQLite 数据库保存在本地 `data` 目录。

结构化筛选依赖 Markdown 中可提取的字段。实习时长未注明的记录不会匹配时长上限。样例的招聘状态是采集时的记录，投递前以官方渠道为准。

## 验证与演示资料

在根目录运行 `verify.cmd`，执行离线回归测试及 Vue 类型检查、生产构建。测试使用临时数据库和替代模型，不修改日常知识库，不调用付费 API。

服务启动且已导入样例后，可运行下面的真实问答检查。它会正常消耗已配置 DeepSeek API 的额度，结果保存到本地 `data/reports/demo-evaluation.json`，不进入 Git。

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_demo.py
```

上传限制为单文件 10 MB。TXT / Markdown 使用 UTF-8 编码，PDF 需有可提取文本；扫描版需先 OCR。清空功能删除当前 Chroma 与 SQLite 索引，保留 `data/docs` 下原始文件和 `samples` 样例。重启不会自动重新导入已清空的资料。聊天记录仅在当前页面保留。

模型只获得问题、检索片段或查询结果。网页不接触 API 密钥。请仅在本机运行本演示服务；尚未实现登录、用户隔离或公网部署。

本项目基于 [Sunruising/rag-knowledge-base-qa](https://github.com/Sunruising/rag-knowledge-base-qa) 改造，按 [MIT 许可证](LICENSE) 分发。[上游英文说明](README.en.md)
