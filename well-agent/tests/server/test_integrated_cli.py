"""Merged client -> actual MCP adapter -> fake process -> analysis pipeline."""
import json
import sys
from argparse import Namespace
from unittest.mock import Mock
import pytest
from scripts.demo import run_one
from src.agent import loop
from src.agent.schemas import BenchContext, RequestIntent
from src.agent.tools import McpToolGateway, McpGatewayError
from .conftest import FAKE_OLGA


@pytest.mark.parametrize('decision,behavior,expected', [('да', 'ok', 'ok'), ('нет', 'ok', 'refused'), ('да', 'fail', 'failed')])
def test_integrated_run(kit, tmp_path, monkeypatch, decision, behavior, expected):
    for name, value in {
        'OLGA_ADAPTER_MODE': 'fake', 'OLGA_CASE_KIT_DIR': str(kit),
        'OLGA_LAUNCHER': sys.executable, 'OLGA_LAUNCHER_ARGS': json.dumps([str(FAKE_OLGA), '{input}']),
        'OLGA_APPROVAL_SECRET': 'integration-secret', 'OLGA_RUNS_ROOT': str(tmp_path/'runs'),
        'OLGA_LOG_DIR': str(tmp_path/'server-logs'), 'FAKE_OLGA_BEHAVIOR': behavior,
    }.items():
        monkeypatch.setenv(name, value)
    intent = RequestIntent(action='simulate_bypass', case_id=None, event_time=None,
        transition_duration=None, end_time=None, requested_outputs=[])
    monkeypatch.setattr(loop, 'parse_request', Mock(return_value=intent))
    context = BenchContext(llm_model='test', llm_base_url='https://example.invalid',
        llm_api_key='integration-llm-key', mcp_case_id='mbsnu_bypass_96h', mcp_timeout_s=60)
    args = Namespace(execute=True, test_mcp=False, log_dir=tmp_path/'client-logs',
        poll_interval=.05, timeout=10)
    output=[]
    assert run_one('Запусти обход МБСНУ', context, args, lambda _: decision, output.append) == expected
    assert not (kit/'case1_obhod.out').exists()
    runs=list((tmp_path/'runs').glob('run_*'))
    if decision == 'нет':
        assert runs == []
        return
    assert len(runs) == 1
    if expected == 'ok':
        summary=json.loads(next((tmp_path/'client-logs').glob('*.results.json')).read_text())
        assert summary['adapter_mode']=='fake'
        assert summary['statuses']['results_read']=='OK'
        assert len(summary['metrics'])==20
        assert (runs[0]/'model/analysis/overview.png').is_file()
        assert (runs[0]/'model/analysis/series.csv').is_file()
    for path in (tmp_path/'client-logs').glob('*.jsonl'):
        assert 'integration-secret' not in path.read_text()
        assert 'integration-llm-key' not in path.read_text()


def test_adapter_error_is_not_success(monkeypatch, tmp_path):
    monkeypatch.setenv('OLGA_LOG_DIR', str(tmp_path/'logs'))
    gateway = McpToolGateway()
    with pytest.raises(McpGatewayError) as error:
        gateway.call_tool('read_case_manifest', {'case_id':'missing', 'trace_id':'test-error'})
    assert error.value.code == 'INVALID_INPUT'
