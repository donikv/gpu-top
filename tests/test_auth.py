"""LDAP search+bind tests against ldap3's in-process mock server.

This exercises the real _ldap_authenticate code path (service bind -> search
-> user bind) without a running directory. For an end-to-end check against a
real OpenLDAP, use dev/ldap-compose.yml on a machine with docker.
"""
import ldap3
import pytest
from ldap3.core.exceptions import LDAPBindError

from gpu_top.config import LdapConfig
from gpu_top.server.auth import _ldap_authenticate

SERVICE_DN = "cn=gpu-top,ou=services,dc=example,dc=org"
ALICE_DN = "uid=alice,ou=people,dc=example,dc=org"

ENTRIES = {
    SERVICE_DN: {"objectClass": "organizationalRole", "cn": "gpu-top",
                 "userPassword": "service123"},
    ALICE_DN: {"objectClass": "inetOrgPerson", "uid": "alice", "cn": "Alice",
               "sn": "Example", "userPassword": "alice123"},
}

CFG = LdapConfig(
    uri="ldap://mock",
    service_dn=SERVICE_DN,
    service_password="service123",
    base_dn="ou=people,dc=example,dc=org",
)

_real_connection = ldap3.Connection


@pytest.fixture(autouse=True)
def mock_ldap(monkeypatch):
    """Replace ldap3.Connection with one backed by the MOCK_SYNC strategy."""

    def connection(server, user=None, password=None, auto_bind=False, **kwargs):
        kwargs.pop("client_strategy", None)
        conn = _real_connection(server, user=user, password=password,
                                client_strategy=ldap3.MOCK_SYNC, **kwargs)
        for dn, attrs in ENTRIES.items():
            conn.strategy.add_entry(dn, dict(attrs))
        if auto_bind and not conn.bind():
            raise LDAPBindError(f"mock bind failed for {user}")
        return conn

    monkeypatch.setattr(ldap3, "Connection", connection)


def test_valid_credentials():
    assert _ldap_authenticate(CFG, "alice", "alice123") is True


def test_wrong_password():
    assert _ldap_authenticate(CFG, "alice", "wrong") is False


def test_unknown_user():
    assert _ldap_authenticate(CFG, "bob", "whatever") is False


def test_filter_injection_is_escaped():
    # A crafted "username" that would widen the filter must find nothing.
    assert _ldap_authenticate(CFG, "*)(uid=*", "alice123") is False


def test_bad_service_credentials():
    cfg = LdapConfig(uri="ldap://mock", service_dn=SERVICE_DN,
                     service_password="wrong", base_dn=CFG.base_dn)
    assert _ldap_authenticate(cfg, "alice", "alice123") is False
