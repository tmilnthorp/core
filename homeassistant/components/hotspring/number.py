"""Support for Hot Spring number entities."""

from typing import override

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import HotSpringConfigEntry, HotSpringDataUpdateCoordinator
from .deprecation import async_should_create_deprecated_entity
from .entity import HotSpringEntity
from .helpers import SetpointRange, hotspring_exception_handler, setpoint_range

PARALLEL_UPDATES = 1

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
    coordinator = entry.runtime_data
    # Superseded by the climate entity.
    if async_should_create_deprecated_entity(
        hass,
        config_entry_id=entry.entry_id,
        platform_domain=Platform.NUMBER,
        entity_unique_id=(
            f"{coordinator.data.info.mac_address}_{TARGET_TEMPERATURE_DESCRIPTION.key}"
        ),
        translation_key="deprecated_number_target_temperature",
    ):
        async_add_entities(
            [HotSpringNumberEntity(coordinator, TARGET_TEMPERATURE_DESCRIPTION)]
        )


class HotSpringNumberEntity(HotSpringEntity, NumberEntity):
    """Defines a Hot Spring number entity."""

    entity_description: NumberEntityDescription

    def __init__(
        self,
        coordinator: HotSpringDataUpdateCoordinator,
        description: NumberEntityDescription,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def _range(self) -> SetpointRange:
        """Return the target temperature limits of the spa."""
        return setpoint_range(self.coordinator.data)

    @property
    @override
    def native_unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        return self._range.unit

    @property
    @override
    def native_min_value(self) -> float:
        """Return the minimum value."""
        return self._range.min_temp

    @property
    @override
    def native_max_value(self) -> float:
        """Return the maximum value."""
        return self._range.max_temp

    @property
    @override
    def native_step(self) -> float:
        """Return the step value."""
        return self._range.step

    @property
    @override
    def native_value(self) -> float | None:
        """Return the current target temperature."""
        return self.coordinator.data.heater.set_temperature

    @hotspring_exception_handler
    @override
    async def async_set_native_value(self, value: float) -> None:
        """Set the target temperature."""
        target = round(value / self.native_step) * self.native_step
        await self.coordinator.hotspring.set_temperature(target)
        self.coordinator.async_set_updated_data(self.coordinator.data)
