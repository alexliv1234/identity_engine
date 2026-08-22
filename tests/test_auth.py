"""Bearer api-key auth and the stable error body shape (spec §5.3, §5.4)."""


def test_missing_authorization_header_is_401(client):
    response = client.get("/v1/meta/versions")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_malformed_authorization_header_is_401(client):
    response = client.get("/v1/meta/versions", headers={"Authorization": "Basic abc"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_unknown_key_is_401(client):
    response = client.get("/v1/meta/versions", headers={"Authorization": "Bearer sk_nope"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_valid_key_is_accepted(client, auth_headers):
    assert client.get("/v1/meta/versions", headers=auth_headers).status_code == 200


def test_error_body_shape_is_stable(client):
    body = client.get("/v1/meta/versions").json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "field"}


def test_key_hashing_is_deterministic_and_not_reversible():
    from api.auth import generate_key, hash_key

    key = generate_key()
    assert key.startswith("sk_")
    assert hash_key(key) == hash_key(key)
    assert key not in hash_key(key)
    assert len(hash_key(key)) == 64


def test_generated_keys_are_unique():
    from api.auth import generate_key

    assert len({generate_key() for _ in range(100)}) == 100


def test_health_endpoint_needs_no_auth(client):
    assert client.get("/health").status_code == 200


def test_other_tenants_key_is_also_accepted_but_distinct(client, auth_headers, other_app_headers):
    # Both are valid, known keys — just for different tenants. Scoping
    # persons/profiles by tenant is a later task's job; here we only need
    # both to authenticate.
    assert client.get("/v1/meta/versions", headers=auth_headers).status_code == 200
    assert client.get("/v1/meta/versions", headers=other_app_headers).status_code == 200


def test_empty_bearer_token_is_401(client):
    response = client.get("/v1/meta/versions", headers={"Authorization": "Bearer "})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_unauthorized_message_does_not_distinguish_missing_from_unknown(client):
    """Authentication failures must not leak information: a missing header
    and a valid-format-but-unknown key must return the identical body."""
    missing = client.get("/v1/meta/versions").json()
    unknown = client.get(
        "/v1/meta/versions", headers={"Authorization": "Bearer sk_totally_unknown"}
    ).json()
    assert missing == unknown
