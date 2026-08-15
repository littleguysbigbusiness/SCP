import os
import uuid

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

import sheets_client as sc

_service = None


def get_service():
    global _service
    if _service is not None:
        return _service
    _service = build("drive", "v3", credentials=sc.get_credentials(), cache_discovery=False)
    return _service


def _upload_file(file_storage, name_prefix):
    # Service accounts have no Drive storage quota of their own, so the file
    # has to land in a folder a real Google account owns and has shared with
    # the service account (Editor) - that folder's quota is what's used.
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    if not folder_id:
        raise RuntimeError("GOOGLE_DRIVE_FOLDER_ID env var is not set")

    filename = file_storage.filename or "{}-{}".format(name_prefix, uuid.uuid4().hex[:8])
    mimetype = file_storage.mimetype or "application/octet-stream"
    media = MediaIoBaseUpload(file_storage.stream, mimetype=mimetype, resumable=False)

    service = get_service()
    created = (
        service.files()
        .create(
            body={"name": filename, "parents": [folder_id]},
            media_body=media,
            fields="id, webViewLink",
        )
        .execute()
    )

    file_id = created["id"]
    service.permissions().create(fileId=file_id, body={"type": "anyone", "role": "reader"}).execute()
    return created


def upload_scan(file_storage):
    created = _upload_file(file_storage, "scan")
    file_id = created["id"]
    return created.get("webViewLink") or "https://drive.google.com/file/d/{}/view".format(file_id)


def _upload_direct_url(file_storage, name_prefix):
    # unlike upload_scan's webViewLink (an HTML viewer page - wrong for an
    # <img>/<audio> src), this returns a URL that serves the raw file bytes
    # directly, suitable for embedding.
    created = _upload_file(file_storage, name_prefix)
    return "https://drive.google.com/uc?export=view&id={}".format(created["id"])


def upload_image(file_storage):
    return _upload_direct_url(file_storage, "image")


def upload_audio(file_storage):
    return _upload_direct_url(file_storage, "audio")
