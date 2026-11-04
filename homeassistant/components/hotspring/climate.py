"""Support for the Hot Spring spa heater."""

from typing import Any, override

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import HEATING_MODE_TO_OPTION, OPTION_TO_HEATING_MODE
from .coordinator import HotSpringConfigEntry, HotSpringDataUpdateCoordinator
from .entity import HotSpringEntity
from .helpers import (
    SetpointRange,
    heating_mode_options,
    hotspring_exception_handler,
    setpoint_range,
)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HotSpringConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Hot Spring climate entity."""
    async_add_entities([HotSpringClimateEntity(entry.runtime_data)])


class HotSpringClimateEntity(HotSpringEntity, ClimateEntity):
    """Defines the Hot Spring spa heater."""

    # The spa has no heater-off mode to map to HVACMode.OFF.
    _attr_hvac_mode = HVACMode.HEAT
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    )
    _attr_name = None
    _attr_translation_key = "heater"

    def __init__(self, coordinator: HotSpringDataUpdateCoordinator) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator, "heater")

    @property
    def _range(self) -> SetpointRange:
        """Return the target temperature limits of the spa."""
        return setpoint_range(self.coordinator.data)

    @property
    @override
    def native_temperature_unit(self) -> str:
        """Return the unit the spa reports temperatures in."""
        return self._range.unit

    @property
    @override
    def min_temp(self) -> float:
        """Return the minimum target temperature."""
        return self._range.min_temp

    @property
    @override
    def max_temp(self) -> float:
        """Return the maximum target temperature."""
        return self._range.max_temp

    @property
    @override
    def target_temperature_step(self) -> float:
        """Return the target temperature step."""
        return self._range.step

    @property
    @override
    def native_current_temperature(self) -> float | None:
        """Return the water temperature."""
        return self.coordinator.data.heater.current_temperature

    @property
    @override
    def native_target_temperature(self) -> float | None:
        """Return the target water temperature."""
        return self.coordinator.data.heater.set_temperature

    @property
    @override
    def hvac_action(self) -> HVACAction:
        """Return whether the heater is running."""
        if self.coordinator.data.heater.is_on:
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    @override
    def preset_modes(self) -> list[str]:
        """Return the heating modes the spa supports."""
        return heating_mode_options(self.coordinator.data)

    @property
    @override
    def preset_mode(self) -> str | None:
        """Return the current heating mode."""
        return HEATING_MODE_TO_OPTION.get(self.coordinator.data.heater.heating_mode)

    @override
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Accept HEAT, the only mode, which is always active."""

    @hotspring_exception_handler
    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target water temperature."""
        step = self._range.step
        target = round(kwargs[ATTR_TEMPERATURE] / step) * step
        await self.coordinator.hotspring.set_temperature(target)
        self.coordinator.async_set_updated_data(self.coordinator.data)

    @hotspring_exception_handler
    @override
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the heating mode."""
        await self.coordinator.hotspring.set_heating_mode(
            OPTION_TO_HEATING_MODE[preset_mode]
        )
        self.coordinator.async_set_updated_data(self.coordinator.data)
