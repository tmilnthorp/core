"""Support for Hot Spring light entities."""

from datetime import datetime, timedelta
from typing import Any, cast, override

from hotspring import LightColor, LightZone, Spa

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.util.color import brightness_to_value, value_to_brightness

from .const import SCAN_INTERVAL
from .coordinator import HotSpringConfigEntry, HotSpringDataUpdateCoordinator
from .entity import HotSpringEntity
from .helpers import hotspring_exception_handler

PARALLEL_UPDATES = 1

# A LoRa round trip to the spa plus one poll, with margin.
PENDING_STATE_TIMEOUT = SCAN_INTERVAL + timedelta(seconds=30)

LIGHT_COLOR_TO_RGB: dict[LightColor, tuple[int, int, int]] = {
    LightColor.RED: (255, 0, 0),
    LightColor.GREEN: (0, 255, 0),
    LightColor.BLUE: (0, 0, 255),
    LightColor.YELLOW: (255, 255, 0),
    LightColor.WHITE: (255, 255, 255),
    LightColor.AQUA: (0, 255, 255),
    LightColor.MAGENTA: (255, 0, 255),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HotSpringConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hot Spring light entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        HotSpringLightEntity(coordinator, zone.zone_id)
        for zone in coordinator.data.light_zones.values()
        if zone.is_enabled
    )


class HotSpringLightEntity(HotSpringEntity, LightEntity):
    """Defines a Hot Spring light entity."""

    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_translation_key = "light_zone"
    _pending_is_on: bool | None = None
    _pending_is_on_timer: CALLBACK_TYPE | None = None

    def __init__(
        self,
        coordinator: HotSpringDataUpdateCoordinator,
        zone_id: int,
    ) -> None:
        """Initialize the light entity."""
        super().__init__(coordinator, f"light_zone_{zone_id}")
        self._zone_id = zone_id
        self._attr_translation_placeholders = {"zone": str(zone_id)}

    @property
    def _zone(self) -> LightZone:
        """Return the light zone data."""
        return self.coordinator.data.light_zones[self._zone_id]

    @property
    @override
    def is_on(self) -> bool:
        """Return true if the light is on."""
        if self._pending_is_on is not None:
            return self._pending_is_on
        return self._zone.is_on

    @property
    @override
    def brightness(self) -> int | None:
        """Return the brightness of this light between 1..255."""
        return value_to_brightness((1, 5), self._zone.intensity)

    @property
    @override
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return the rgb color value."""
        zone = self._zone
        if zone.rgb_state == "active":
            return (zone.c_red, zone.c_green, zone.c_blue)
        return LIGHT_COLOR_TO_RGB.get(zone.color)

    @hotspring_exception_handler
    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        was_on = self._zone.is_on
        self._set_pending_is_on(True)
        try:
            if (rgb_color := kwargs.get(ATTR_RGB_COLOR)) is not None:
                await self.coordinator.hotspring.set_light_rgb(
                    self._zone_id, *rgb_color
                )

            if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
                intensity = max(1, round(brightness_to_value((1, 5), brightness)))
                await self.coordinator.hotspring.set_light_brightness(
                    self._zone_id, intensity
                )
            elif not was_on:
                await self.coordinator.hotspring.set_light_brightness(self._zone_id, 5)
        except BaseException:
            self._clear_pending_is_on()
            self.async_write_ha_state()
            raise

        self.coordinator.async_set_updated_data(
            cast(Spa, self.coordinator.hotspring.spa)
        )

    @hotspring_exception_handler
    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        self._set_pending_is_on(False)
        try:
            await self.coordinator.hotspring.turn_off_light(self._zone_id)
        except BaseException:
            self._clear_pending_is_on()
            self.async_write_ha_state()
            raise
        self.coordinator.async_set_updated_data(
            cast(Spa, self.coordinator.hotspring.spa)
        )

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        """Drop the pending state once the spa reports it."""
        if self._pending_is_on == self._zone.is_on:
            self._clear_pending_is_on()
        super()._handle_coordinator_update()

    @override
    async def async_will_remove_from_hass(self) -> None:
        """Cancel the pending state timer."""
        self._clear_pending_is_on()
        await super().async_will_remove_from_hass()

    @callback
    def _set_pending_is_on(self, is_on: bool) -> None:
        """Show the requested state until the spa reports it over LoRa."""
        self._clear_pending_is_on()
        self._pending_is_on = is_on
        self._pending_is_on_timer = async_call_later(
            self.hass, PENDING_STATE_TIMEOUT, self._pending_is_on_expired
        )
        self.async_write_ha_state()

    @callback
    def _pending_is_on_expired(self, _now: datetime) -> None:
        """Fall back to the reported state when the spa never confirms."""
        self._pending_is_on_timer = None
        self._clear_pending_is_on()
        self.async_write_ha_state()

    @callback
    def _clear_pending_is_on(self) -> None:
        """Forget the pending state and cancel its timer."""
        if self._pending_is_on_timer is not None:
            self._pending_is_on_timer()
            self._pending_is_on_timer = None
        self._pending_is_on = None
