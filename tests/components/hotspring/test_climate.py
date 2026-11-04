"""Tests for the Hot Spring climate platform."""

from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from hotspring import (
    HeatingMode,
    HotSpringConnectionError,
    HotSpringError,
    Spa,
    TemperatureUnit,
)
import pytest
from pytest_homeassistant.common import (
    MockConfigEntry,
    async_fire_time_changed,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_HVAC_ACTION,
    ATTR_HVAC_MODE,
    ATTR_MAX_TEMP,
    ATTR_MIN_TEMP,
    ATTR_PRESET_MODE,
    ATTR_PRESET_MODES,
    ATTR_TARGET_TEMP_STEP,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACAction,
    HVACMode,
)
from homeassistant.components.hotspring.const import SCAN_INTERVAL
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    STATE_UNAVAILABLE,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_system import (
    METRIC_SYSTEM,
    US_CUSTOMARY_SYSTEM,
    UnitSystem,
)

from . import setup_with_selected_platforms

ENTITY_ID = "climate.connectedspa_ddeeff"


@pytest.mark.usefixtures("mock_hotspring")
async def test_climate_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    device_fixture: Spa,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test the climate entity state."""
    device_fixture.heater.heatpump_installed = True
    await setup_with_selected_platforms(hass, mock_config_entry, [Platform.CLIMATE])
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.parametrize(
    ("unit", "unit_system", "expected"),
    [
        pytest.param(
            TemperatureUnit.FAHRENHEIT,
            US_CUSTOMARY_SYSTEM,
            {
                ATTR_MIN_TEMP: 80.0,
                ATTR_MAX_TEMP: 104.0,
                ATTR_TARGET_TEMP_STEP: 1.0,
            },
            id="fahrenheit",
        ),
        pytest.param(
            TemperatureUnit.CELSIUS,
            METRIC_SYSTEM,
            {
                ATTR_MIN_TEMP: 26.0,
                ATTR_MAX_TEMP: 40.0,
                ATTR_TARGET_TEMP_STEP: 0.5,
            },
            id="celsius",
        ),
    ],
)
@pytest.mark.usefixtures("mock_hotspring")
async def test_climate_temperature_unit(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    device_fixture: Spa,
    unit: TemperatureUnit,
    unit_system: UnitSystem,
    expected: dict[str, float],
) -> None:
    """Test the limits and step follow the spa's configured unit."""
    hass.config.units = unit_system
    device_fixture.heater.temperature_unit = unit
    device_fixture.heater.set_temperature = 38.0
    device_fixture.heater.current_temperature = 37.0
    await setup_with_selected_platforms(hass, mock_config_entry, [Platform.CLIMATE])

    assert (state := hass.states.get(ENTITY_ID))
    assert {key: state.attributes[key] for key in expected} == expected
    assert state.attributes[ATTR_TEMPERATURE] == 38.0
    assert state.attributes[ATTR_CURRENT_TEMPERATURE] == 37.0


@pytest.mark.parametrize(
    ("is_on", "expected"),
    [
        pytest.param(True, HVACAction.HEATING, id="heating"),
        pytest.param(False, HVACAction.IDLE, id="idle"),
    ],
)
@pytest.mark.usefixtures("mock_hotspring")
async def test_climate_hvac_action(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    device_fixture: Spa,
    is_on: bool,
    expected: HVACAction,
) -> None:
    """Test the HVAC action follows the heater's running state."""
    device_fixture.heater.is_on = is_on
    await setup_with_selected_platforms(hass, mock_config_entry, [Platform.CLIMATE])

    assert (state := hass.states.get(ENTITY_ID))
    assert state.state == HVACMode.HEAT
    assert state.attributes[ATTR_HVAC_ACTION] == expected


@pytest.mark.parametrize(
    ("heatpump_installed", "expected"),
    [
        pytest.param(
            False,
            ["heat_saver", "heat_with_boost", "auto_saver", "auto_with_boost"],
            id="without_heatpump",
        ),
        pytest.param(
            True,
            ["heat_saver", "heat_with_boost", "auto_saver", "auto_with_boost", "chill"],
            id="with_heatpump",
        ),
    ],
)
@pytest.mark.usefixtures("mock_hotspring")
async def test_climate_preset_modes(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    device_fixture: Spa,
    heatpump_installed: bool,
    expected: list[str],
) -> None:
    """Test chill is only offered with a heat pump."""
    device_fixture.heater.heatpump_installed = heatpump_installed
    await setup_with_selected_platforms(hass, mock_config_entry, [Platform.CLIMATE])

    assert (state := hass.states.get(ENTITY_ID))
    assert state.attributes[ATTR_PRESET_MODES] == expected


@pytest.mark.usefixtures("mock_hotspring")
async def test_climate_unsupported_heating_mode(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    device_fixture: Spa,
) -> None:
    """Test a heating mode without a preset leaves the preset unset."""
    device_fixture.heater.heating_mode = HeatingMode.INVALID
    await setup_with_selected_platforms(hass, mock_config_entry, [Platform.CLIMATE])

    assert (state := hass.states.get(ENTITY_ID))
    assert state.attributes[ATTR_PRESET_MODE] is None


@pytest.mark.parametrize(
    ("unit", "unit_system", "requested", "expected"),
    [
        pytest.param(
            TemperatureUnit.FAHRENHEIT,
            US_CUSTOMARY_SYSTEM,
            100.4,
            100.0,
            id="fahrenheit",
        ),
        pytest.param(
            TemperatureUnit.CELSIUS,
            METRIC_SYSTEM,
            37.6,
            37.5,
            id="celsius_half_degree",
        ),
    ],
)
async def test_climate_set_temperature(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hotspring: MagicMock,
    device_fixture: Spa,
    unit: TemperatureUnit,
    unit_system: UnitSystem,
    requested: float,
    expected: float,
) -> None:
    """Test setting the target temperature rounds to the spa's step."""
    hass.config.units = unit_system
    device_fixture.heater.temperature_unit = unit

    def _set_temperature(value: float) -> None:
        device_fixture.heater.set_temperature = value

    mock_hotspring.set_temperature.side_effect = _set_temperature
    await setup_with_selected_platforms(hass, mock_config_entry, [Platform.CLIMATE])

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_TEMPERATURE: requested},
        blocking=True,
    )

    mock_hotspring.set_temperature.assert_called_once_with(expected)
    assert (state := hass.states.get(ENTITY_ID))
    assert state.attributes[ATTR_TEMPERATURE] == expected


@pytest.mark.parametrize(
    ("preset_mode", "expected"),
    [
        ("heat_saver", HeatingMode.HEAT_SAVER),
        ("heat_with_boost", HeatingMode.HEAT_WITH_BOOST),
        ("auto_saver", HeatingMode.AUTO_SAVER),
        ("auto_with_boost", HeatingMode.AUTO_WITH_BOOST),
        ("chill", HeatingMode.CHILL),
    ],
)
async def test_climate_set_preset_mode(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hotspring: MagicMock,
    device_fixture: Spa,
    preset_mode: str,
    expected: HeatingMode,
) -> None:
    """Test setting a preset sets the matching heating mode."""
    device_fixture.heater.heatpump_installed = True
    device_fixture.heater.heating_mode = HeatingMode.INVALID

    def _set_heating_mode(mode: HeatingMode) -> None:
        device_fixture.heater.heating_mode = mode

    mock_hotspring.set_heating_mode.side_effect = _set_heating_mode
    await setup_with_selected_platforms(hass, mock_config_entry, [Platform.CLIMATE])

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_PRESET_MODE: preset_mode},
        blocking=True,
    )

    mock_hotspring.set_heating_mode.assert_called_once_with(expected)
    assert (state := hass.states.get(ENTITY_ID))
    assert state.attributes[ATTR_PRESET_MODE] == preset_mode


async def test_climate_set_hvac_mode_heat(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hotspring: MagicMock,
) -> None:
    """Test setting HEAT, the only mode, is accepted without a command."""
    await setup_with_selected_platforms(hass, mock_config_entry, [Platform.CLIMATE])

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_HVAC_MODE: HVACMode.HEAT},
        blocking=True,
    )

    mock_hotspring.set_temperature.assert_not_called()
    mock_hotspring.set_heating_mode.assert_not_called()
    assert (state := hass.states.get(ENTITY_ID))
    assert state.state == HVACMode.HEAT


@pytest.mark.parametrize(
    ("service", "data", "method_name"),
    [
        pytest.param(
            SERVICE_SET_TEMPERATURE,
            {ATTR_TEMPERATURE: 100},
            "set_temperature",
            id="set_temperature",
        ),
        pytest.param(
            SERVICE_SET_PRESET_MODE,
            {ATTR_PRESET_MODE: "auto_saver"},
            "set_heating_mode",
            id="set_preset_mode",
        ),
    ],
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
async def test_climate_action_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hotspring: MagicMock,
    service: str,
    data: dict[str, object],
    method_name: str,
    exception: type[Exception],
    match: str,
) -> None:
    """Test library errors surface as translated errors."""
    hass.config.units = US_CUSTOMARY_SYSTEM
    await setup_with_selected_platforms(hass, mock_config_entry, [Platform.CLIMATE])
    getattr(mock_hotspring, method_name).side_effect = exception

    with pytest.raises(HomeAssistantError, match=match):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            service,
            {ATTR_ENTITY_ID: ENTITY_ID, **data},
            blocking=True,
        )


async def test_climate_unavailable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hotspring: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test the climate entity is unavailable while the spa can't be reached."""
    await setup_with_selected_platforms(hass, mock_config_entry, [Platform.CLIMATE])
    assert (state := hass.states.get(ENTITY_ID))
    assert state.state == HVACMode.HEAT

    mock_hotspring.update.side_effect = HotSpringConnectionError
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert (state := hass.states.get(ENTITY_ID))
    assert state.state == STATE_UNAVAILABLE

    mock_hotspring.update.side_effect = None
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert (state := hass.states.get(ENTITY_ID))
    assert state.state == HVACMode.HEAT
