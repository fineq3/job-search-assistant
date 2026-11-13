"""Offline regression checks. Temporary stores only; no paid model calls."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

import chromadb
import httpx
from fastapi.testclient import TestClient
from openai import APITimeoutError
from langchain_core.messages import AIMessage, ToolMessage
from langchain_deepseek import ChatDeepSeek
from app import main, rag
from app.jobs import JobFilters, JobStore

ROOT = Path(__file__).resolve().parents[1]
MIDEA = ROOT / 'samples' / '美的冰箱事业部-AI应用实习生.md'
BAOZUN = ROOT / 'samples' / '宝尊电商-AI应用开发实习生.md'


class FakeEmbedder:
    def __init__(self, *args):
        pass

    def encode(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class JobStoreTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = JobStore(Path(temp.name) / 'jobs.sqlite3')
        self.store.rebuild(ROOT.joinpath('samples').glob('*.md'))

    def test_numeric_boundaries_and_unknown_values(self):
        self.assertEqual(len(self.store.search(JobFilters())['jobs']), 32)
        for months, expected in [(2, []), (3, ['美的冰箱事业部']),
                                 (5, ['美的冰箱事业部']), (6, ['宝尊电商', '美的冰箱事业部'])]:
            rows = self.store.search(JobFilters(city='合肥', kind='实习', max_duration_months=months))['jobs']
            self.assertEqual(sorted(row['company'] for row in rows), expected)
        self.assertEqual(len(self.store.search(JobFilters(max_duration_months=6))['jobs']), 2)

    def test_sql_input_is_only_a_value(self):
        self.assertEqual(self.store.search(JobFilters(city="合肥' OR 1=1 --"))['jobs'], [])
        self.assertEqual(len(self.store.search(JobFilters())['jobs']), 32)

    def test_rebuild_and_truncation(self):
        self.assertTrue(self.store.search(JobFilters(), limit=1)['truncated'])
        self.store.rebuild([MIDEA])
        self.assertEqual(len(self.store.search(JobFilters())['jobs']), 1)
        self.store.rebuild([])
        self.assertEqual(self.store.search(JobFilters())['jobs'], [])


class ProjectTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        data = Path(temp.name)
        self.docs = data / 'docs'
        self.docs.mkdir()
        chroma = chromadb.EphemeralClient()
        name = 'test_' + uuid4().hex
        for patcher in [patch.object(main, 'DATA_DIR', data), patch.object(main, 'DOCS_DIR', self.docs),
                        patch.object(rag, 'COLLECTION_NAME', name), patch.object(rag, 'LocalEmbedder', FakeEmbedder),
                        patch.object(rag.chromadb, 'PersistentClient', return_value=chroma)]:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(chroma.delete_collection, name)
        self.client = self.enterContext(TestClient(main.app))
        self.engine = main.engine

    def upload(self, path=MIDEA):
        response = self.client.post('/api/upload', files={'file': (path.name, path.read_bytes(), 'text/markdown')})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_reupload_replaces_in_both_stores(self):
        first = self.upload()
        self.upload()
        self.assertEqual(self.client.get('/api/status').json(), {'chunks': first['chunks'], 'docs': [MIDEA.name]})
        result = self.client.get('/api/jobs', params={'city': '合肥', 'max_duration_months': 3}).json()
        self.assertEqual([j['company'] for j in result['jobs']], ['美的冰箱事业部'])

    def test_reset_and_restart_do_not_resurrect_files(self):
        self.upload()
        self.assertEqual(self.client.post('/api/reset').status_code, 200)
        self.assertTrue((self.docs / MIDEA.name).exists())
        with TestClient(main.app) as restarted:
            self.assertEqual(restarted.get('/api/status').json(), {'chunks': 0, 'docs': []})
            self.assertEqual(restarted.get('/api/jobs').json()['jobs'], [])

    def test_empty_database_does_not_call_llm(self):
        with patch.object(self.engine, '_chat') as model:
            reply = self.client.post('/api/ask', json={'question': '美的在哪里？'})
            self.assertEqual(reply.status_code, 200)
            self.assertIn('请先上传', reply.json()['answer'])
            model.assert_not_called()

    def test_invalid_upload_preserves_existing_document(self):
        self.upload()
        before = self.client.get('/api/status').json()
        for filename, content in [('broken.pdf', b'not a PDF'), ('empty.md', b''), ('bad.md', b'\xff\xfe'),
                                  ('bad.exe', b'x'), ('../escape.md', b'x'), (MIDEA.name, b'')]:
            response = self.client.post('/api/upload', files={'file': (filename, content)})
            self.assertEqual(response.status_code, 400, (filename, response.text))
        with patch.object(main, 'MAX_UPLOAD_BYTES', 8):
            response = self.client.post('/api/upload', files={'file': ('big.md', b'x' * 9)})
            self.assertEqual(response.status_code, 413)
        self.assertEqual(self.client.get('/api/status').json(), before)

    def test_question_and_filter_validation(self):
        self.assertEqual(self.client.post('/api/ask', json={'question': '  '}).status_code, 400)
        self.assertEqual(self.client.post('/api/ask', json={'question': 'x' * 2001}).status_code, 422)
        self.assertEqual(self.client.get('/api/jobs?max_days_per_week=8').status_code, 422)
        self.assertEqual(self.client.get('/api/jobs?unexpected=value').status_code, 422)

    def test_missing_api_key_and_timeout(self):
        self.upload()
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': ''}):
            response = self.client.post('/api/ask', json={'question': '美的在哪里？'})
            self.assertEqual(response.status_code, 503)
            self.assertIn('未配置', response.json()['detail'])
        with patch.object(self.engine, '_chat', side_effect=APITimeoutError(request=httpx.Request('POST', 'https://example.test'))):
            self.assertEqual(self.client.post('/api/ask', json={'question': '美的在哪里？'}).status_code, 502)

    def test_chunk_tail_is_not_duplicated(self):
        for length, sizes in [(400, [400]), (720, [400, 400]), (721, [400, 400, 81])]:
            self.assertEqual([len(c) for c in self.engine._chunk('a' * length)], sizes)

    def test_rag_returns_full_passage(self):
        self.upload()
        with patch.object(self.engine, '_chat', return_value=AIMessage(content='未说明住宿。')):
            result = self.engine.answer('美的提供住宿吗？', main.job_store)
        self.assertEqual(result['mode'], 'rag')
        self.assertTrue(any(len(s['snippet']) > 120 for s in result['sources']))

    def test_tool_answer_does_not_mix_nonmatching_rag_passages(self):
        self.upload()
        self.upload(BAOZUN)
        payloads = []

        def respond(request):
            self.assertEqual(request.url.path, '/chat/completions')
            payload = json.loads(request.content)
            payloads.append(payload)
            if len(payloads) == 1:
                message = {'role': 'assistant', 'content': None, 'tool_calls': [{
                    'id': 'call_test', 'type': 'function', 'function': {
                        'name': 'search_jobs',
                        'arguments': json.dumps({'city': '合肥', 'kind': '实习', 'max_duration_months': 3}),
                    },
                }]}
            else:
                message = {'role': 'assistant', 'content': '匹配美的。'}
            return httpx.Response(200, json={
                'id': 'mock_completion', 'object': 'chat.completion', 'created': 0,
                'model': 'deepseek-flash', 'choices': [{
                    'index': 0, 'message': message,
                    'finish_reason': 'tool_calls' if len(payloads) == 1 else 'stop',
                }],
            })

        with httpx.Client(transport=httpx.MockTransport(respond)) as http:
            with patch.object(rag, 'ChatDeepSeek', side_effect=lambda **kwargs: ChatDeepSeek(
                **{**kwargs, 'api_key': 'offline-test'}, http_client=http,
            )), patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'offline-test'}):
                response = self.client.post('/api/ask', json={'question': '筛选合肥实习不超过3个月'})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result['mode'], 'jobs')
        self.assertEqual(result['answer'], '匹配美的。')
        self.assertEqual(result['sources'], [])
        self.assertEqual([j['company'] for j in result['jobs']], ['美的冰箱事业部'])

        first, second = payloads
        self.assertEqual(first['tool_choice'], 'auto')
        self.assertEqual(first['tools'][0]['function']['name'], 'search_jobs')
        self.assertEqual(first['thinking'], {'type': 'disabled'})
        self.assertIn('【参考资料】', first['messages'][1]['content'])
        self.assertEqual(second['tool_choice'], 'none')
        self.assertEqual(second['messages'][-1]['tool_call_id'], 'call_test')
        sent = json.dumps(second['messages'], ensure_ascii=False)
        self.assertNotIn('宝尊', sent)
        self.assertNotIn('【参考资料】', sent)

    def test_invalid_tool_calls_cannot_query_database(self):
        self.upload()
        calls = [('execute_sql', {}), ('search_jobs', {'max_duration_months': '3'}),
                 ('search_jobs', {'sql': 'DELETE FROM jobs'})]
        replies = [AIMessage(content='', tool_calls=[{'id': 'call_test', 'name': name, 'args': args}])
                   for name, args in calls]
        replies.append(AIMessage(content='', invalid_tool_calls=[{
            'id': 'call_test', 'name': 'search_jobs', 'args': '{"unfinished":', 'error': 'invalid JSON',
        }]))
        for reply in replies:
            with self.subTest(reply=reply), patch.object(main.job_store, 'search') as search, patch.object(
                self.engine, '_chat', side_effect=[reply, AIMessage(content='请确认条件。')],
            ) as model:
                result = self.engine.answer('查询岗位', main.job_store)
                search.assert_not_called()
                self.assertEqual(result['mode'], 'jobs')
                self.assertEqual(result['jobs'], [])
                self.assertEqual(model.call_count, 2)
                self.assertEqual(model.call_args.kwargs['tool_choice'], 'none')
                tool_message = model.call_args.args[0][-1]
                self.assertIsInstance(tool_message, ToolMessage)
                self.assertEqual(tool_message.tool_call_id, 'call_test')
                self.assertIn('error', json.loads(tool_message.content))


if __name__ == '__main__':
    unittest.main()
