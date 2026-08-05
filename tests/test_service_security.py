"""Security configuration tests for the published SPI services."""

from pathlib import Path
from xml.etree import ElementTree


PLONE_NAMESPACE = "http://namespaces.plone.org/plone"


def test_account_services_require_manage_portal_permission():
    config = Path("src/nva/keycloak/browser/configure.zcml")
    root = ElementTree.parse(config).getroot()  # noqa: S314 - trusted repository file
    services = root.findall(f"{{{PLONE_NAMESPACE}}}service")
    protected = [service for service in services if service.attrib["name"] != "health"]

    assert protected
    assert all(
        service.attrib["permission"] == "cmf.ManagePortal" for service in protected
    )


def test_health_remains_publicly_viewable():
    config = Path("src/nva/keycloak/browser/configure.zcml")
    root = ElementTree.parse(config).getroot()  # noqa: S314 - trusted repository file
    services = root.findall(f"{{{PLONE_NAMESPACE}}}service")
    health = [service for service in services if service.attrib["name"] == "health"]

    assert len(health) == 1
    assert health[0].attrib["permission"] == "zope.Public"
