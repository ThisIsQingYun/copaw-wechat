from wecom.app.config import WeComAppConfig


def test_app_config_supports_secret_alias_and_proxy_env(monkeypatch):
    monkeypatch.setenv('WECOM_APP_EGRESS_PROXY_URL', 'http://proxy.local:3128')

    config = WeComAppConfig.from_mapping(
        {
            'corp_id': 'ww1234567890',
            'corp_secret': 'secret_from_alias',
            'agent_id': 1000001,
        }
    )

    assert config.agent_secret == 'secret_from_alias'
    assert config.receive_id == 'ww1234567890'
    assert config.egress_proxy_url == 'http://proxy.local:3128'


def test_app_config_normalizes_policy_values():
    config = WeComAppConfig.from_mapping(
        {
            'corp_id': 'ww1234567890',
            'agent_secret': 'secret',
            'agent_id': 1000001,
            'dm_policy': '开放',
            'group_policy': '白名单列表',
        }
    )

    assert config.dm_policy == 'open'
    assert config.group_policy == 'allowlist'
