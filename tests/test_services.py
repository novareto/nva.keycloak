"""Integration tests for the Keycloak SPI service implementations."""

import json
from types import SimpleNamespace

from nva.keycloak.browser import service as service_module
from nva.keycloak.browser.service import createUserDict
from nva.keycloak.browser.service import Health
from nva.keycloak.browser.service import KeyCloakCreateUser
from nva.keycloak.browser.service import KeyCloakCredentials
from nva.keycloak.browser.service import KeyCloakDeleteUser
from nva.keycloak.browser.service import KeyCloakUpdateCredentials
from nva.keycloak.browser.service import KeyCloakUpdateUser
from nva.keycloak.browser.service import KeyCloakUsers
from plone import api
from plone.app.testing import setRoles
from plone.app.testing import TEST_USER_ID
from zope.publisher.browser import TestRequest as BrowserTestRequest

import pytest


MISSING = object()


def request(body=MISSING, raw_body=None, **form):
    if body is not MISSING:
        form["BODY"] = json.dumps(body).encode()
    elif raw_body is not None:
        form["BODY"] = raw_body
    return BrowserTestRequest(form=form)


def make_service(factory, portal, body=MISSING, params=(), raw_body=None, **form):
    instance = factory(portal, request(body, raw_body, **form))
    for param in params:
        instance.publishTraverse(instance.request, param)
    return instance


def result(instance):
    body = instance.render()
    return instance.request.response.getStatus(), body


def json_result(instance):
    status, body = result(instance)
    return status, json.loads(body) if body else None


def create_user(username, credential="S3cure-test-password!", **kwargs):
    kwargs.setdefault("email", f"{username}@example.test")
    return api.user.create(username=username, password=credential, **kwargs)


def test_health_returns_explicit_json_success(portal):
    instance = make_service(Health, portal)

    assert json_result(instance) == (200, {"status": "ok"})
    assert instance.request.response.getHeader("Content-Type") == "application/json"


@pytest.mark.parametrize(
    ("fullname", "first_name", "last_name"),
    [
        ("", "", ""),
        ("Bob", "", "Bob"),
        ("Alice Maria Müller", "Alice Maria", "Müller"),
        ("  Alice   Example  ", "Alice", "Example"),
    ],
)
def test_user_representation_handles_name_shapes(fullname, first_name, last_name):
    member = SimpleNamespace(
        id="user",
        getProperty=lambda name: {
            "email": "user@example.test",
            "fullname": fullname,
        }[name],
    )

    value = createUserDict(member)

    assert value["firstName"] == first_name
    assert value["lastName"] == last_name


def test_users_list_count_and_lookup_by_id_and_email(portal):
    create_user(
        "alice",
        email="alice@example.test",
        properties={"fullname": "Alice Example"},
    )

    listed = json_result(make_service(KeyCloakUsers, portal))
    count = json_result(make_service(KeyCloakUsers, portal, params=("count",)))
    by_id = json_result(make_service(KeyCloakUsers, portal, params=("alice",)))
    by_email = json_result(
        make_service(
            KeyCloakUsers,
            portal,
            params=("email", "alice@example.test"),
        )
    )

    expected = {
        "id": "alice",
        "email": "alice@example.test",
        "firstName": "Alice",
        "lastName": "Example",
        "attributes": {},
        "groups": ["Member"],
    }
    assert listed[0] == 200
    assert expected in listed[1]
    assert count == (200, {"count": len(api.user.get_users())})
    assert by_id == by_email == (200, expected)


@pytest.mark.parametrize(
    ("first", "maximum", "expected_slice"),
    [
        (None, None, slice(None)),
        ("0", "2", slice(0, 2)),
        ("1", "2", slice(1, 3)),
        ("999", "2", slice(999, 1001)),
    ],
)
def test_users_list_pagination(portal, first, maximum, expected_slice):
    for username in ("page-user-1", "page-user-2", "page-user-3"):
        create_user(username, email=f"{username}@example.test")
    all_users = json_result(make_service(KeyCloakUsers, portal))[1]
    form = {
        key: value
        for key, value in {"first": first, "max": maximum}.items()
        if value is not None
    }

    response = json_result(make_service(KeyCloakUsers, portal, **form))

    assert response == (200, all_users[expected_slice])


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("first", "-1"),
        ("first", "text"),
        ("first", "1000001"),
        ("max", "-1"),
        ("max", "1.5"),
        ("max", "1001"),
    ],
)
def test_users_list_rejects_invalid_pagination(portal, name, value):
    status, body = json_result(make_service(KeyCloakUsers, portal, **{name: value}))

    assert status == 400
    assert name in body["message"]


@pytest.mark.parametrize(
    "params",
    [("missing",), ("email", "missing@example.test")],
)
def test_unknown_user_lookup_returns_not_found(portal, params):
    status, body = json_result(make_service(KeyCloakUsers, portal, params=params))

    assert status == 404
    assert body == {"message": "User not found."}


def test_invalid_user_lookup_path_is_rejected(portal):
    status, _ = json_result(
        make_service(KeyCloakUsers, portal, params=("email", "a@example.test", "extra"))
    )

    assert status == 400


def test_create_user_persists_supplied_profile(portal):
    instance = make_service(
        KeyCloakCreateUser,
        portal,
        {
            "id": "new-user",
            "email": "new@example.test",
            "firstName": "New",
            "lastName": "User",
        },
    )

    assert result(instance) == (204, None)
    member = api.user.get(userid="new-user")
    assert member.getProperty("email") == "new@example.test"
    assert member.getProperty("fullname") == "New User"


def test_create_duplicate_user_returns_conflict(portal):
    create_user("duplicate")

    status, _ = json_result(
        make_service(KeyCloakCreateUser, portal, {"id": "duplicate"})
    )

    assert status == 409


@pytest.mark.parametrize(
    "body",
    [{}, {"id": None}, {"id": 3}, {"id": ""}, {"id": "valid", "email": None}],
)
def test_create_user_rejects_invalid_fields(portal, body):
    status, _ = json_result(make_service(KeyCloakCreateUser, portal, body))

    assert status == 400
    if isinstance(body.get("id"), str) and body["id"]:
        assert api.user.get(userid=body["id"]) is None


@pytest.mark.parametrize("raw_body", [b"", b"not-json", b"\xff"])
def test_create_user_rejects_missing_or_malformed_json(portal, raw_body):
    status, _ = json_result(make_service(KeyCloakCreateUser, portal, raw_body=raw_body))

    assert status == 400


def test_create_user_backend_failure_returns_server_error(portal, monkeypatch):
    monkeypatch.setattr(
        service_module,
        "createUser",
        lambda *args: (_ for _ in ()).throw(RuntimeError()),
    )

    status, _ = json_result(make_service(KeyCloakCreateUser, portal, {"id": "broken"}))

    assert status == 500


def test_update_user_persists_profile(portal):
    create_user("updated")
    instance = make_service(
        KeyCloakUpdateUser,
        portal,
        {
            "id": "updated",
            "email": "changed@example.test",
            "firstName": "Changed",
            "lastName": "Name",
        },
        params=("updated",),
    )

    assert result(instance) == (204, None)
    member = api.user.get(userid="updated")
    assert member.getProperty("email") == "changed@example.test"
    assert member.getProperty("fullname") == "Changed Name"


@pytest.mark.parametrize(
    ("params", "body", "expected_status"),
    [
        ((), {"id": "user", "email": "e", "firstName": "F", "lastName": "L"}, 400),
        (
            ("path-id",),
            {"id": "body-id", "email": "e", "firstName": "F", "lastName": "L"},
            400,
        ),
        (
            ("missing",),
            {"id": "missing", "email": "e", "firstName": "F", "lastName": "L"},
            404,
        ),
        (
            ("user",),
            {"id": "user", "email": None, "firstName": "F", "lastName": "L"},
            400,
        ),
    ],
)
def test_update_user_rejects_invalid_request(portal, params, body, expected_status):
    status, _ = json_result(
        make_service(KeyCloakUpdateUser, portal, body, params=params)
    )

    assert status == expected_status


def test_update_user_backend_failure_returns_server_error(portal, monkeypatch):
    member = SimpleNamespace(
        setMemberProperties=lambda **kwargs: (_ for _ in ()).throw(RuntimeError())
    )
    membership = SimpleNamespace(getMemberById=lambda uid: member)
    monkeypatch.setattr(service_module, "getToolByName", lambda *args: membership)
    body = {"id": "broken", "email": "e", "firstName": "F", "lastName": "L"}

    status, _ = json_result(
        make_service(KeyCloakUpdateUser, portal, body, params=("broken",))
    )

    assert status == 500


def test_delete_existing_user_returns_no_content(portal):
    setRoles(portal, TEST_USER_ID, ["Manager"])
    create_user("deleted")

    response = result(make_service(KeyCloakDeleteUser, portal, params=("deleted",)))

    assert response == (204, None)
    assert api.user.get(userid="deleted") is None


@pytest.mark.parametrize(
    ("params", "expected_status"), [((), 400), (("missing",), 404), (("a", "b"), 400)]
)
def test_delete_rejects_invalid_or_missing_user(portal, params, expected_status):
    status, _ = json_result(make_service(KeyCloakDeleteUser, portal, params=params))

    assert status == expected_status


def test_delete_backend_failure_returns_server_error(portal, monkeypatch):
    create_user("broken-delete")
    membership = SimpleNamespace(
        deleteMembers=lambda ids: (_ for _ in ()).throw(RuntimeError())
    )
    monkeypatch.setattr(service_module, "getToolByName", lambda *args: membership)

    status, _ = json_result(
        make_service(KeyCloakDeleteUser, portal, params=("broken-delete",))
    )

    assert status == 500
    assert api.user.get(userid="broken-delete") is not None


def test_credentials_verify_correct_and_reject_wrong_password(portal):
    create_user("credential-user", credential="old-password")

    correct = result(
        make_service(
            KeyCloakCredentials,
            portal,
            {"value": "old-password"},
            params=("credential-user",),
        )
    )
    wrong = json_result(
        make_service(
            KeyCloakCredentials,
            portal,
            {"value": "wrong-password"},
            params=("credential-user",),
        )
    )
    unknown = json_result(
        make_service(
            KeyCloakCredentials, portal, {"value": "old-password"}, params=("unknown",)
        )
    )

    assert correct == (204, None)
    assert wrong == unknown == (401, {"message": "Invalid user ID or credential."})


@pytest.mark.parametrize(
    ("params", "body"),
    [
        ((), {"value": "password"}),
        (("user",), {}),
        (("user",), {"value": ""}),
        (("user",), {"value": None}),
    ],
)
def test_credentials_reject_invalid_requests(portal, params, body):
    status, _ = json_result(
        make_service(KeyCloakCredentials, portal, body, params=params)
    )

    assert status == 400


def test_update_credentials_changes_existing_password(portal):
    create_user("password-user", credential="old-password")

    changed = result(
        make_service(
            KeyCloakUpdateCredentials,
            portal,
            {"value": "new-password"},
            params=("password-user",),
        )
    )
    new = result(
        make_service(
            KeyCloakCredentials,
            portal,
            {"value": "new-password"},
            params=("password-user",),
        )
    )
    old = json_result(
        make_service(
            KeyCloakCredentials,
            portal,
            {"value": "old-password"},
            params=("password-user",),
        )
    )

    assert changed == (204, None)
    assert new == (204, None)
    assert old[0] == 401


def test_update_credentials_creates_missing_user(portal):
    response = result(
        make_service(
            KeyCloakUpdateCredentials,
            portal,
            {"value": "new-password"},
            params=("created-by-credentials",),
        )
    )

    assert response == (204, None)
    assert api.user.get(userid="created-by-credentials") is not None


@pytest.mark.parametrize(
    ("params", "body"),
    [
        ((), {"value": "password"}),
        (("user",), {}),
        (("user",), {"value": ""}),
        (("a", "b"), {"value": "password"}),
    ],
)
def test_update_credentials_rejects_invalid_requests(portal, params, body):
    status, _ = json_result(
        make_service(KeyCloakUpdateCredentials, portal, body, params=params)
    )

    assert status == 400


def test_update_credentials_backend_failure_returns_server_error(portal, monkeypatch):
    member = SimpleNamespace(
        setSecurityProfile=lambda **kwargs: (_ for _ in ()).throw(RuntimeError())
    )
    monkeypatch.setattr(service_module.api.user, "get", lambda **kwargs: member)

    status, _ = json_result(
        make_service(
            KeyCloakUpdateCredentials, portal, {"value": "password"}, params=("broken",)
        )
    )

    assert status == 500
