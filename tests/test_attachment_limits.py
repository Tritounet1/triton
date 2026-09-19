"""Attachment limits apply to the whole request, not only each file."""

import pytest
from fastapi import HTTPException

import server


def test_total_attachment_limit_blocks_many_individually_valid_files(monkeypatch):
    # Eight base64 characters estimate to six decoded bytes. Each attachment
    # is below the per-file ceiling; together they cross this test-sized cap.
    monkeypatch.setattr(server, "MAX_ATTACHMENT_BYTES", 8)
    monkeypatch.setattr(server, "MAX_TOTAL_ATTACHMENT_BYTES", 10)
    attachments = [
        server.Attachment(name="first.png", data_url="data:image/png;base64,AAAAAAAA"),
        server.Attachment(name="second.png", data_url="data:image/png;base64,AAAAAAAA"),
    ]

    with pytest.raises(HTTPException, match="attachments exceed") as exc_info:
        server.validate_attachments(attachments)

    assert exc_info.value.status_code == 400


def test_total_attachment_limit_accepts_files_below_the_combined_ceiling(monkeypatch):
    monkeypatch.setattr(server, "MAX_ATTACHMENT_BYTES", 8)
    monkeypatch.setattr(server, "MAX_TOTAL_ATTACHMENT_BYTES", 12)
    attachments = [
        server.Attachment(name="first.png", data_url="data:image/png;base64,AAAAAAAA"),
        server.Attachment(name="second.png", data_url="data:image/png;base64,AAAAAAAA"),
    ]

    server.validate_attachments(attachments)
