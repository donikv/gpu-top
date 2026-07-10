"""Config parsing tests, including the STARTTLS/verify options."""
import pytest

from gpu_top.config import ConfigError, load_agent_config, load_server_config

SERVER_TOML = """
[server]
session_secret = "s"
[agents]
tokens = ["t"]
[auth]
mode = "ldap"
[auth.ldap]
uri = "ldap://zver0.zesoi.fer.hr"
starttls = true
tls_verify = false
service_dn = "cn=administrator,dc=ipg,dc=com"
service_password = "pw"
base_dn = "dc=ipg,dc=com"
user_filter = "(&(uid={username})(memberOf=cn=monitoring,ou=Machines,dc=ipg,dc=com))"
"""


def test_server_config_ldap_options(tmp_path):
    path = tmp_path / "server.toml"
    path.write_text(SERVER_TOML)
    cfg = load_server_config(str(path))
    assert cfg.ldap.starttls is True
    assert cfg.ldap.tls_verify is False
    assert "cn=monitoring,ou=Machines" in cfg.ldap.user_filter


def test_ldap_tls_defaults(tmp_path):
    path = tmp_path / "server.toml"
    path.write_text(SERVER_TOML.replace("starttls = true\ntls_verify = false\n", ""))
    cfg = load_server_config(str(path))
    assert cfg.ldap.starttls is False
    assert cfg.ldap.tls_verify is True


def test_auth_none_requires_dev_env(tmp_path, monkeypatch):
    monkeypatch.delenv("GPU_TOP_DEV", raising=False)
    path = tmp_path / "server.toml"
    path.write_text('[server]\nsession_secret="s"\n[agents]\ntokens=["t"]\n'
                    '[auth]\nmode="none"\n')
    with pytest.raises(ConfigError):
        load_server_config(str(path))


def test_agent_config(tmp_path):
    path = tmp_path / "agent.toml"
    path.write_text('[agent]\nserver_name="zver13"\nurl="https://mon.example/"\n'
                    'token="t"\n')
    cfg = load_agent_config(str(path))
    assert cfg.server_name == "zver13"
    assert cfg.url == "https://mon.example"   # trailing slash stripped
    assert cfg.interval == 5.0
