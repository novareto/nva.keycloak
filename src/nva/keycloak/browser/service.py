import json
import logging
import secrets

from plone import api
from plone.rest import Service
from Products.CMFCore.utils import getToolByName
from zope.interface import implementer
from zope.publisher.interfaces import IPublishTraverse


logger = logging.getLogger(__name__)
MAX_PAGE_SIZE = 1000
MAX_OFFSET = 1_000_000


def createUser(uid, pw, email="john.doe@dummy.de", fullname="John Doe"):
    return api.user.create(
        email=email,
        username=uid,
        password=pw,
        properties={"fullname": fullname},
    )


def createUserDict(member):
    fullname = (member.getProperty("fullname") or "").strip()
    parts = fullname.split()
    return {
        "id": member.id,
        "email": member.getProperty("email"),
        "firstName": " ".join(parts[:-1]) if len(parts) > 1 else "",
        "lastName": parts[-1] if parts else "",
        "attributes": {},
        "groups": ["Member"],
    }


class KeyCloakService(Service):
    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.params = []

    def publishTraverse(self, request, name):
        self.params.append(name)
        return self

    def json_response(self, payload, status=200):
        self.request.response.setStatus(status)
        self.request.response.setHeader("Content-Type", "application/json")
        return json.dumps(payload)

    def error(self, status, message):
        return self.json_response({"message": message}, status)

    def read_json(self):
        body = self.request.get("BODY")
        if not isinstance(body, bytes) or not body:
            raise ValueError("A JSON request body is required.")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("The request body is not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise ValueError("The JSON request body must be an object.")
        return payload

    def require_single_id(self):
        if len(self.params) != 1 or not self.params[0]:
            raise ValueError("Exactly one user ID is required in the path.")
        return self.params[0]


@implementer(IPublishTraverse)
class Health(KeyCloakService):
    """Endpoint: GET /health."""

    def render(self):
        return self.json_response({"status": "ok"})


@implementer(IPublishTraverse)
class KeyCloakUsers(KeyCloakService):
    """Endpoint: GET /users."""

    def render(self):
        if not self.params:
            try:
                first = self._pagination_value("first", 0, MAX_OFFSET)
                maxuser = self._pagination_value("max", 0, MAX_PAGE_SIZE)
            except ValueError as exc:
                return self.error(400, str(exc))
            users = [createUserDict(member) for member in api.user.get_users()]
            users = users[first:]
            if maxuser:
                users = users[:maxuser]
            return self.json_response(users)

        if self.params == ["count"]:
            return self.json_response({"count": len(api.user.get_users())})

        if len(self.params) == 2 and self.params[0] == "email":
            email = self.params[1]
            for member in api.user.get_users():
                if email == member.getProperty("email"):
                    return self.json_response(createUserDict(member))
            return self.error(404, "User not found.")

        if len(self.params) == 1:
            member = api.user.get(userid=self.params[0])
            if member:
                return self.json_response(createUserDict(member))
            return self.error(404, "User not found.")

        return self.error(400, "Invalid user lookup path.")

    def _pagination_value(self, name, default, maximum):
        value = self.request.get(name)
        if value in (None, ""):
            return default
        try:
            value = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a non-negative integer.") from exc
        if value < 0 or value > maximum:
            raise ValueError(f"{name} must be between 0 and {maximum}.")
        return value


@implementer(IPublishTraverse)
class KeyCloakCreateUser(KeyCloakService):
    """Endpoint: POST /users."""

    def render(self):
        try:
            payload = self.read_json()
        except ValueError as exc:
            return self.error(400, str(exc))

        uid = payload.get("id")
        if not isinstance(uid, str) or not uid.strip():
            return self.error(400, "id must be a non-empty string.")
        uid = uid.strip()
        if api.user.get(userid=uid):
            return self.error(409, "User already exists.")

        email = payload.get("email", "john.doe@dummy.de")
        first_name = payload.get("firstName", "John")
        last_name = payload.get("lastName", "Doe")
        if not all(isinstance(value, str) for value in (email, first_name, last_name)):
            return self.error(400, "email and name fields must be strings.")
        fullname = f"{first_name} {last_name}".strip()

        try:
            createUser(uid, secrets.token_urlsafe(32), email, fullname)
        except Exception:
            logger.exception("Unable to create Keycloak user %r", uid)
            return self.error(500, "User creation failed.")
        self.request.response.setStatus(204)
        return None


@implementer(IPublishTraverse)
class KeyCloakUpdateUser(KeyCloakService):
    """Endpoint: PUT /users/{id}."""

    def render(self):
        try:
            uid = self.require_single_id()
            payload = self.read_json()
        except ValueError as exc:
            return self.error(400, str(exc))

        if payload.get("id") != uid:
            return self.error(400, "Path and body user IDs must match.")
        email = payload.get("email")
        first_name = payload.get("firstName")
        last_name = payload.get("lastName")
        if not all(isinstance(value, str) for value in (email, first_name, last_name)):
            return self.error(
                400, "email, firstName and lastName are required strings."
            )

        pm = getToolByName(self.context, "portal_membership")
        member = pm.getMemberById(uid)
        if not member:
            return self.error(404, "User not found.")
        try:
            member.setMemberProperties(
                mapping={
                    "email": email,
                    "fullname": f"{first_name} {last_name}".strip(),
                }
            )
        except Exception:
            logger.exception("Unable to update Keycloak user %r", uid)
            return self.error(500, "User update failed.")
        self.request.response.setStatus(204)
        return None


@implementer(IPublishTraverse)
class KeyCloakDeleteUser(KeyCloakService):
    """Endpoint: DELETE /users/{id}."""

    def render(self):
        try:
            uid = self.require_single_id()
        except ValueError as exc:
            return self.error(400, str(exc))
        existing_user = api.user.get(userid=uid)
        if not existing_user:
            return self.error(404, "User not found.")
        try:
            api.user.delete(user=existing_user)
        except Exception:
            logger.exception("Unable to delete Keycloak user %r", uid)
            return self.error(500, "User deletion failed.")
        self.request.response.setStatus(204)
        return None


@implementer(IPublishTraverse)
class KeyCloakCredentials(KeyCloakService):
    """Endpoint: POST /credentials/{id}."""

    def render(self):
        try:
            uid = self.require_single_id()
            payload = self.read_json()
        except ValueError as exc:
            return self.error(400, str(exc))
        password = payload.get("value")
        if not isinstance(password, str) or not password:
            return self.error(400, "value must be a non-empty string.")

        member = api.user.get(userid=uid)
        if member:
            uf = getToolByName(self.context, "acl_users")
            if uf.authenticate(uid, password, self.request):
                self.request.response.setStatus(204)
                return None
        return self.error(401, "Invalid user ID or credential.")


@implementer(IPublishTraverse)
class KeyCloakUpdateCredentials(KeyCloakService):
    """Endpoint: PUT /credentials/{id}."""

    def render(self):
        try:
            uid = self.require_single_id()
            payload = self.read_json()
        except ValueError as exc:
            return self.error(400, str(exc))
        password = payload.get("value")
        if not isinstance(password, str) or not password:
            return self.error(400, "value must be a non-empty string.")

        member = api.user.get(userid=uid)
        try:
            if not member:
                createUser(uid, password)
            else:
                member.setSecurityProfile(password=password)
        except Exception:
            logger.exception("Unable to update credentials for %r", uid)
            return self.error(500, "Credential update failed.")
        self.request.response.setStatus(204)
        return None
