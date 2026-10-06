def test_template_duplicate_preview_and_default(client) -> None:
    profile = client.post("/api/v1/profiles", json={"name": "Test Outreach"}).json()
    created = client.post(
        "/api/v1/templates",
        json={
            "name": "Test Intro",
            "subject": "Hello {{name}}",
            "body": "The {{role}} role at {{company}}. {{ai_intro}}",
            "is_default": True,
            "profile_ids": [profile["id"]],
        },
    )
    assert created.status_code == 201
    saved = created.json()
    assert saved["profile_ids"] == [profile["id"]]
    assert saved["is_default"] is True
    assert client.get(f"/api/v1/profiles/{profile['id']}").json()["email_template_id"] == saved["id"]

    preview = client.post(
        "/api/v1/templates/preview",
        json={
            "template_id": saved["id"],
            "name": "Rahul Sharma",
            "company": "",
            "role": "Frontend Engineer",
        },
    )
    assert preview.status_code == 200
    rendered = preview.json()
    assert rendered["subject"] == "Hello Rahul Sharma"
    assert "Frontend Engineer" in rendered["body"]
    assert "{{ai_intro}}" in rendered["body"]
    assert rendered["empty_variables"] == ["company"]
    assert rendered["unknown_tokens"] == ["ai_intro"]

    duplicate = client.post(f"/api/v1/templates/{saved['id']}/duplicate")
    assert duplicate.status_code == 201
    copied = duplicate.json()
    assert copied["name"] == "Copy of Test Intro"
    assert copied["subject"] == saved["subject"]
    assert copied["body"] == saved["body"]
    assert copied["profile_ids"] == []
    assert copied["is_default"] is False
    assert client.get(f"/api/v1/templates/{saved['id']}").json()["profile_ids"] == [profile["id"]]

    removed = client.delete(f"/api/v1/templates/{saved['id']}")
    assert removed.json()["is_active"] is False
    assert removed.json()["is_default"] is False
    assert client.get(f"/api/v1/templates/{saved['id']}").status_code == 200


def test_long_subject_is_rejected(client) -> None:
    response = client.post(
        "/api/v1/templates",
        json={"name": "Test Long", "subject": "s" * 201, "body": "Hello"},
    )
    assert response.status_code == 422


def test_preview_requires_a_source(client) -> None:
    response = client.post("/api/v1/templates/preview", json={"name": "Rahul"})
    assert response.status_code == 422
    assert response.json()["code"] == "preview_source_required"


def test_second_default_template_clears_the_first(client) -> None:
    first = client.post(
        "/api/v1/templates",
        json={"name": "Test First", "subject": "One", "body": "Body", "is_default": True},
    ).json()
    second = client.post(
        "/api/v1/templates",
        json={"name": "Test Second", "subject": "Two", "body": "Body", "is_default": True},
    ).json()
    assert second["is_default"] is True
    assert client.get(f"/api/v1/templates/{first['id']}").json()["is_default"] is False
