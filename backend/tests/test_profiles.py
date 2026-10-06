def test_lists_seeded_profiles(client) -> None:
    response = client.get("/api/v1/profiles", params={"limit": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 1
    assert len(body["items"]) == 1
    assert body["total"] >= 7

    software = client.get("/api/v1/profiles", params={"limit": 200}).json()
    match = next(item for item in software["items"] if item["name"] == "Software Engineer")
    assert "swe" in match["keywords"]
    assert "software engineer" in match["keywords"]


def test_create_normalizes_keywords_and_keeps_the_name(client) -> None:
    created = client.post(
        "/api/v1/profiles",
        json={"name": "Test Full-Stack", "keywords": ["Test Full-Stack", "platform-specialist"], "priority": 3},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["keywords"] == ["platform specialist", "test full stack"]
    assert body["priority"] == 3

    replaced = client.put(
        f"/api/v1/profiles/{body['id']}/keywords",
        json={"keywords": ["beta"]},
    )
    assert replaced.status_code == 200
    assert replaced.json()["keywords"] == ["beta", "test full stack"]

    renamed = client.patch(f"/api/v1/profiles/{body['id']}", json={"name": "Test Marker Two"})
    assert renamed.status_code == 200
    assert renamed.json()["keywords"] == ["beta", "test marker two"]


def test_keyword_owned_by_an_active_profile_is_rejected(client) -> None:
    response = client.post("/api/v1/profiles", json={"name": "Test SWE Clash", "keywords": ["swe"]})
    assert response.status_code == 409
    assert response.json()["code"] == "keyword_conflict"
    assert "Software Engineer" in response.json()["detail"]


def test_inactive_profile_can_hold_a_keyword_until_it_is_activated(client) -> None:
    listed = client.get("/api/v1/profiles", params={"limit": 200}).json()["items"]
    frontend = next(item for item in listed if item["name"] == "Frontend Engineer")
    removed = client.delete(f"/api/v1/profiles/{frontend['id']}")
    assert removed.status_code == 200
    assert removed.json()["is_active"] is False
    assert "react" in removed.json()["keywords"]
    created = client.post("/api/v1/profiles", json={"name": "Test React Bench", "keywords": ["react"]})
    try:
        assert created.status_code == 201
        blocked = client.patch(f"/api/v1/profiles/{frontend['id']}", json={"is_active": True})
        assert blocked.status_code == 409
        assert blocked.json()["code"] == "keyword_conflict"
    finally:
        if created.status_code == 201:
            client.delete(f"/api/v1/profiles/{created.json()['id']}")
        restored = client.patch(f"/api/v1/profiles/{frontend['id']}", json={"is_active": True})
        assert restored.status_code == 200


def test_deactivate_keeps_the_row(client) -> None:
    created = client.post("/api/v1/profiles", json={"name": "Test Archive"}).json()
    removed = client.delete(f"/api/v1/profiles/{created['id']}")
    assert removed.json()["is_active"] is False
    fetched = client.get(f"/api/v1/profiles/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["keywords"] == ["test archive"]
    missing = client.get("/api/v1/profiles/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"


def test_duplicate_profile_name_is_rejected(client) -> None:
    response = client.post("/api/v1/profiles", json={"name": "Software Engineer"})
    assert response.status_code == 409
    assert response.json()["code"] == "name_taken"
