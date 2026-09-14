"""SSRF-protection tests for app.utils.security.

DNS resolution is monkeypatched so these tests never touch the network.
"""
from __future__ import annotations

import socket

import pytest

from app.utils.security import (
    is_public_http_url,
    is_safe_url,
    is_same_scope,
    normalize_url,
    resolve_and_validate_host,
)
from app.schemas.models import CrawlScope


def _fake_getaddrinfo(ip: str):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 6, "", (ip, 0))]


def _patch_dns(monkeypatch, mapping: dict[str, str]):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        if host not in mapping:
            raise socket.gaierror(f"no mapping for {host}")
        return _fake_getaddrinfo(mapping[host])

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


# --- scheme tests -----------------------------------------------------

def test_rejects_file_scheme():
    assert is_public_http_url("file:///etc/passwd") is False


def test_rejects_ftp_scheme():
    assert is_public_http_url("ftp://example.com/file") is False


def test_rejects_gopher_scheme():
    assert is_public_http_url("gopher://example.com/") is False


def test_rejects_data_scheme():
    assert is_public_http_url("data:text/html,<script>alert(1)</script>") is False


def test_accepts_https_scheme():
    assert is_public_http_url("https://example.com/page") is True


# --- host/IP resolution tests ------------------------------------------

def test_rejects_localhost_hostname(monkeypatch):
    _patch_dns(monkeypatch, {"localhost": "127.0.0.1"})
    with pytest.raises(ValueError):
        resolve_and_validate_host("localhost")


def test_rejects_loopback_ip_literal(monkeypatch):
    _patch_dns(monkeypatch, {"127.0.0.1": "127.0.0.1"})
    with pytest.raises(ValueError):
        resolve_and_validate_host("127.0.0.1")


@pytest.mark.parametrize(
    "ip",
    [
        "10.0.0.5",
        "172.16.0.5",
        "192.168.1.5",
        "127.0.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "224.0.0.1",
    ],
)
def test_rejects_private_and_special_ipv4(monkeypatch, ip):
    _patch_dns(monkeypatch, {"evil.example": ip})
    with pytest.raises(ValueError):
        resolve_and_validate_host("evil.example")


def test_rejects_aws_metadata_ip(monkeypatch):
    _patch_dns(monkeypatch, {"attacker.example": "169.254.169.254"})
    with pytest.raises(ValueError):
        resolve_and_validate_host("attacker.example")


def test_rejects_metadata_google_internal_hostname(monkeypatch):
    _patch_dns(monkeypatch, {"metadata.google.internal": "8.8.8.8"})
    with pytest.raises(ValueError):
        resolve_and_validate_host("metadata.google.internal")


def test_rejects_ipv6_loopback(monkeypatch):
    _patch_dns(monkeypatch, {"evil6.example": "::1"})
    with pytest.raises(ValueError):
        resolve_and_validate_host("evil6.example")


def test_rejects_ipv6_link_local(monkeypatch):
    _patch_dns(monkeypatch, {"evil6ll.example": "fe80::1"})
    with pytest.raises(ValueError):
        resolve_and_validate_host("evil6ll.example")


def test_rejects_ipv6_unique_local(monkeypatch):
    _patch_dns(monkeypatch, {"evil6ula.example": "fd00::1"})
    with pytest.raises(ValueError):
        resolve_and_validate_host("evil6ula.example")


def test_accepts_public_hostname(monkeypatch):
    _patch_dns(monkeypatch, {"example.com": "93.184.216.34"})
    ips = resolve_and_validate_host("example.com")
    assert ips == ["93.184.216.34"]


def test_dns_failure_raises(monkeypatch):
    _patch_dns(monkeypatch, {})
    with pytest.raises(ValueError):
        resolve_and_validate_host("nonexistent.invalid")


# --- is_safe_url integration --------------------------------------------

def test_is_safe_url_accepts_public_https(monkeypatch):
    _patch_dns(monkeypatch, {"example.com": "93.184.216.34"})
    ok, reason = is_safe_url("https://example.com/path")
    assert ok is True
    assert reason == "ok"


def test_is_safe_url_rejects_private(monkeypatch):
    _patch_dns(monkeypatch, {"internal.example": "10.1.2.3"})
    ok, reason = is_safe_url("http://internal.example/admin")
    assert ok is False
    assert reason


def test_is_safe_url_rejects_bad_scheme():
    ok, reason = is_safe_url("file:///etc/passwd")
    assert ok is False


# --- normalize_url --------------------------------------------------------

def test_normalize_url_strips_fragment_and_tracking_params():
    url = "https://Example.com/Page/?utm_source=x&fbclid=123&a=1#section"
    normalized = normalize_url(url)
    assert normalized == "https://example.com/Page?a=1"


def test_normalize_url_resolves_relative_against_base():
    normalized = normalize_url("/about", base="https://example.com/blog/post")
    assert normalized == "https://example.com/about"


def test_normalize_url_removes_default_port():
    normalized = normalize_url("https://example.com:443/path")
    assert normalized == "https://example.com/path"


# --- is_same_scope --------------------------------------------------------

def test_same_scope_entire_domain_includes_subdomains():
    root = "https://example.com/"
    assert is_same_scope("https://blog.example.com/post", root, CrawlScope.entire_domain, None) is True


def test_same_scope_selected_path_prefix():
    root = "https://example.com/docs/"
    assert (
        is_same_scope("https://example.com/docs/intro", root, CrawlScope.selected_path, "/docs")
        is True
    )
    assert (
        is_same_scope("https://example.com/blog/post", root, CrawlScope.selected_path, "/docs")
        is False
    )


def test_same_scope_linked_pages_same_host_only():
    root = "https://example.com/"
    assert is_same_scope("https://example.com/other", root, CrawlScope.linked_pages, None) is True
    assert is_same_scope("https://other.com/other", root, CrawlScope.linked_pages, None) is False
