"""Links into the web interface, and the way there through its menu.

A link is relative unless OITC_PUBLIC_URL is set. This server often reaches
openITCOCKPIT under an address a browser cannot, such as a container name, so
OITC_BASEURL is no base for a link. A relative link works wherever the answer
is shown inside openITCOCKPIT itself.
"""

from __future__ import annotations

from openitcockpit_mcp.api.navigation import Page
from openitcockpit_mcp.config import Settings

#: Where the web interface is served.
APP = "/a"


def link(settings: Settings, route: str) -> str:
    return f"{settings.public_url.rstrip('/')}{APP}/{route.lstrip('/')}"


def way(page: Page) -> list[str]:
    """Menu entries to click through, from the headline down to the page."""
    return [*page.trail, page.title]


def list_page(pages: list[Page], controller: str) -> Page | None:
    """A controller's list page, if the user has it in their menu."""
    for page in pages:
        if page.controller == controller.lower() and page.route.lower().endswith("/index"):
            return page
    return None
