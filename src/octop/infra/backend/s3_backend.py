"""S3-compatible object storage on harness's deepagents 0.7-compatible backend.

harness-agent's ``[all]`` extra installs ``deepagents-backends``, and harness
prefers it over its own bundled boto3 backend whenever it is importable
(``harness_agent.backends._build_s3``). ``deepagents-backends 0.2.0`` is pinned
to the deepagents 0.5/0.6 protocol: it passes the removed ``files_update``
keyword, returns a line-numbered ``str`` from ``read``, and only implements the
retired ``ls_info`` / ``glob_info`` / ``grep_raw`` bridges. Under deepagents 0.7
every S3 write raises ``TypeError`` and reads / listings no longer match the
protocol. The Admin probe surfaces it first as::

    write failed: Error writing file '/.harness-probe-….txt':
    WriteResult.__init__() got an unexpected keyword argument 'files_update'

Octop therefore builds harness's bundled boto3 ``S3Backend`` — which implements
the current protocol — for ``s3`` specs and hands the instance to
``resolve_backend`` (pre-built backends pass through untouched). This covers the
``s3`` and ``custom`` (custom S3-compatible) storage kinds.

The client is built with SigV4 and automatic addressing (the previous
``deepagents-backends`` client used SigV4), so AWS S3 and S3-compatible stores
that reject SigV2 keep working.
"""

from __future__ import annotations

from typing import Any

from harness_agent.backends.s3_backend import S3Backend, S3Config

_S3 = "s3"
_AUTO_ADDRESSING = "auto"
# SigV4 needs a signing region. ``custom`` stores may leave it blank, so keep the
# previous deepagents-backends default rather than let boto3 raise NoRegionError.
_DEFAULT_REGION = "us-east-1"


class OctopS3Backend(S3Backend):
    """Harness bundled S3 backend with SigV4 signing and automatic addressing.

    Inherits the full deepagents 0.7 protocol implementation from
    :class:`harness_agent.backends.s3_backend.S3Backend`; only the boto3 client
    is rebuilt. The bundled default (SigV2 + virtual-hosted addressing) is
    rejected by AWS S3 and breaks self-hosted endpoints that cannot resolve
    virtual-host buckets.
    """

    @staticmethod
    def _build_client(config: S3Config) -> Any:
        import boto3
        import botocore.config

        client_kwargs: dict[str, Any] = {
            "aws_access_key_id": config.access_key_id,
            "aws_secret_access_key": config.secret_access_key,
            "config": botocore.config.Config(
                signature_version="s3v4",
                s3={"addressing_style": config.addressing_style or _AUTO_ADDRESSING},
            ),
        }
        if config.region:
            client_kwargs["region_name"] = config.region
        else:
            client_kwargs["region_name"] = _DEFAULT_REGION
        if config.endpoint_url:
            client_kwargs["endpoint_url"] = config.endpoint_url
        return boto3.client(_S3, **client_kwargs)


def spec_is_s3(spec: Any) -> bool:
    """True when *spec* is a dict addressing the ``s3`` backend type."""
    return isinstance(spec, dict) and str(spec.get("type") or "").lower() == _S3


def build_s3_backend(spec: dict[str, Any]) -> OctopS3Backend:
    """Build Octop's S3 backend from a resolved ``s3`` spec."""
    kwargs = {key: value for key, value in spec.items() if key != "type"}
    kwargs.setdefault("addressing_style", _AUTO_ADDRESSING)
    return OctopS3Backend(S3Config.from_kwargs(**kwargs))


def materialize_s3_backends(spec: Any) -> Any:
    """Replace every ``s3`` spec in a backend tree with a prebuilt backend instance.

    ``resolve_backend`` returns pre-built instances untouched, so materializing
    before resolution keeps harness (and its incompatible ``deepagents-backends``
    preference) out of the S3 path. Composite ``default`` / ``routes`` are walked
    so nested S3 routes are covered; everything else is returned unchanged.
    """
    if spec_is_s3(spec):
        return build_s3_backend(spec)
    if not isinstance(spec, dict) or spec.get("type") != "composite":
        return spec
    materialized = dict(spec)
    if "default" in materialized:
        materialized["default"] = materialize_s3_backends(materialized["default"])
    routes = materialized.get("routes")
    if isinstance(routes, dict):
        materialized["routes"] = {
            prefix: materialize_s3_backends(sub) for prefix, sub in routes.items()
        }
    return materialized
