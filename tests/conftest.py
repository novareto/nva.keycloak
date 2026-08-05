from nva.keycloak.testing import NVA_KEYCLOAK_ACCEPTANCE_TESTING
from nva.keycloak.testing import NVA_KEYCLOAK_FUNCTIONAL_TESTING
from nva.keycloak.testing import NVA_KEYCLOAK_INTEGRATION_TESTING
from pytest_plone import fixtures_factory


pytest_plugins = ["pytest_plone"]


globals().update(
    fixtures_factory((
        (NVA_KEYCLOAK_ACCEPTANCE_TESTING, "acceptance"),
        (NVA_KEYCLOAK_FUNCTIONAL_TESTING, "functional"),
        (NVA_KEYCLOAK_INTEGRATION_TESTING, "integration"),
    ))
)
