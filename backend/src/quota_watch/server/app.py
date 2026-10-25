from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Request, Response, status

from quota_watch import __version__
from quota_watch.common.models import DeviceSnapshot
from quota_watch.server.aggregation import aggregate_snapshots
from quota_watch.server.config import ServerConfig
from quota_watch.server.security import (
    SlidingWindowLimiter,
    verify_device_request,
    widget_key_is_valid,
)
from quota_watch.server.storage import Storage


def create_app(config: ServerConfig | None = None) -> FastAPI:
    settings = config or ServerConfig.from_env()
    storage = Storage(settings.database_path)
    device_limiter = SlidingWindowLimiter(settings.ingest_requests_per_minute)
    ingest_ip_limiter = SlidingWindowLimiter(settings.ingest_requests_per_ip_minute)
    global_ingest_limiter = SlidingWindowLimiter(
        settings.global_ingest_requests_per_minute, max_keys=1
    )
    widget_ip_limiter = SlidingWindowLimiter(settings.widget_requests_per_ip_minute)
    app = FastAPI(
        title="Quota Watch Bridge",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.post("/v1/ingest/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def ingest(
        device_id: str,
        request: Request,
        x_qwb_timestamp: str | None = Header(default=None),
        x_qwb_nonce: str | None = Header(default=None),
        x_qwb_signature: str | None = Header(default=None),
    ) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        if not global_ingest_limiter.allow("global"):
            raise HTTPException(
                status_code=429,
                detail="rate limit exceeded",
                headers={"Retry-After": "60"},
            )
        if not ingest_ip_limiter.allow(client_ip):
            raise HTTPException(
                status_code=429,
                detail="rate limit exceeded",
                headers={"Retry-After": "60"},
            )
        content_length = request.headers.get("content-length")
        try:
            if content_length and int(content_length) > settings.max_body_bytes:
                raise HTTPException(status_code=413, detail="payload too large")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid content length") from exc
        secret = settings.device_keys.get(device_id)
        if not secret:
            raise HTTPException(status_code=401, detail="invalid credentials")
        body = await request.body()
        if len(body) > settings.max_body_bytes:
            raise HTTPException(status_code=413, detail="payload too large")
        if not x_qwb_timestamp or not x_qwb_nonce or not x_qwb_signature:
            raise HTTPException(status_code=401, detail="invalid credentials")

        now = datetime.now(timezone.utc)
        valid = verify_device_request(
            secret=secret,
            method=request.method,
            path=request.url.path,
            timestamp=x_qwb_timestamp,
            nonce=x_qwb_nonce,
            body=body,
            provided_signature=x_qwb_signature,
            now=now,
            max_age_seconds=settings.signature_max_age_seconds,
        )
        if not valid:
            raise HTTPException(status_code=401, detail="invalid credentials")
        # Invalid traffic cannot consume the authenticated device's allowance.
        if not device_limiter.allow(device_id):
            raise HTTPException(
                status_code=429,
                detail="rate limit exceeded",
                headers={"Retry-After": "60"},
            )
        if not storage.claim_nonce(
            device_id=device_id,
            nonce=x_qwb_nonce,
            now=now,
            ttl_seconds=settings.signature_max_age_seconds,
        ):
            raise HTTPException(status_code=409, detail="replayed request")

        try:
            snapshot = DeviceSnapshot.model_validate_json(body)
        except Exception as exc:
            raise HTTPException(status_code=422, detail="invalid snapshot") from exc
        if snapshot.device_id != device_id:
            raise HTTPException(status_code=422, detail="device id mismatch")
        if abs((now - snapshot.sent_at).total_seconds()) > settings.signature_max_age_seconds:
            raise HTTPException(status_code=422, detail="snapshot timestamp outside allowed window")
        storage.save_snapshot(snapshot, now)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/v1/widget")
    def widget(
        request: Request,
        response: Response,
        x_widget_key: str | None = Header(default=None),
    ) -> dict:
        client_ip = request.client.host if request.client else "unknown"
        if not widget_ip_limiter.allow(client_ip):
            raise HTTPException(
                status_code=429,
                detail="rate limit exceeded",
                headers={"Retry-After": "60"},
            )
        if not widget_key_is_valid(x_widget_key, settings.widget_keys):
            raise HTTPException(status_code=401, detail="invalid widget key")
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Vary"] = "X-Widget-Key"
        now = datetime.now(timezone.utc)
        return aggregate_snapshots(
            storage.list_snapshots(),
            now=now,
            device_stale_seconds=settings.device_stale_seconds,
            limit_stale_seconds=settings.limit_stale_seconds,
            active_state_ttl_seconds=settings.active_state_ttl_seconds,
            limit_source_devices=settings.limit_source_devices,
        )

    return app


def run() -> None:
    import uvicorn

    uvicorn.run("quota_watch.server.app:create_app", factory=True, host="127.0.0.1", port=8787)


app = None
