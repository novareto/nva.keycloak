"""Functional HTTP tests through the real Zope publisher."""

import base64
import json

from plone.testing._z2_testbrowser import Browser


SITE_URL = "http://nohost/plone/++api++"


def browser(app, username=None, password=None):
    instance = Browser(app)
    instance.handleErrors = True
    instance.raiseHttpErrors = False
    instance.addHeader("Accept", "application/json")
    if username is not None:
        credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
        instance.addHeader("Authorization", f"Basic {credentials}")
    return instance


def test_health_is_published_for_anonymous_callers(functional_app):
    client = browser(functional_app)

    client.open(f"{SITE_URL}/health")

    assert client.headers["Status"] == "200 OK"
    assert json.loads(client.contents) == {"status": "ok"}
    assert client.headers["Content-Type"].startswith("application/json")


def test_user_listing_rejects_anonymous_callers(functional_app):
    client = browser(functional_app)

    client.open(f"{SITE_URL}/users")

    assert client.headers["Status"].startswith(("401 ", "403 "))
    assert b"john.doe@dummy.de" not in client.contents


def test_user_listing_accepts_manager_credentials(functional_app):
    client = browser(functional_app, "admin", "secret")

    client.open(f"{SITE_URL}/users")

    assert client.headers["Status"] == "200 OK"
    assert isinstance(json.loads(client.contents), list)
