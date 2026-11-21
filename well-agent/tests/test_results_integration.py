import json
from pathlib import Path
import pytest
from src.results import analyze_run


def test_sparse_export_warns_and_preserves_signed_flow(tmp_path):
    tpl = tmp_path/'case1_obhod.tpl'
    tpl.write_text("\n".join([
        "'TEST'", 'CATALOG', '1',
        "GT 'BOUNDARY:' 'BRANCH:' 'PUMP TUBE - COPY' 'PIPE:' 'PIPE-1' 'NR:' '2' '(KG/S)' 'Total mass flow'",
        "TIME SERIES '(S)'", '0 -9.989051', '345600 0', '']))
    manifest = json.loads(Path('mcp_server/cases/mbsnu_bypass_96h.json').read_text())
    result = analyze_run(tmp_path, manifest, {})
    initial = next(m for m in result['metrics'] if m['name']=='initial')
    assert initial['value'] == -9.989051
    assert result['assessment']['status']=='NOT_ASSESSED'
    assert result['assessment']['transition_points']==0
    assert any('трёх' in w for w in result['assessment']['warnings'])
    assert (tmp_path/'analysis/channels.csv').exists()


def test_bad_numeric_output_is_rejected(tmp_path):
    tpl = tmp_path/'case1_obhod.tpl'
    tpl.write_text("\n".join([
        "'TEST'", 'CATALOG', '1',
        "GT 'BOUNDARY:' 'BRANCH:' 'BYPASS' 'PIPE:' 'PIPE-1' 'NR:' '2' '(KG/S)' 'flow'",
        "TIME SERIES '(S)'", '0 1', '345600 nan', '']))
    manifest = json.loads(Path('mcp_server/cases/mbsnu_bypass_96h.json').read_text())
    with pytest.raises(ValueError):
        analyze_run(tmp_path, manifest, {})
