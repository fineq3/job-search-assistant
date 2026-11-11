"""Run five live demo questions against an already running local server.

Uses the server's configured DeepSeek API and incurs normal API usage.
Does not upload, delete, reset, or modify the existing knowledge base.
"""
import json
from datetime import datetime
from pathlib import Path
import re
import sys
from time import perf_counter
import httpx

CASES = [
    ('single_company', '睿联技术的嵌入式软件开发工程师在哪个城市，招哪一届？', 'rag', ['深圳', '2027']),
    ('compare', '美的冰箱事业部和宝尊电商的 AI 实习岗位，每周分别到岗几天，各实习多久？', 'rag',
     ['美的', '宝尊', '[4四]', '[3三]', '[5五]', '[6六]']),
    ('missing_information', '美的冰箱事业部这个 AI 实习岗位提供住宿吗？', 'rag',
     ['未|没有|无法|不确定|不清楚']),
    ('filter', '筛选合肥的实习岗位，实习时长不超过 3 个月', 'jobs', ['美的']),
    ('no_match', '筛选合肥的实习岗位，实习时长不超过 2 个月', 'jobs', ['无|没有|未']),
]


def main():
    results = []
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=90.0, trust_env=False) as client:
        try:
            status = client.get('/api/status')
            status.raise_for_status()
        except httpx.HTTPError:
            print('Local server is unavailable. Start start.cmd and wait for Application startup complete.')
            return 1
        for name, question, mode, patterns in CASES:
            started = perf_counter()
            try:
                response = client.post('/api/ask', json={'question': question})
                response.raise_for_status()
                data = response.json()
                checks = [data.get('mode') == mode,
                          all(re.search(pattern, data.get('answer', '')) for pattern in patterns)]
                if mode == 'rag':
                    checks.append(bool(data.get('sources')))
                elif name == 'filter':
                    checks.append([job['company'] for job in data.get('jobs', [])] == ['美的冰箱事业部'])
                else:
                    checks.append(data.get('jobs') == [])
                record = {'id': name, 'question': question, 'passed': all(checks), 'response': data}
            except (httpx.HTTPError, ValueError) as error:
                record = {'id': name, 'question': question, 'passed': False, 'error': str(error)}
            record['seconds'] = round(perf_counter() - started, 2)
            results.append(record)
            print(f"{name}: {'PASS' if record['passed'] else 'FAIL'} ({record['seconds']}s)", flush=True)
    target = Path(__file__).resolve().parents[1] / 'data' / 'reports' / 'demo-evaluation.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'tested_at': datetime.now().astimezone().isoformat(),
                                 'knowledge_base': status.json(), 'cases': results}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Report: {target}')
    print('These are smoke checks; review the full answers and sources in the report.')
    return 0 if all(case['passed'] for case in results) else 1


if __name__ == '__main__':
    sys.exit(main())
