"""Tests for the Hot Spring light platform."""

from asyncio import TimerHandle
from datetime import timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from hotspring import (
    HotSpringConnectionError,
    HotSpringError,
    LightColor,
    LightWheelMode,
    LightZone,
    Spa,
)
import pytest
from pytest_homeassistant.common import (
    MockConfigEntry,
    async_fire_time_changed,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.hotspring.const import SCAN_INTERVAL
from homeassistant.components.hotspring.light import PENDING_STATE_TIMEOUT
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    DOMAIN as LIGHT_DOMAIN,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    Platform,
)
from homeassistant.core import HassJob, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util.async_ import get_scheduled_timer_handles

from . import setup_with_selected_platforms

ENTITY_ID = "light.connectedspa_ddeeff_light_zone_1"


async def _call(hass: HomeAssistant, service: str) -> None:
    await hass.services.async_call(
        LIGHT_DOMAIN, service, {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
    )


async def _tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta
) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def _state(hass: HomeAssistant) -> str:
    assert (state := hass.states.get(ENTITY_ID))
    return state.state


def _pending_state_timers(hass: HomeAssistant) -> list[TimerHandle]:
    return [
        handle
        for handle in get_scheduled_timer_handles(hass.loop)
        if not handle.cancelled()
        and any(
            isinstance(arg, HassJob)
            and getattr(arg.target, "__name__", None) == "_pending_is_on_expired"
            for arg in handle._args
        )
    ]


async def test_light_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hotspring: MagicMock,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test the light entity state."""
    await setup_with_selected_platforms(hass, mock_config_entry, [Platform.LIGHT])
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


async def test_turn_on_default(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_hotspring: MagicMock,
    device_fixture: Spa,
) -> None:
    """Test turning on light with default settings."""
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == "off"
    assert state.attributes.get(ATTR_BRIGHTNESS) is None

    def _set_light_brightness(zone: int, brightness: int) -> None:
        device_fixture.light_zones[1].intensity = brightness
        device_fixture.light_zones[1].is_on = brightness > 0

    mock_hotspring.set_light_brightness.side_effect = _set_light_brightness

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: ENTITY_ID},
        blocking=True,
    )

    mock_hotspring.set_light_brightness.assert_called_once_with(1, 5)
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == "on"
    assert state.attributes.get(ATTR_BRIGHTNESS) == 255


async def test_turn_on_with_brightness(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_hotspring: MagicMock,
    device_fixture: Spa,
) -> None:
    """Test turning on light with brightness."""

    def _set_light_brightness(zone: int, brightness: int) -> None:
        device_fixture.light_zones[1].intensity = brightness
        device_fixture.light_zones[1].is_on = brightness > 0

    mock_hotspring.set_light_brightness.side_effect = _set_light_brightness

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {
            ATTR_ENTITY_ID: ENTITY_ID,
            ATTR_BRIGHTNESS: 153,
        },
        blocking=True,
    )

    mock_hotspring.set_light_brightness.assert_called_once_with(1, 3)
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == "on"
    assert state.attributes.get(ATTR_BRIGHTNESS) == 153


async def test_turn_on_with_rgb_color_when_off(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_hotspring: MagicMock,
) -> None:
    """Test turning on light with rgb color when light is off."""
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {
            ATTR_ENTITY_ID: ENTITY_ID,
            ATTR_RGB_COLOR: (120, 200, 50),
        },
        blocking=True,
    )

    mock_hotspring.set_light_rgb.assert_called_once_with(1, 120, 200, 50)
    mock_hotspring.set_light_brightness.assert_called_once_with(1, 5)


async def test_turn_on_with_rgb_color_when_on(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hotspring: MagicMock,
    device_fixture: Spa,
) -> None:
    """Test setting rgb color when light is already on."""
    device_fixture.light_zones = {
        1: LightZone(
            zone_id=1,
            is_enabled=True,
            is_on=True,
            color=LightColor.BLUE,
            light_wheel=LightWheelMode.OFF,
            intensity=3,
            loop_speed=0,
        ),
    }
    await setup_with_selected_platforms(hass, mock_config_entry, [Platform.LIGHT])

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {
            ATTR_ENTITY_ID: ENTITY_ID,
            ATTR_RGB_COLOR: (120, 200, 50),
        },
        blocking=True,
    )

    mock_hotspring.set_light_rgb.assert_called_once_with(1, 120, 200, 50)
    mock_hotspring.set_light_brightness.assert_not_called()


async def test_turn_on_with_rgb_color_and_brightness(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_hotspring: MagicMock,
) -> None:
    """Test turning on light with rgb color and brightness."""
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {
            ATTR_ENTITY_ID: ENTITY_ID,
            ATTR_RGB_COLOR: (120, 200, 50),
            ATTR_BRIGHTNESS: 102,
        },
        blocking=True,
    )

    mock_hotspring.set_light_rgb.assert_called_once_with(1, 120, 200, 50)
    mock_hotspring.set_light_brightness.assert_called_once_with(1, 2)


async def test_rgb_color_active_custom(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hotspring: MagicMock,
    device_fixture: Spa,
) -> None:
    """Test rgb_color property returns custom RGB values when active."""
    device_fixture.light_zones = {
        1: LightZone(
            zone_id=1,
            is_enabled=True,
            is_on=True,
            color=LightColor.CUSTOM,
            light_wheel=LightWheelMode.OFF,
            intensity=3,
            loop_speed=0,
            c_red=120,
            c_green=200,
            c_blue=50,
            rgb_state="active",
        ),
    }
    await setup_with_selected_platforms(hass, mock_config_entry, [Platform.LIGHT])

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.attributes.get("rgb_color") == (120, 200, 50)


async def test_rgb_color_all_zero(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hotspring: MagicMock,
    device_fixture: Spa,
) -> None:
    """Test rgb_color property returns (0, 0, 0) when rgb_state is active."""
    device_fixture.light_zones = {
        1: LightZone(
            zone_id=1,
            is_enabled=True,
            is_on=True,
            color=LightColor.CUSTOM,
            light_wheel=LightWheelMode.OFF,
            intensity=3,
            loop_speed=0,
            c_red=0,
            c_green=0,
            c_blue=0,
            rgb_state="active",
        ),
    }
    await setup_with_selected_platforms(hass, mock_config_entry, [Platform.LIGHT])

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.attributes.get("rgb_color") == (0, 0, 0)


async def test_turn_off(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hotspring: MagicMock,
    device_fixture: Spa,
) -> None:
    """Test turning off light."""
    device_fixture.light_zones = {
        1: LightZone(
            zone_id=1,
            is_enabled=True,
            is_on=True,
            color=LightColor.BLUE,
            light_wheel=LightWheelMode.OFF,
            intensity=5,
            loop_speed=0,
        ),
    }
    await setup_with_selected_platforms(hass, mock_config_entry, [Platform.LIGHT])

    def _turn_off_light(zone: int) -> None:
        device_fixture.light_zones[1].intensity = 0
        device_fixture.light_zones[1].is_on = False

    mock_hotspring.turn_off_light.side_effect = _turn_off_light

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == "on"

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: ENTITY_ID},
        blocking=True,
    )

    mock_hotspring.turn_off_light.assert_called_once_with(1)
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == "off"


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
async def test_turn_on_error(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_hotspring: MagicMock,
    exception: type[Exception],
    match: str,
) -> None:
    """Test exception handling when turning on light."""
    mock_hotspring.set_light_brightness.side_effect = exception

    with pytest.raises(HomeAssistantError, match=match):
        await hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: ENTITY_ID},
            blocking=True,
        )


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
async def test_turn_off_error(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_hotspring: MagicMock,
    exception: type[Exception],
    match: str,
) -> None:
    """Test exception handling when turning off light."""
    mock_hotspring.turn_off_light.side_effect = exception

    with pytest.raises(HomeAssistantError, match=match):
        await hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: ENTITY_ID},
            blocking=True,
        )


async def test_disabled_zone_not_added(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hotspring: MagicMock,
    device_fixture: Spa,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test disabled light zones are not added to entity registry."""
    device_fixture.light_zones = {
        1: LightZone(
            zone_id=1,
            is_enabled=False,
            is_on=False,
            color=LightColor.UNKNOWN,
            light_wheel=LightWheelMode.OFF,
            intensity=0,
            loop_speed=0,
        ),
    }
    await setup_with_selected_platforms(hass, mock_config_entry, [Platform.LIGHT])

    assert not entity_registry.async_is_registered(ENTITY_ID)


async def test_pending_on_survives_stale_poll(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_hotspring: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test the requested state shows at once and outlives a stale poll."""
    states_in_flight: list[str] = []

    async def _set_light_brightness(zone: int, brightness: int) -> None:
        states_in_flight.append(_state(hass))

    mock_hotspring.set_light_brightness.side_effect = _set_light_brightness

    await _call(hass, SERVICE_TURN_ON)
    assert states_in_flight == ["on"]
    assert _state(hass) == "on"

    await _tick(hass, freezer, SCAN_INTERVAL)

    assert mock_hotspring.update.call_count == 2
    assert _state(hass) == "on"


async def test_pending_off_survives_stale_poll(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hotspring: MagicMock,
    device_fixture: Spa,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a requested off outlives a poll still reporting on."""
    device_fixture.light_zones[1].is_on = True
    device_fixture.light_zones[1].intensity = 5
    await setup_with_selected_platforms(hass, mock_config_entry, [Platform.LIGHT])

    await _call(hass, SERVICE_TURN_OFF)
    await _tick(hass, freezer, SCAN_INTERVAL)

    assert _state(hass) == "off"


async def test_pending_state_clears_when_reported(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_hotspring: MagicMock,
    device_fixture: Spa,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test the pending state gives way once the spa reports it."""
    await _call(hass, SERVICE_TURN_ON)

    device_fixture.light_zones[1].is_on = True
    await _tick(hass, freezer, SCAN_INTERVAL)
    assert _state(hass) == "on"
    assert not _pending_state_timers(hass)

    # A later change made at the spa itself now shows through.
    device_fixture.light_zones[1].is_on = False
    await _tick(hass, freezer, SCAN_INTERVAL)
    assert _state(hass) == "off"


async def test_pending_state_expires(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_hotspring: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test the reported state returns when the spa never confirms."""
    await _call(hass, SERVICE_TURN_ON)

    await _tick(hass, freezer, PENDING_STATE_TIMEOUT - timedelta(seconds=1))
    assert _state(hass) == "on"

    await _tick(hass, freezer, timedelta(seconds=1))
    assert _state(hass) == "off"
    assert not _pending_state_timers(hass)


@pytest.mark.parametrize(
    ("service", "method"),
    [
        (SERVICE_TURN_ON, "set_light_brightness"),
        (SERVICE_TURN_OFF, "turn_off_light"),
    ],
)
async def test_pending_state_cleared_on_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hotspring: MagicMock,
    device_fixture: Spa,
    service: str,
    method: str,
) -> None:
    """Test a failed command drops the pending state and its timer."""
    device_fixture.light_zones[1].is_on = service == SERVICE_TURN_OFF
    await setup_with_selected_platforms(hass, mock_config_entry, [Platform.LIGHT])
    reported = _state(hass)
    getattr(mock_hotspring, method).side_effect = HotSpringConnectionError

    with pytest.raises(HomeAssistantError):
        await _call(hass, service)

    assert _state(hass) == reported
    assert not _pending_state_timers(hass)


async def test_second_request_replaces_timer(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_hotspring: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a new request restarts the guard instead of inheriting the old one."""
    await _call(hass, SERVICE_TURN_ON)
    await _tick(hass, freezer, timedelta(seconds=30))
    await _call(hass, SERVICE_TURN_ON)
    assert len(_pending_state_timers(hass)) == 1

    # Past the first request's guard, the second request still shows.
    await _tick(hass, freezer, PENDING_STATE_TIMEOUT - timedelta(seconds=29))
    assert _state(hass) == "on"

    await _tick(hass, freezer, timedelta(seconds=30))
    assert _state(hass) == "off"


async def test_pending_state_timer_cancelled_on_unload(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_hotspring: MagicMock,
) -> None:
    """Test removing the entity cancels the guard timer."""
    await _call(hass, SERVICE_TURN_ON)
    assert _pending_state_timers(hass)

    assert await hass.config_entries.async_unload(init_integration.entry_id)

    assert not _pending_state_timers(hass)
