"""Offline adapter contracts; no test connects to Huawei OBS or a Redis server."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.ahr import cache, storage


@pytest.fixture
def storage_config(tmp_path, monkeypatch):
    config = SimpleNamespace(runtime=tmp_path / "runtime", storage="local",
                             obs_endpoint="https://obs.example.invalid", obs_bucket="fixture-bucket",
                             obs_access_key="dummy-ak", obs_secret_key="dummy-sk", obs_region="cn-north-4")
    monkeypatch.setattr(storage, "settings", lambda: config)
    return config


class FakeOBS:
    def __init__(self, status=200, content=b"fake-object-content", error=None):
        self.status, self.content, self.error = status, content, error
        self.closed = 0
        self.calls = []

    def putContent(self, bucket, key, **kwargs):
        self.calls.append(("put", bucket, key, kwargs))
        if self.error:
            raise self.error
        return SimpleNamespace(status=self.status)

    def getObject(self, bucket, key, downloadPath):
        self.calls.append(("get", bucket, key, downloadPath))
        # Simulate an interrupted HTTP response that has already written bytes.
        Path(downloadPath).write_bytes(self.content)
        if self.error:
            raise self.error
        return SimpleNamespace(status=self.status)

    def close(self):
        self.closed += 1


def test_local_storage_atomic_replacement_and_no_cloud_calls(storage_config, monkeypatch):
    monkeypatch.setattr(storage, "obs_client", lambda: pytest.fail("本地存储不应调用云服务"))
    key = "originals/test.png"
    storage.put(key, b"old-bytes", "image/png")
    target = storage.get_path(key)
    original_replace = storage.os.replace
    observations = []

    def check_atomic_replace(source, destination):
        observations.append((Path(source).read_bytes(), Path(destination).read_bytes()))
        assert Path(source).parent == target.parent
        return original_replace(source, destination)

    monkeypatch.setattr(storage.os, "replace", check_atomic_replace)
    storage.put(key, b"complete-new-bytes", "image/png")
    assert observations == [(b"complete-new-bytes", b"old-bytes")]
    assert target.read_bytes() == b"complete-new-bytes"
    assert list(target.parent.glob(".ahr-*")) == []


def test_atomic_write_failure_preserves_old_file_and_cleans_temp(storage_config, monkeypatch):
    path = storage.local_path("one/image.png")
    storage.atomic_write(path, b"original")

    def fail_replace(*args):
        raise OSError("injected disk replace failure")

    monkeypatch.setattr(storage.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected"):
        storage.atomic_write(path, b"new")
    assert path.read_bytes() == b"original"
    assert list(path.parent.glob(".ahr-*")) == []


@pytest.mark.parametrize("key", ["../outside.bin", "folder/../../outside.bin", "/tmp/ahr-outside-test.bin"])
def test_storage_rejects_path_escape(storage_config, key):
    with pytest.raises(ValueError, match="非法存储路径"):
        storage.local_path(key)


def test_storage_rejects_symlink_escape(storage_config, tmp_path):
    root = storage.local_path("inside.txt").parent
    root.mkdir(parents=True, exist_ok=True)
    (root / "escape").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="非法存储路径"):
        storage.put("escape/outside.txt", b"must-not-be-written")
    assert not (tmp_path / "outside.txt").exists()


def test_obs_put_uses_private_header_and_closes(storage_config, monkeypatch):
    storage_config.storage = "obs"
    client = FakeOBS(status=201)
    monkeypatch.setattr(storage, "obs_client", lambda: client)
    assert storage.put("images/a.png", b"png-content", "image/png") == "images/a.png"
    _, bucket, key, args = client.calls[0]
    assert bucket == "fixture-bucket" and key == "images/a.png"
    assert args["content"] == b"png-content"
    assert args["headers"].contentType == "image/png"
    assert args["headers"].acl == "private"
    assert client.closed == 1
    assert storage.local_path(key).read_bytes() == b"png-content"


@pytest.mark.parametrize("status", [None, 301, 400, 403, 500])
def test_obs_non_success_put_is_not_cached_or_successful(storage_config, monkeypatch, status):
    storage_config.storage = "obs"
    client = FakeOBS(status=status)
    monkeypatch.setattr(storage, "obs_client", lambda: client)
    with pytest.raises(OSError, match="OBS操作失败"):
        storage.put("images/failure.png", b"should-not-be-cached")
    assert not storage.local_path("images/failure.png").exists()
    assert client.closed == 1


def test_obs_download_success_is_cached_and_client_closed(storage_config, monkeypatch):
    storage_config.storage = "obs"
    client = FakeOBS(content=b"download-complete")
    monkeypatch.setattr(storage, "obs_client", lambda: client)
    result = storage.get_path("images/download.png")
    assert result.read_bytes() == b"download-complete"
    assert client.closed == 1 and len(client.calls) == 1
    assert storage.get_path("images/download.png") == result
    assert len(client.calls) == 1  # second access is the local cache
    assert list(result.parent.glob(".ahr-*")) == []


@pytest.mark.parametrize("status,expected", [(404, FileNotFoundError), (403, OSError), (500, OSError)])
def test_failed_obs_download_never_publishes_partial_cache(storage_config, monkeypatch, status, expected):
    storage_config.storage = "obs"
    client = FakeOBS(status=status, content=b"partial-error-body")
    monkeypatch.setattr(storage, "obs_client", lambda: client)
    with pytest.raises(expected):
        storage.get_path("images/fail.png")
    target = storage.local_path("images/fail.png")
    assert not target.exists()
    assert list(target.parent.glob(".ahr-*")) == []
    assert client.closed == 1


def test_obs_transport_exception_cleans_partial_download(storage_config, monkeypatch):
    storage_config.storage = "obs"
    client = FakeOBS(error=TimeoutError("offline injected timeout"))
    monkeypatch.setattr(storage, "obs_client", lambda: client)
    with pytest.raises(TimeoutError):
        storage.get_path("images/timeout.png")
    target = storage.local_path("images/timeout.png")
    assert not target.exists()
    assert list(target.parent.glob(".ahr-*")) == []
    assert client.closed == 1


def test_obs_client_creation_failure_leaves_no_orphan_download(storage_config, monkeypatch):
    storage_config.storage = "obs"

    def fail_client():
        raise ValueError("injected invalid configuration")

    monkeypatch.setattr(storage, "obs_client", fail_client)
    with pytest.raises(ValueError):
        storage.get_path("images/no-client.png")
    target = storage.local_path("images/no-client.png")
    assert not target.exists()
    assert list(target.parent.glob(".ahr-*")) == []


def test_official_obs_client_configuration_is_secure_and_offline(storage_config, monkeypatch):
    import obs
    captured = {}
    sentinel = object()

    def fake_constructor(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(obs, "ObsClient", fake_constructor)
    assert storage.obs_client() is sentinel
    assert captured["server"] == storage_config.obs_endpoint
    assert captured["ssl_verify"] is True and captured["trust_env"] is False
    assert captured["timeout"] == 30 and captured["max_retry_count"] == 2
    storage_config.obs_endpoint = "http://obs.example.invalid"
    with pytest.raises(ValueError, match="HTTPS"):
        storage.obs_client()


class FakeRedis:
    def __init__(self, raw=None, error=None):
        self.raw, self.error = raw, error
        self.keys, self.writes = [], []

    def get(self, key):
        self.keys.append(key)
        if self.error:
            raise self.error
        return self.raw

    def setex(self, key, ttl, content):
        if self.error:
            raise self.error
        self.writes.append((key, ttl, content))


def test_redis_hit_serialization_namespace_and_ttl(monkeypatch):
    expected = {"items": [{"title": "中文循证条目"}], "count": 1}
    client = FakeRedis(raw=json.dumps(expected, ensure_ascii=False))
    monkeypatch.setattr(cache, "redis_client", lambda: client)
    assert cache.get_cache("query") == expected
    cache.set_cache("query", expected)
    assert client.keys == ["ahr:retrieval:v1:query"]
    key, ttl, content = client.writes[0]
    assert key == "ahr:retrieval:v1:query" and ttl == 900
    assert json.loads(content) == expected and "中文" in content


@pytest.mark.parametrize("raw", [None, "", "not-json", "{malformed"])
def test_redis_miss_or_invalid_json_falls_back(monkeypatch, raw):
    monkeypatch.setattr(cache, "redis_client", lambda: FakeRedis(raw=raw))
    assert cache.get_cache("query") is None


def test_unreachable_redis_falls_back_on_read_and_write(monkeypatch):
    client = FakeRedis(error=ConnectionError("injected offline redis"))
    monkeypatch.setattr(cache, "redis_client", lambda: client)
    assert cache.get_cache("query") is None
    assert cache.set_cache("query", {"value": 1}) is None


def test_unconfigured_redis_remains_local(monkeypatch):
    monkeypatch.setattr(cache, "redis_client", lambda: None)
    assert cache.get_cache("query") is None
    assert cache.set_cache("query", {"value": 1}) is None
