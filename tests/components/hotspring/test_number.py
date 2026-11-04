"""Tests for the Hot Spring number platform."""

from asyncio import TimerHandle
from datetime import timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from hotspring import HotSpringConnectionError, HotSpringError, Spa, TemperatureUnit
import pytest
from pytest_homeassistant.common import (
    MockConfigEntry,
    async_fire_time_changed,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.hotspring.const import SCAN_INTERVAL
from homeassistant.components.hotspring.number import PENDING_TARGET_TIMEOUT
from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HassJob, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util.async_ import get_scheduled_timer_handles

from . import setup_with_selected_platforms

ENTITY_ID = "number.connectedspa_ddeeff_target_temperature"


async def _set_value(hass: HomeAssistant, value: float) -> None:
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_VALUE: value},
        blocking=True,
    )


async def _tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta
) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def _pending_target_timers(hass: HomeAssistant) -> list[TimerHandle]:
    return [
        handle
        for handle in get_scheduled_timer_handles(hass.loop)
        if not handle.cancelled()
        and any(
            isinstance(arg, HassJob)
            and getattr(arg.target, "__name__", None) == "_pending_target_expired"
            for arg in handle._args
        )
    ]


async def test_number_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hotspring: MagicMock,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test the number entity state."""
    await setup_with_selected_platforms(hass, mock_config_entry, [Platform.NUMBER])
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


async def test_set_target_temperature(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_hotspring: MagicMock,
    device_fixture: Spa,
) -> None:
    """Test setting target temperature."""
    assert (state := hass.states.get(ENTITY_ID))
    assert state.state == "40.0"

    def set_temp_mock(value: float) -> None:
        device_fixture.heater.set_temperature = value

    mock_hotspring.set_temperature.side_effect = set_temp_mock

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {
            ATTR_ENTITY_ID: ENTITY_ID,
            ATTR_VALUE: 38,
        },
        blocking=True,
    )

    mock_hotspring.set_temperature.assert_called_once_with(100.0)
    mock_hotspring.update.assert_called_once()
    assert (state := hass.states.get(ENTITY_ID))
    assert state.state == "37.8"


async def test_set_target_temperature_optimistic(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_hotspring: MagicMock,
) -> None:
    """Test the requested target is shown while the command is in flight."""
    states_in_flight: list[str] = []

    async def set_temp_mock(value: float) -> None:
        assert (state := hass.states.get(ENTITY_ID))
        states_in_flight.append(state.state)

    mock_hotspring.set_temperature.side_effect = set_temp_mock

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_VALUE: 38},
        blocking=True,
    )

    assert states_in_flight == ["37.8"]


async def test_set_target_temperature_error_reverts(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_hotspring: MagicMock,
) -> None:
    """Test a failed command restores the spa's reported target."""
    mock_hotspring.set_temperature.side_effect = HotSpringConnectionError

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: ENTITY_ID, ATTR_VALUE: 38},
            blocking=True,
        )

    assert (state := hass.states.get(ENTITY_ID))
    assert state.state == "40.0"


@pytest.mark.parametrize(
    ("exception", "match"),
    [
        (
            HotSpringConnectionError,
            "An error occurred while communicating with the Hot Spring API",
        ),
        (HotSpringError, "Invalid response received from the Hot Spring API"),
    ],
)
async def test_set_target_temperature_error(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_hotspring: MagicMock,
    exception: type[Exception],
    match: str,
) -> None:
    """Test exception handling when setting target temperature."""
    mock_hotspring.set_temperature.side_effect = exception

    with pytest.raises(HomeAssistantError, match=match):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {
                ATTR_ENTITY_ID: ENTITY_ID,
                ATTR_VALUE: 38,
            },
            blocking=True,
        )


async def test_set_target_temperature_celsius(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hotspring: MagicMock,
    device_fixture: Spa,
    snapshot: SnapshotAssertion,
) -> None:
    """Test setting target temperature when the spa is configured in Celsius."""
    device_fixture.heater.temperature_unit = TemperatureUnit.CELSIUS
    device_fixture.heater.set_temperature = 38.5

    def set_temp_mock(value: float) -> None:
        device_fixture.heater.set_temperature = value

    mock_hotspring.set_temperature.side_effect = set_temp_mock

    await setup_with_selected_platforms(hass, mock_config_entry, [Platform.NUMBER])

    assert hass.states.get(ENTITY_ID) == snapshot

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {
            ATTR_ENTITY_ID: ENTITY_ID,
            ATTR_VALUE: 37.5,
        },
        blocking=True,
    )

    mock_hotspring.set_temperature.assert_called_once_with(37.5)
    assert (state := hass.states.get(ENTITY_ID))
    assert state.state == "37.5"


async def test_pending_target_survives_stale_poll(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_hotspring: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a poll still reporting the old target does not revert the request."""
    await _set_value(hass, 38)
    assert (state := hass.states.get(ENTITY_ID))
    assert state.state == "37.8"

    await _tick(hass, freezer, SCAN_INTERVAL)

    assert mock_hotspring.update.call_count == 2
    assert (state := hass.states.get(ENTITY_ID))
    assert state.state == "37.8"


async def test_pending_target_clears_when_reported(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_hotspring: MagicMock,
    device_fixture: Spa,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test the pending target gives way once the spa reports it."""
    await _set_value(hass, 38)

    device_fixture.heater.set_temperature = 100.0
    await _tick(hass, freezer, SCAN_INTERVAL)
    assert (state := hass.states.get(ENTITY_ID))
    assert state.state == "37.8"
    assert not _pending_target_timers(hass)

    # A later change made at the spa itself now shows through.
    device_fixture.heater.set_temperature = 102.0
    await _tick(hass, freezer, SCAN_INTERVAL)
    assert (state := hass.states.get(ENTITY_ID))
    assert state.state == "38.9"


async def test_pending_target_expires(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_hotspring: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test the reported target returns when the spa never confirms."""
    await _set_value(hass, 38)

    await _tick(hass, freezer, PENDING_TARGET_TIMEOUT - timedelta(seconds=1))
    assert (state := hass.states.get(ENTITY_ID))
    assert state.state == "37.8"

    await _tick(hass, freezer, timedelta(seconds=1))
    assert (state := hass.states.get(ENTITY_ID))
    assert state.state == "40.0"
    assert not _pending_target_timers(hass)


async def test_pending_target_cleared_on_error(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_hotspring: MagicMock,
) -> None:
    """Test a failed command drops the pending target and its timer."""
    mock_hotspring.set_temperature.side_effect = HotSpringConnectionError

    with pytest.raises(HomeAssistantError):
        await _set_value(hass, 38)

    assert (state := hass.states.get(ENTITY_ID))
    assert state.state == "40.0"
    assert not _pending_target_timers(hass)


async def test_second_set_replaces_timer(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_hotspring: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a new request restarts the guard instead of inheriting the old one."""
    await _set_value(hass, 38)
    await _tick(hass, freezer, timedelta(seconds=30))
    await _set_value(hass, 39)
    assert len(_pending_target_timers(hass)) == 1

    # Past the first request's guard, the second request still shows.
    await _tick(hass, freezer, PENDING_TARGET_TIMEOUT - timedelta(seconds=29))
    assert (state := hass.states.get(ENTITY_ID))
    assert state.state == "38.9"

    await _tick(hass, freezer, timedelta(seconds=30))
    assert (state := hass.states.get(ENTITY_ID))
    assert state.state == "40.0"


async def test_pending_target_timer_cancelled_on_unload(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_hotspring: MagicMock,
) -> None:
    """Test removing the entity cancels the guard timer."""
    await _set_value(hass, 38)
    assert _pending_target_timers(hass)

    assert await hass.config_entries.async_unload(init_integration.entry_id)

    assert not _pending_target_timers(hass)
