"""Index structured fields from the recruitment Markdown documents."""

import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Annotated, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


SearchText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class JobFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    city: SearchText | None = Field(default=None, description="城市名称，如合肥、深圳")
    keyword: SearchText | None = Field(default=None, description="匹配公司或岗位名称中的一个关键词")
    kind: Literal["实习", "招聘公告"] | None = Field(default=None, description="招聘记录类型")
    max_duration_months: int | None = Field(default=None, ge=1, description="实习时长上限，含等于，单位为月")
    max_days_per_week: int | None = Field(default=None, ge=1, le=7, description="每周出勤天数上限，含等于")


def _parse_job(path: Path) -> dict | None:
    if path.suffix.lower() != ".md" or not path.is_file():
        return None
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    fields = {
        key.strip(): value.strip()
        for key, value in re.findall(r"(?m)^[ \t]*-[ \t]*([^：:\n]+)[：:]([^\n]*)", text)
    }
    position = fields.get("岗位名称") or fields.get("岗位") or fields.get("招聘岗位")
    location = fields.get("工作地点")
    heading = re.search(r"(?m)^#\s+(.+)", text)
    if not position or not location or not heading:
        return None

    company = fields.get("公司") or fields.get("公司 / 部门") or heading[1].split("｜", 1)[0]
    days = re.fullmatch(r"每周\s*([1-7])\s*天", fields.get("到岗要求") or fields.get("出勤要求", ""))
    months = re.fullmatch(r"([1-9][0-9]*)\s*个?月", fields.get("实习时长", ""))
    return {
        "source": path.name,
        "company": company.strip(),
        "position": position.strip(),
        "location": location.strip(),
        "kind": "实习" if "实习" in position or "实习时长" in fields else "招聘公告",
        "days_per_week": int(days[1]) if days else None,
        "duration_months": int(months[1]) if months else None,
        "eligibility": fields.get("招聘对象"),
    }


class JobStore:
    def __init__(self, path: Path):
        self.path = path
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    source TEXT PRIMARY KEY,
                    company TEXT NOT NULL,
                    position TEXT NOT NULL,
                    location TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    days_per_week INTEGER,
                    duration_months INTEGER,
                    eligibility TEXT
                )
            """)

    def rebuild(self, paths: Iterable[Path]) -> None:
        rows = [row for path in paths if (row := _parse_job(path)) is not None]
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM jobs")
            db.executemany("""
                INSERT INTO jobs (source, company, position, location, kind,
                                  days_per_week, duration_months, eligibility)
                VALUES (:source, :company, :position, :location, :kind,
                        :days_per_week, :duration_months, :eligibility)
            """, rows)

    def search(self, filters: JobFilters, limit: int = 50) -> dict:
        conditions = {
            "city": "instr(location, ?) > 0",
            "keyword": "instr(lower(company || ' ' || position), lower(?)) > 0",
            "kind": "kind = ?",
            "max_duration_months": "duration_months <= ?",
            "max_days_per_week": "days_per_week <= ?",
        }
        params = filters.model_dump(exclude_none=True)
        where = " AND ".join(conditions[key] for key in params)
        query = "SELECT * FROM jobs"
        if where:
            query += " WHERE " + where
        query += " ORDER BY company, source LIMIT ?"
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(query, [*params.values(), limit + 1]).fetchall()
        return {
            "filters": params,
            "jobs": [dict(row) for row in rows[:limit]],
            "truncated": len(rows) > limit,
        }
