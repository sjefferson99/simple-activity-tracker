def test_healthz_reports_ok_with_a_migrated_db(app_client) -> None:
    response = app_client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert "version" in body
