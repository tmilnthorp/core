"""Tests for the Hot Spring integration."""

from unittest.mock import patch

from pytest_homeassistant.common import MockConfigEntry

from homeassistant.components.hotspring.const import DOMAIN
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


async def setup_with_selected_platforms(
    hass: HomeAssistant, entry: MockConfigEntry, platforms: list[Platform]
) -> None:
    """Set up the Hot Spring integration with the selected platforms."""
    entry.add_to_hass(hass)
    with patch("homeassistant.components.hotspring.PLATFORMS", platforms):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


def register_entity(
    entity_registry: er.EntityRegistry,
    platform: Platform,
    key: str,
    original_name: str | None = None,
) -> str:
    """Register an entity as an earlier setup would have, returning its id."""
    return entity_registry.async_get_or_create(
        platform,
        DOMAIN,
        f"AA:BB:CC:DD:EE:FF_{key}",
        suggested_object_id=f"connectedspa_ddeeff_{key}",
        original_name=original_name,
    ).entity_id
