from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from channel_models import ChannelJobLog, PublishedPost, PublishJob
from channel_store import (
    append_channel_job_log,
    generate_id,
    get_derivative,
    get_publish_job,
    now_iso,
    save_publish_job,
    save_published_post,
)
from media_store import get_media_asset
from src.core.content import PublicationTargetStatus

from ..client import MastodonApiClient
from ..errors import MastodonError, MastodonPublishError, MastodonPublishUncertainError
from ..models import MastodonPublicationOptions, MastodonRemoteMediaUpload
from ..storage import (
    MastodonAccountRepository,
    MastodonRemoteMediaRepository,
    MastodonRequirementsRepository,
    MastodonSecretStore,
    append_audit,
    append_event,
    fingerprint,
)


def run_publish_job_with_runtime(
    config: Any, app_runtime, job_id: str, *, worker_id: str = "", started_at: str = ""
) -> PublishJob:
    job = get_publish_job(job_id)
    if job is None:
        raise RuntimeError(f"Publish job {job_id} not found.")
    derivative = get_derivative(job.derivative_id)
    if derivative is None:
        raise RuntimeError(f"Derivative {job.derivative_id} not found.")
    metadata = dict(derivative.generation_metadata_json or {})
    snapshot = dict(metadata.get("snapshot") or {})
    account_id = str(snapshot.get("channel_account_id") or job.channel_id)
    worker_id = worker_id or f"mastodon:{job.id}"
    _report(app_runtime, config, job, phase="preflight", mutation_state="not_started", status="running")
    _log(job, "running", "preflight", worker_id)
    try:
        account = MastodonAccountRepository().get(account_id)
        if account is None or account.connection_status != "connected" or account.revoked_local:
            raise MastodonPublishError("authentication_required", "Mastodon account is not connected.")
        requirements = MastodonRequirementsRepository().latest_for_account(account.channel_account_id)
        if requirements is None or requirements.checksum != snapshot.get(
            "mastodon_requirements_checksum", requirements.checksum
        ):
            raise MastodonPublishError(
                "mastodon.requirements_stale", "Mastodon requirements snapshot is missing or stale."
            )
        options = validate_options(dict(metadata.get("mastodon_options") or snapshot.get("mastodon_options") or {}))
        body = derivative.body.replace("\r\n", "\n").strip()
        if not body:
            raise MastodonPublishError("mastodon.body_required", "Mastodon status body is required.")
        if len(body) > requirements.content_length_limit:
            raise MastodonPublishError("mastodon.body_too_long", "Mastodon status body exceeds the instance limit.")
        client = MastodonApiClient(
            origin=account.instance_origin,
            transport=app_runtime.get_plugin_service("channel.mastodon", "channel_runtime").transport,
            access_token=MastodonSecretStore().get(account.token_secret_ref),
        )
        media_ids, media_evidence = _upload_media(
            config, app_runtime, job, derivative, client, requirements, worker_id=worker_id
        )
        idempotency_key = mastodon_idempotency_key(
            target_id=str(metadata.get("publication_target_id") or snapshot.get("publication_target_id") or ""),
            snapshot_checksum=str(
                metadata.get("snapshot_checksum") or job.result_details_json.get("snapshot_checksum") or ""
            ),
            generation=str(snapshot.get("execution_generation") or "1"),
            channel_account_id=account.channel_account_id,
        )
        _report(app_runtime, config, job, phase="channel_prepare", mutation_state="prepared")
        job.last_step = "api_payload_prepared"
        save_publish_job(job)
        _report(app_runtime, config, job, phase="remote_mutation", mutation_state="mutation_started")
        append_event(
            "channel.mastodon.publish.started",
            workspace_id=account.workspace_id,
            account_id=account.channel_account_id,
            metadata={"idempotency_key_fingerprint": fingerprint(idempotency_key)},
        )
        status = client.create_status(
            status=body,
            media_ids=media_ids,
            visibility=options.visibility,
            sensitive=options.sensitive,
            spoiler_text=options.spoiler_text,
            language=options.language,
            idempotency_key=idempotency_key,
        )
        _report(app_runtime, config, job, phase="remote_mutation", mutation_state="mutation_acknowledged")
        evidence = _verify_status(client, status, account, job, derivative, snapshot, media_evidence, idempotency_key)
        publication = PublishedPost(
            id=f"published_mastodon_{generate_id('post')}",
            derivative_id=derivative.id,
            source_document_id=derivative.source_document_id,
            channel_id=account.channel_account_id,
            external_id=str(status.get("uri") or status.get("id") or ""),
            external_url=str(status.get("url") or ""),
            published_at=evidence["published_at"],
            publish_job_id=job.id,
            status="confirmed",
            raw_result_json=evidence,
            created_at=now_iso(),
            updated_at=now_iso(),
        )
        saved_publication = save_published_post(publication)
        _mark_media_attached(media_ids, str(status.get("id") or ""))
        job.status = "success"
        job.finished_at = now_iso()
        job.updated_at = job.finished_at
        job.last_step = "remote_status_verified"
        job.result_url = publication.external_url
        job.result_external_id = publication.external_id
        job.result_details_json = dict(job.result_details_json or {}) | {"content_publication_evidence": evidence}
        job.claimed_by = job.claimed_at = job.lease_expires_at = job.heartbeat_at = ""
        save_publish_job(job)
        _target_published(app_runtime, config, metadata, saved_publication.id)
        _report(
            app_runtime,
            config,
            job,
            phase="cleanup",
            mutation_state="mutation_verified",
            status="succeeded",
            remote_verification_state="verified",
        )
        append_event(
            "channel.mastodon.publish.verified",
            workspace_id=account.workspace_id,
            account_id=account.channel_account_id,
            metadata={"status_uri": publication.external_id},
        )
        append_audit(
            "publish.result",
            workspace_id=account.workspace_id,
            account_id=account.channel_account_id,
            result="ok",
            metadata={"target_id": metadata.get("publication_target_id", "")},
        )
        _log(job, "success", "remote_status_verified", worker_id)
        return job
    except MastodonPublishUncertainError as exc:
        job.status = "manual_verification_required"
        job.finished_at = now_iso()
        job.updated_at = job.finished_at
        job.last_step = "mutation_uncertain"
        job.error_code = exc.code
        job.error_message = exc.safe_message
        job.unknown_result = True
        job.manual_verification_required = True
        job.claimed_by = job.claimed_at = job.lease_expires_at = job.heartbeat_at = ""
        save_publish_job(job)
        _report(
            app_runtime,
            config,
            job,
            phase="reconciliation",
            mutation_state="mutation_uncertain",
            status="uncertain",
            safe_error_code=exc.code,
        )
        append_event("channel.mastodon.publish.uncertain", metadata={"safe_error_code": exc.code})
        _log(job, job.status, "mutation_uncertain", worker_id, error_code=exc.code, error_message=exc.safe_message)
        return job
    except MastodonError as exc:
        job.status = "failed"
        job.finished_at = now_iso()
        job.updated_at = job.finished_at
        job.error_code = exc.code
        job.error_message = exc.safe_message
        job.last_step = "failed_before_verified_status"
        job.claimed_by = job.claimed_at = job.lease_expires_at = job.heartbeat_at = ""
        save_publish_job(job)
        _report(
            app_runtime,
            config,
            job,
            phase="reconciliation",
            mutation_state=exc.mutation_state,
            status="failed",
            safe_error_code=exc.code,
        )
        _log(job, "failed", job.last_step, worker_id, error_code=exc.code, error_message=exc.safe_message)
        return job


def validate_options(payload: dict[str, Any]) -> MastodonPublicationOptions:
    visibility = str(payload.get("visibility") or "public")
    if visibility not in {"public", "unlisted"}:
        raise MastodonPublishError("mastodon.visibility_unsupported", "Mastodon visibility must be public or unlisted.")
    spoiler = str(payload.get("spoiler_text") or "")
    if len(spoiler) > 500:
        raise MastodonPublishError("mastodon.spoiler_too_long", "Mastodon content warning is too long.")
    language = str(payload.get("language") or "")
    if language and not (
        2 <= len(language) <= 35 and all(part.isalnum() for part in language.replace("-", "").split())
    ):
        raise MastodonPublishError("mastodon.language_invalid", "Mastodon language tag is invalid.")
    return MastodonPublicationOptions(
        visibility=visibility, language=language, spoiler_text=spoiler, sensitive=bool(payload.get("sensitive", False))
    )


def mastodon_idempotency_key(
    *, target_id: str, snapshot_checksum: str, generation: str, channel_account_id: str
) -> str:
    digest = hashlib.sha256(f"{target_id}|{snapshot_checksum}|{generation}|{channel_account_id}".encode()).hexdigest()
    return f"smm-mastodon-{digest[:48]}"


def _upload_media(
    config, app_runtime, job, derivative, client, requirements, *, worker_id: str
) -> tuple[list[str], list[dict[str, Any]]]:
    library = app_runtime.media_library_service(config)
    try:
        resolution = library.resolve_owner_media(
            owner_type="content" if str(derivative.id).startswith("derivative_plan_") else "draft",
            owner_id=derivative.source_document_id
            if str(derivative.id).startswith("derivative_plan_")
            else derivative.id,
            workspace_id=derivative.channel_id,
            channel_plugin_id="channel.mastodon",
            capability="channel.publish.image",
            compatibility_metadata=dict(derivative.generation_metadata_json or {}),
            job_id=job.id,
        )
    except Exception as exc:
        if getattr(exc, "code", "") == "media.owner_not_found":
            return [], []
        raise
    if resolution.rejected_items and not resolution.selected_items:
        first = resolution.rejected_items[0]
        raise MastodonPublishError(first.code, first.message)
    selected = list(resolution.selected_items)[: requirements.maximum_media_count]
    media_ids: list[str] = []
    evidence: list[dict[str, Any]] = []
    repo = MastodonRemoteMediaRepository()
    for index, item in enumerate(selected):
        if item.resolved_mime_type not in set(requirements.supported_mime_types):
            raise MastodonPublishError("mastodon.media_mime_unsupported", "Mastodon media MIME type is not supported.")
        if item.width * item.height > requirements.maximum_image_pixels:
            raise MastodonPublishError(
                "mastodon.media_pixels_too_large", "Mastodon media pixel matrix exceeds instance limit."
            )
        alt_text = _alt_text(library, item.relation_id, item.asset_id)
        if alt_text and len(alt_text) > requirements.description_limit:
            raise MastodonPublishError("mastodon.alt_text_too_long", "Mastodon alt text exceeds instance limit.")
        with library.materialize_selected(
            item, workspace_id=derivative.channel_id, purpose="mastodon.image_publish", job_id=job.id
        ) as materialized:
            data = Path(materialized.local_path).read_bytes()
        if len(data) > requirements.maximum_image_bytes:
            raise MastodonPublishError("mastodon.media_file_too_large", "Mastodon media file exceeds instance limit.")
        upload = client.upload_media(
            data=data,
            filename=f"mastodon-{index}.{_extension(item.resolved_mime_type)}",
            mime_type=item.resolved_mime_type,
            description=alt_text,
        )
        attachment_id = str(upload.get("id") or "")
        if not attachment_id:
            raise MastodonPublishError(
                "mastodon.media_missing_id", "Mastodon media response did not include an attachment ID."
            )
        repo.save(
            MastodonRemoteMediaUpload(
                attachment_id=attachment_id,
                account_id=job.channel_id,
                publication_target_id=str(
                    (derivative.generation_metadata_json or {}).get("publication_target_id") or ""
                ),
                execution_attempt_id="",
                uploaded_at=now_iso(),
                processing_status="ready_unattached",
            )
        )
        append_event(
            "channel.mastodon.media.uploaded", account_id=job.channel_id, metadata={"attachment_id": attachment_id}
        )
        ready = _media_ready(client, upload, attachment_id)
        if not ready:
            raise MastodonPublishError(
                "mastodon.media_processing_timeout", "Mastodon media processing did not complete before status publish."
            )
        append_event(
            "channel.mastodon.media.ready", account_id=job.channel_id, metadata={"attachment_id": attachment_id}
        )
        media_ids.append(attachment_id)
        evidence.append(
            {
                "relation_id": item.relation_id,
                "source_asset_id": item.asset_id,
                "selected_media_variant_id": item.variant_id,
                "remote_attachment_id": attachment_id,
                "mime_type": item.resolved_mime_type,
                "checksum": item.checksum,
                "alt_text_present": bool(alt_text),
            }
        )
    return media_ids, evidence


def _media_ready(client, upload: dict[str, Any], attachment_id: str) -> bool:
    if upload.get("url") or upload.get("preview_url"):
        return True
    for _ in range(5):
        current = client.get_media(attachment_id)
        if current.get("url") or current.get("preview_url"):
            return True
    return False


def _verify_status(client, status, account, job, derivative, snapshot, media_evidence, idempotency_key):
    local_id = str(status.get("id") or "")
    uri = str(status.get("uri") or "")
    if not local_id or not uri:
        raise MastodonPublishUncertainError(
            "mastodon.status_identity_missing",
            "Mastodon status response did not include a stable identity.",
            mutation_state="mutation_uncertain",
        )
    remote_account = status.get("account") if isinstance(status.get("account"), dict) else {}
    if str(remote_account.get("id") or "") and str(remote_account.get("id")) != account.remote_account_id:
        raise MastodonPublishUncertainError(
            "mastodon.account_mismatch",
            "Mastodon status belongs to another account.",
            mutation_state="mutation_uncertain",
        )
    verified = client.get_status(local_id)
    if str(verified.get("uri") or uri) != uri:
        raise MastodonPublishUncertainError(
            "mastodon.status_verification_mismatch",
            "Mastodon status verification mismatched.",
            mutation_state="mutation_uncertain",
        )
    published_at = str(status.get("created_at") or now_iso())
    return {
        "content_item_id": derivative.source_document_id,
        "revision_id": snapshot.get("revision_id", ""),
        "revision_checksum": snapshot.get("revision_checksum", ""),
        "channel_variant_id": snapshot.get("variant_id", ""),
        "variant_checksum": snapshot.get("variant_checksum", ""),
        "media_relation_ids": snapshot.get("media_relation_ids", []),
        "source_asset_ids": snapshot.get("resolved_asset_ids", []),
        "selected_media_variant_ids": snapshot.get("resolved_variant_ids", []),
        "publication_plan_id": (derivative.generation_metadata_json or {}).get("publication_plan_id", ""),
        "publication_target_id": (derivative.generation_metadata_json or {}).get("publication_target_id", ""),
        "execution_attempt_id": "",
        "schedule_occurrence_id": snapshot.get("schedule_occurrence_id", ""),
        "campaign_id": snapshot.get("campaign_id", ""),
        "snapshot_checksum": (derivative.generation_metadata_json or {}).get("snapshot_checksum", ""),
        "instance_origin": account.instance_origin,
        "local_status_id": local_id,
        "global_status_uri": uri,
        "status_url": str(status.get("url") or ""),
        "mastodon_requirements_checksum": snapshot.get("mastodon_requirements_checksum", ""),
        "idempotency_key_fingerprint": fingerprint(idempotency_key),
        "media_publication_evidence": media_evidence,
        "published_at": published_at,
        "verified_at": now_iso(),
        "plugin_version": "0.1.0",
    }


def _alt_text(library, relation_id: str, asset_id: str) -> str:
    relation = library.relation_repository.get(relation_id)
    if relation is not None:
        relation_alt = str((relation.metadata or {}).get("alt_text") or "")
        if relation_alt:
            return relation_alt
    asset = get_media_asset(asset_id)
    return str((getattr(asset, "metadata", {}) or {}).get("alt_text") or "") if asset is not None else ""


def _extension(mime_type: str) -> str:
    return "jpg" if mime_type == "image/jpeg" else "png"


def _mark_media_attached(media_ids: list[str], status_id: str) -> None:
    repo = MastodonRemoteMediaRepository()
    for media_id in media_ids:
        record = repo.get(media_id)
        if record is not None:
            record.attached_status_id = status_id
            record.processing_status = "attached"
            record.cleanup_status = "cleanup_succeeded"
            repo.save(record)


def _target_published(app_runtime, config, metadata: dict[str, Any], publication_id: str) -> None:
    target_id = str(metadata.get("publication_target_id") or "")
    if not target_id:
        return
    planning = app_runtime.publication_planning_service(config)
    target = planning.target_repository.get(target_id)
    if target is not None:
        target.status = PublicationTargetStatus.PUBLISHED.value
        target.publication_id = publication_id
        target.updated_at = now_iso()
        planning.target_repository.save(target)
        planning.refresh_status(target.publication_plan_id, workspace_id=target.workspace_id)


def _report(app_runtime, config, job: PublishJob, **kwargs) -> None:
    try:
        app_runtime.publication_execution_service(config).report_job_phase(job_id=job.id, **kwargs)
    except Exception:
        return


def _log(
    job: PublishJob, status: str, step: str, worker_id: str, *, error_code: str = "", error_message: str = ""
) -> None:
    append_channel_job_log(
        ChannelJobLog(
            id=generate_id("log"),
            channel_id=job.channel_id,
            job_type="publish",
            job_id=job.id,
            status=status,
            last_step=step,
            error_code=error_code,
            error_message=error_message,
            created_at=now_iso(),
            worker_id=worker_id,
        )
    )
