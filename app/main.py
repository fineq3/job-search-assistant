"""
FastAPI 后端：把 RAG 能力包成网页可调用的接口，并托管前端页面。

启动后访问 http://127.0.0.1:8000 即可使用。
"""

from pathlib import Path
from contextlib import asynccontextmanager
from tempfile import TemporaryDirectory
from threading import Lock
from typing import Annotated

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAIError
from pydantic import BaseModel, Field
from pypdf.errors import PdfReadError

load_dotenv()  # 读取 .env 里的 DEEPSEEK_API_KEY

from app.rag import RagEngine, DATA_DIR, LLMConfigurationError  # noqa: E402
from app.jobs import JobFilters, JobStore  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"
FRONTEND_DIST = STATIC_DIR.parent.parent / "frontend" / "dist"
DOCS_DIR = DATA_DIR / "docs"
DOCS_DIR.mkdir(parents=True, exist_ok=True)

# RAG 引擎只初始化一次（加载 embedding 模型较慢，常驻）
engine: RagEngine
job_store: JobStore
ingest_lock = Lock()
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _rebuild_jobs():
    sources = engine.status()["docs"]
    job_store.rebuild(DOCS_DIR / name for name in sources if Path(name).name == name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine, job_store
    engine = RagEngine()
    job_store = JobStore(DATA_DIR / "jobs.sqlite3")
    _rebuild_jobs()
    yield


app = FastAPI(title="招聘信息助手", version="1.0.0", lifespan=lifespan)


class AskBody(BaseModel):
    question: str = Field(max_length=2000)


@app.get("/api/status")
def status():
    return engine.status()


@app.get("/api/jobs")
def list_jobs(filters: Annotated[JobFilters, Query()]):
    return job_store.search(filters)


@app.post("/api/upload")
def upload(file: UploadFile = File(...)):
    filename = file.filename
    if not filename or Path(filename).name != filename or any(c in filename for c in "/\\:"):
        raise HTTPException(400, "文件名无效")
    suffix = Path(filename).suffix.lower()
    if suffix not in (".txt", ".md", ".pdf"):
        raise HTTPException(400, "只支持 .txt / .md / .pdf")
    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "单个文件不能超过 10 MB")
    with ingest_lock, TemporaryDirectory(dir=DOCS_DIR) as staging_dir:
        staged_file = Path(staging_dir) / filename
        staged_file.write_bytes(content)
        try:
            chunks = engine.ingest_file(staged_file)
        except UnicodeDecodeError as error:
            raise HTTPException(400, "文本编码无法识别，请另存为 UTF-8 后上传。") from error
        except PdfReadError as error:
            raise HTTPException(400, "PDF 无法读取，请确认文件完整且未加密。") from error
        if not chunks:
            raise HTTPException(400, "未提取到文本。扫描版 PDF 需先进行文字识别。")
        staged_file.replace(DOCS_DIR / filename)
        _rebuild_jobs()
    return {"filename": filename, "chunks": chunks}


@app.post("/api/ask")
def ask(body: AskBody):
    q = body.question.strip()
    if not q:
        raise HTTPException(400, "问题不能为空")
    try:
        return engine.answer(q, job_store)
    except LLMConfigurationError as error:
        raise HTTPException(503, str(error)) from error
    except OpenAIError as error:
        raise HTTPException(502, "DeepSeek 请求失败，请检查 API 配置或稍后重试。") from error


@app.post("/api/reset")
def reset():
    with ingest_lock:
        engine.reset()
        job_store.rebuild(())
    return {"ok": True}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if (FRONTEND_DIST / "index.html").is_file():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
else:
    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")
