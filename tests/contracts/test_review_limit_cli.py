import json
import pytest
from mira.config.settings import Settings
from tools import live_provider as cli


def args(*extra):
    return ['check','--provider','chatgpt_subscription','--model','synthetic-model',
        '--env-file','/synthetic/private.env','--action-review-mode','legacy_jev',*extra]


@pytest.mark.parametrize('extra,expected',[
    ([],(16384,32768)),(['--story'],(32768,65536)),
    (['--story','--input-review-max-bytes','40000','--output-review-max-bytes','70000'],(40000,70000))])
def test_check_displays_exact_factory_resolved_request_caps_without_io(monkeypatch,capsys,extra,expected):
    monkeypatch.setattr(cli,'_load',lambda _:(Settings(),None))
    monkeypatch.setattr(cli,'_generation',lambda *_:pytest.fail('no model/auth IO during check'))
    assert cli.main(args(*extra))==0
    result=json.loads(capsys.readouterr().out)['review_request_limits']
    assert (result['input_max_request_bytes'],result['output_max_request_bytes'])==expected
    assert result['limits_are_dollar_caps'] is False


@pytest.mark.parametrize('bad',['0','1023','131073','999999999999999999999'])
def test_invalid_explicit_request_cap_stops_before_config_reads(monkeypatch,bad):
    monkeypatch.setattr(cli,'_load',lambda _:pytest.fail('configuration read before option validation'))
    assert cli.main(args('--input-review-max-bytes',bad))==2
