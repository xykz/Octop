"""Tests for Octop's S3-compatible backend materialization."""

from __future__ import annotations

from typing import Any

import pytest

from octop.infra.backend.s3_backend import (
    OctopS3Backend,
    build_s3_backend,
    materialize_s3_backends,
    spec_is_s3,
)

_S3_SPEC: dict[str, Any] = {
    "type": "s3",
    "bucket": "my-bucket",
    "access_key_id": "AKIA",
    "secret_access_key": "secret",
    "region": "us-east-1",
    "endpoint_url": "https://minio.example.com",
}


def test_build_s3_backend_uses_bundled_harness_backend() -> None:
    backend = build_s3_backend(_S3_SPEC)
    assert isinstance(backend, OctopS3Backend)


def test_build_s3_backend_defaults_addressing_to_auto() -> None:
    backend = build_s3_backend(_S3_SPEC)
    assert backend._config.addressing_style == "auto"


def test_build_s3_backend_keeps_explicit_addressing() -> None:
    backend = build_s3_backend({**_S3_SPEC, "addressing_style": "path"})
    assert backend._config.addressing_style == "path"


def test_default_region_kept_when_spec_omits_it(monkeypatch: pytest.MonkeyPatch) -> None:
    import boto3
    import botocore.config

    captured: dict[str, Any] = {}

    def _client(service: str, **kwargs: Any) -> str:
        captured["service"] = service
        captured["kwargs"] = kwargs
        return "client"

    monkeypatch.setattr(boto3, "client", _client)
    build_s3_backend({key: value for key, value in _S3_SPEC.items() if key != "region"})
    assert captured["kwargs"]["region_name"] == "us-east-1"
    assert captured["kwargs"]["config"] is not None
    assert isinstance(captured["kwargs"]["config"], botocore.config.Config)


def test_spec_is_s3_matches_only_dict_s3() -> None:
    assert spec_is_s3(_S3_SPEC)
    assert spec_is_s3({"type": "S3"})
    assert not spec_is_s3({"type": "cos"})
    assert not spec_is_s3("s3")


def test_materialize_replaces_s3_with_instance() -> None:
    materialized = materialize_s3_backends(_S3_SPEC)
    assert isinstance(materialized, OctopS3Backend)


def test_materialize_leaves_other_specs_untouched() -> None:
    spec = {"type": "filesystem", "root_dir": "/data"}
    assert materialize_s3_backends(spec) is spec


def test_materialize_walks_composite_routes() -> None:
    spec = {
        "type": "composite",
        "default": {"type": "filesystem", "root_dir": "/data"},
        "routes": {"/archive": dict(_S3_SPEC)},
    }
    materialized = materialize_s3_backends(spec)
    assert materialized["default"] == {"type": "filesystem", "root_dir": "/data"}
    assert isinstance(materialized["routes"]["/archive"], OctopS3Backend)
    assert spec["routes"]["/archive"] == _S3_SPEC
