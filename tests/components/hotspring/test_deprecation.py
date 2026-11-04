"""Tests for the deprecated Hot Spring number and select entities."""

from unittest.mock import patch

import pytest
from pytest_homeassistant.common import MockConfigEntry

from homeassistant.components.automation import DOMAIN as AUTOMATION_DOMAIN
from homeassistant.components.hotspring.const import DEPRECATED_REMOVAL_VERSION, DOMAIN
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.setup import async_setup_component

from . import register_entity, setup_with_selected_platforms

DEPRECATED_ENTITIES = pytest.mark.parametrize(
    ("platform", "key", "translation_key", "name"),
    [
        pytest.param(
            Platform.NUMBER,
            "target_temperature",
            "deprecated_number_target_temperature",
            "Target temperature",
            id="number_target_temperature",
        ),
        pytest.param(
            Platform.SELECT,
            "heating_mode",
            "deprecated_select_heating_mode",
            "Heating mode",
            id="select_heating_mode",
        ),
    ],
)


def create_stale_issue(
    hass: HomeAssistant, entry: MockConfigEntry, translation_key: str
) -> str:
    """Create a repair issue left over from an earlier setup, returning its id."""
    issue_id = f"{translation_key}_{entry.entry_id}"
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=translation_key,
        translation_placeholders={"entity_id": "x", "entity_name": "x"},
    )
    return issue_id


@DEPRECATED_ENTITIES
@pytest.mark.usefixtures("mock_hotspring")
async def test_deprecated_entity_not_created_for_new_installs(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    issue_registry: ir.IssueRegistry,
    platform: Platform,
    key: str,
    translation_key: str,
    name: str,
) -> None:
    """Test a fresh install does not create the deprecated entity."""
    issue_id = create_stale_issue(hass, mock_config_entry, translation_key)

    await setup_with_selected_platforms(hass, mock_config_entry, [platform])

    assert (
        entity_registry.async_get_entity_id(
            platform, DOMAIN, f"AA:BB:CC:DD:EE:FF_{key}"
        )
        is None
    )
    assert (DOMAIN, issue_id) not in issue_registry.issues


@DEPRECATED_ENTITIES
@pytest.mark.usefixtures("mock_hotspring")
async def test_deprecated_entity_kept_and_flagged(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    issue_registry: ir.IssueRegistry,
    platform: Platform,
    key: str,
    translation_key: str,
    name: str,
) -> None:
    """Test an existing install keeps the entity and raises a repair issue."""
    entity_id = register_entity(entity_registry, platform, key, name)

    await setup_with_selected_platforms(hass, mock_config_entry, [platform])

    assert hass.states.get(entity_id) is not None
    issue = issue_registry.async_get_issue(
        DOMAIN, f"{translation_key}_{mock_config_entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_key == translation_key
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.breaks_in_ha_version == DEPRECATED_REMOVAL_VERSION
    assert issue.config_entry_id == mock_config_entry.entry_id
    assert issue.translation_placeholders == {
        "entity_id": entity_id,
        "entity_name": name,
    }


@DEPRECATED_ENTITIES
@pytest.mark.usefixtures("mock_hotspring")
async def test_deprecated_entity_issue_names_renamed_entity(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    issue_registry: ir.IssueRegistry,
    platform: Platform,
    key: str,
    translation_key: str,
    name: str,
) -> None:
    """Test the issue names the entity the way the user renamed it."""
    entity_id = register_entity(entity_registry, platform, key)
    entity_registry.async_update_entity(entity_id, name="Hot tub")

    await setup_with_selected_platforms(hass, mock_config_entry, [platform])

    issue = issue_registry.async_get_issue(
        DOMAIN, f"{translation_key}_{mock_config_entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_placeholders["entity_name"] == "Hot tub"


@DEPRECATED_ENTITIES
@pytest.mark.parametrize(
    ("automation_id", "expected_item"),
    [
        pytest.param(
            {"id": "test_automation"},
            "[test_automation](/config/automation/edit/test_automation)",
            id="registered",
        ),
        pytest.param({}, "`automation.test_automation`", id="yaml_without_id"),
    ],
)
@pytest.mark.usefixtures("mock_hotspring")
async def test_deprecated_entity_issue_lists_automations(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    issue_registry: ir.IssueRegistry,
    platform: Platform,
    key: str,
    translation_key: str,
    name: str,
    automation_id: dict[str, str],
    expected_item: str,
) -> None:
    """Test the issue lists the automations still using the entity."""
    entity_id = register_entity(entity_registry, platform, key)
    assert await async_setup_component(
        hass,
        AUTOMATION_DOMAIN,
        {
            AUTOMATION_DOMAIN: {
                **automation_id,
                "alias": "test_automation",
                "triggers": {"trigger": "state", "entity_id": entity_id},
                "actions": {"action": "notify.notify", "data": {}},
            }
        },
    )

    await setup_with_selected_platforms(hass, mock_config_entry, [platform])

    issue = issue_registry.async_get_issue(
        DOMAIN, f"{translation_key}_{mock_config_entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_key == f"{translation_key}_scripts"
    assert issue.translation_placeholders["items"] == f"- {expected_item}"


@DEPRECATED_ENTITIES
@pytest.mark.usefixtures("mock_hotspring")
async def test_deprecated_entity_removed_when_disabled(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    issue_registry: ir.IssueRegistry,
    platform: Platform,
    key: str,
    translation_key: str,
    name: str,
) -> None:
    """Test a user-disabled entity is removed and its issue cleared."""
    entity_id = register_entity(entity_registry, platform, key)
    entity_registry.async_update_entity(
        entity_id, disabled_by=er.RegistryEntryDisabler.USER
    )
    issue_id = create_stale_issue(hass, mock_config_entry, translation_key)

    await setup_with_selected_platforms(hass, mock_config_entry, [platform])

    assert entity_registry.async_get(entity_id) is None
    assert (DOMAIN, issue_id) not in issue_registry.issues


@DEPRECATED_ENTITIES
@pytest.mark.usefixtures("mock_hotspring")
async def test_deprecated_entity_kept_when_disabled_by_device(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    issue_registry: ir.IssueRegistry,
    platform: Platform,
    key: str,
    translation_key: str,
    name: str,
) -> None:
    """Test an entity disabled along with its device is neither removed nor flagged."""
    mock_config_entry.add_to_hass(hass)
    device_entry = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, "AA:BB:CC:DD:EE:FF")},
        disabled_by=dr.DeviceEntryDisabler.USER,
    )
    entity_id = entity_registry.async_get_or_create(
        platform,
        DOMAIN,
        f"AA:BB:CC:DD:EE:FF_{key}",
        config_entry=mock_config_entry,
        device_id=device_entry.id,
        suggested_object_id=f"connectedspa_ddeeff_{key}",
    ).entity_id
    issue_id = create_stale_issue(hass, mock_config_entry, translation_key)

    with patch("homeassistant.components.hotspring.PLATFORMS", [platform]):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert entity_registry.async_get(entity_id) is not None
    assert (DOMAIN, issue_id) not in issue_registry.issues
