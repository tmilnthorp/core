"""Support for Hot Spring number entities."""

from datetime import datetime, timedelta
from typing import override

from hotspring import TemperatureUnit

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import SCAN_INTERVAL
from .coordinator import HotSpringConfigEntry, HotSpringDataUpdateCoordinator
from .entity import HotSpringEntity
from .helpers import hotspring_exception_handler

PARALLEL_UPDATES = 1

MIN_TEMP_FAHRENHEIT = 80.0
MAX_TEMP_FAHRENHEIT = 104.0
STEP_FAHRENHEIT = 1.0

MIN_TEMP_CELSIUS = 26.0
MAX_TEMP_CELSIUS = 40.0
STEP_CELSIUS = 0.5

# A LoRa round trip to the spa plus one poll, with margin.
PENDING_TARGET_TIMEOUT = SCAN_INTERVAL + timedelta(seconds=30)

TARGET_TEMPERATURE_DESCRIPTION = NumberEntityDescription(
    key="target_temperature",
    translation_key="target_temperature",
    device_class=NumberDeviceClass.TEMPERATURE,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HotSpringConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hot Spring number entities."""
    async_add_entities(
        [HotSpringNumberEntity(entry.runtime_data, TARGET_TEMPERATURE_DESCRIPTION)]
    )


class HotSpringNumberEntity(HotSpringEntity, NumberEntity):
    """Defines a Hot Spring number entity."""

    entity_description: NumberEntityDescription
    _pending_target: float | None = None
    _pending_target_timer: CALLBACK_TYPE | None = None

    def __init__(
        self,
        coordinator: HotSpringDataUpdateCoordinator,
        description: NumberEntityDescription,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def _is_celsius(self) -> bool:
        """Return True if the spa is configured in Celsius."""
        return self.coordinator.data.heater.temperature_unit is TemperatureUnit.CELSIUS

    @property
    @override
    def native_unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        if self._is_celsius:
            return UnitOfTemperature.CELSIUS
        return UnitOfTemperature.FAHRENHEIT

    @property
    @override
    def native_min_value(self) -> float:
        """Return the minimum value."""
        if self._is_celsius:
            return MIN_TEMP_CELSIUS
        return MIN_TEMP_FAHRENHEIT

    @property
    @override
    def native_max_value(self) -> float:
        """Return the maximum value."""
        if self._is_celsius:
            return MAX_TEMP_CELSIUS
        return MAX_TEMP_FAHRENHEIT

    @property
    @override
    def native_step(self) -> float:
        """Return the step value."""
        if self._is_celsius:
            return STEP_CELSIUS
        return STEP_FAHRENHEIT

    @property
    @override
    def native_value(self) -> float | None:
        """Return the current target temperature."""
        if self._pending_target is not None:
            return self._pending_target
        return self.coordinator.data.heater.set_temperature

    @hotspring_exception_handler
    @override
    async def async_set_native_value(self, value: float) -> None:
        """Set the target temperature."""
        target = round(value / self.native_step) * self.native_step
        # The HNA can acknowledge the command before the spa applies it over
        # LoRa, so keep showing the target until a poll reports it.
        self._clear_pending_target()
        self._pending_target = target
        self._pending_target_timer = async_call_later(
            self.hass, PENDING_TARGET_TIMEOUT, self._pending_target_expired
        )
        self.async_write_ha_state()
        try:
            await self.coordinator.hotspring.set_temperature(target)
        except BaseException:
            self._clear_pending_target()
            self.async_write_ha_state()
            raise
        self.coordinator.async_set_updated_data(self.coordinator.data)

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        """Drop the pending target once the spa reports it."""
        if self._pending_target == self.coordinator.data.heater.set_temperature:
            self._clear_pending_target()
        super()._handle_coordinator_update()

    @override
    async def async_will_remove_from_hass(self) -> None:
        """Cancel the pending target timer."""
        self._clear_pending_target()
        await super().async_will_remove_from_hass()

    @callback
    def _pending_target_expired(self, _now: datetime) -> None:
        """Fall back to the reported target when the spa never confirms."""
        self._pending_target_timer = None
        self._clear_pending_target()
        self.async_write_ha_state()

    @callback
    def _clear_pending_target(self) -> None:
        """Forget the pending target and cancel its timer."""
        if self._pending_target_timer is not None:
            self._pending_target_timer()
            self._pending_target_timer = None
        self._pending_target = None
