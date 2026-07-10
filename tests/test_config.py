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
    assert cfg.ldap.ca_cert_file == ""


def test_proxy_and_cookie_options(tmp_path):
    path = tmp_path / "server.toml"
    path.write_text(SERVER_TOML.replace(
        'session_secret = "s"',
        'session_secret = "s"\nbehind_proxy = true\n'
        'trusted_proxies = "10.0.0.1"\ncookie_secure = "always"'))
    cfg = load_server_config(str(path))
    assert cfg.behind_proxy is True
    assert cfg.trusted_proxies == "10.0.0.1"
    assert cfg.cookie_secure == "always"


def test_cookie_secure_defaults_to_auto(tmp_path):
    path = tmp_path / "server.toml"
    path.write_text(SERVER_TOML)
    cfg = load_server_config(str(path))
    assert cfg.behind_proxy is False
    assert cfg.cookie_secure == "auto"


def test_bad_cookie_secure_rejected(tmp_path):
    path = tmp_path / "server.toml"
    path.write_text(SERVER_TOML.replace(
        'session_secret = "s"', 'session_secret = "s"\ncookie_secure = "yes"'))
    with pytest.raises(ConfigError):
        load_server_config(str(path))


def test_service_password_from_secret_file(tmp_path, monkeypatch):
    secret = tmp_path / "ldap_service_password"
    secret.write_text("from-secret-file\n")
    path = tmp_path / "server.toml"
    path.write_text(SERVER_TOML.replace('service_password = "pw"\n', ""))
    monkeypatch.delenv("GPU_TOP_SERVICE_PASSWORD", raising=False)
    monkeypatch.setenv("GPU_TOP_SERVICE_PASSWORD_FILE", str(secret))
    cfg = load_server_config(str(path))
    assert cfg.ldap.service_password == "from-secret-file"  # trailing \n stripped


def test_missing_secret_file_is_a_config_error(tmp_path, monkeypatch):
    path = tmp_path / "server.toml"
    path.write_text(SERVER_TOML.replace('service_password = "pw"\n', ""))
    monkeypatch.setenv("GPU_TOP_SERVICE_PASSWORD_FILE", str(tmp_path / "nope"))
    with pytest.raises(ConfigError):
        load_server_config(str(path))


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
