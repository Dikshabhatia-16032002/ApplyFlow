import hashlib

from app.config import get_settings


def _upload(client, content: bytes, filename: str, data: dict[str, str] | None = None):
    return client.post(
        "/api/v1/resumes",
        files={"file": (filename, content, "application/pdf")},
        data=data or {},
    )


def test_rejects_a_file_that_is_not_a_pdf(client, storage) -> None:
    wrong_type = _upload(client, b"hello", "notes.txt")
    assert wrong_type.status_code == 422
    assert wrong_type.json()["code"] == "invalid_pdf"

    wrong_body = _upload(client, b"not a pdf", "resume.pdf")
    assert wrong_body.status_code == 422
    assert wrong_body.json()["code"] == "invalid_pdf"


def test_rejects_a_file_over_the_size_limit(client, storage, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "max_resume_bytes", 8)
    response = _upload(client, b"%PDF-1.4\ntoo-long", "Test Big.pdf", {"name": "Test Big"})
    assert response.status_code == 413
    assert response.json()["code"] == "file_too_large"


def test_upload_assign_default_replace_and_download(client, storage) -> None:
    profile = client.post("/api/v1/profiles", json={"name": "Test Platform"}).json()
    first_bytes = b"%PDF-1.4\nfirst"
    first = _upload(
        client,
        first_bytes,
        "../../Test Primary.pdf",
        {"name": "Test Primary", "is_default": "true"},
    )
    assert first.status_code == 201
    saved = first.json()
    assert saved["original_filename"] == "Test Primary.pdf"
    assert saved["is_default"] is True
    assert saved["sha256"] == hashlib.sha256(first_bytes).hexdigest()
    assert saved["content_type"] == "application/pdf"

    second_bytes = b"%PDF-1.4\nsecond"
    second = _upload(
        client,
        second_bytes,
        "Test Secondary.pdf",
        {"name": "Test Secondary", "profile_ids": profile["id"]},
    )
    assert second.status_code == 201
    assert client.get(f"/api/v1/profiles/{profile['id']}").json()["resume_id"] == second.json()["id"]

    promoted = client.patch(
        f"/api/v1/resumes/{second.json()['id']}",
        json={"is_default": True},
    )
    assert promoted.status_code == 200
    assert promoted.json()["is_default"] is True
    assert client.get(f"/api/v1/resumes/{saved['id']}").json()["is_default"] is False

    cleared = client.patch(f"/api/v1/resumes/{second.json()['id']}", json={"profile_ids": []})
    assert cleared.json()["profile_ids"] == []
    assert client.get(f"/api/v1/profiles/{profile['id']}").json()["resume_id"] is None

    replaced_bytes = b"%PDF-1.4\nreplaced"
    replaced = client.post(
        f"/api/v1/resumes/{saved['id']}/replace",
        files={"file": ("../../other.pdf", replaced_bytes, "application/pdf")},
    )
    assert replaced.status_code == 200
    assert replaced.json()["id"] == saved["id"]
    assert replaced.json()["original_filename"] == "other.pdf"
    assert replaced.json()["sha256"] == hashlib.sha256(replaced_bytes).hexdigest()

    download = client.get(f"/api/v1/resumes/{saved['id']}/file")
    assert download.status_code == 200
    assert download.content == replaced_bytes

    inactive = client.patch(f"/api/v1/resumes/{second.json()['id']}", json={"is_active": False})
    assert inactive.json()["is_active"] is False
    assert inactive.json()["is_default"] is False

    blocked = _upload(client, b"%PDF-1.4\nnope", "Test Idle.pdf", {"name": "Test Idle", "is_active": "false", "is_default": "true"})
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "inactive_default"
