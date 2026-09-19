def test_request_validation_uses_public_error_shape_without_echoing_input(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "shared"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["message"] == "Request validation failed"
    assert all("input" not in detail for detail in body["error"]["details"])
    assert "shared" not in response.text
