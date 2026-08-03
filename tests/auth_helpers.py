from typing import Any

from fastapi.testclient import TestClient


def bootstrap_admin(
    client: TestClient,
    *,
    username: str = "admin",
    display_name: str = "Администратор",
    password: str = "Strong-pass-123",
) -> dict[str, Any]:
    response = client.post(
        "/api/auth/bootstrap",
        json={
            "username": username,
            "display_name": display_name,
            "password": password,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    client.headers.update({"X-CSRF-Token": payload["csrf_token"]})
    return payload


def create_user(
    client: TestClient,
    *,
    username: str,
    display_name: str,
    password: str,
    role: str,
) -> dict[str, Any]:
    response = client.post(
        "/api/auth/users",
        json={
            "username": username,
            "display_name": display_name,
            "password": password,
            "role": role,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def login(
    client: TestClient,
    *,
    username: str,
    password: str,
) -> dict[str, Any]:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    client.headers.update({"X-CSRF-Token": payload["csrf_token"]})
    return payload
