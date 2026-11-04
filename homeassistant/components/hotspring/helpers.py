"""Helpers for Hot Spring."""

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Concatenate

from hotspring import HotSpringConnectionError, HotSpringError, Spa, TemperatureUnit

from homeassistant.const import UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DOMAIN,
    HEATING_MODE_AUTO_SAVER,
    HEATING_MODE_AUTO_WITH_BOOST,
    HEATING_MODE_CHILL,
    HEATING_MODE_HEAT_SAVER,
    HEATING_MODE_HEAT_WITH_BOOST,
)
from .entity import HotSpringEntity


@dataclass(frozen=True, kw_only=True)
class SetpointRange:
    """Target temperature limits of the spa, in its configured unit."""

    unit: UnitOfTemperature
    min_temp: float
    max_temp: float
    step: float


SETPOINT_RANGE_FAHRENHEIT = SetpointRange(
    unit=UnitOfTemperature.FAHRENHEIT, min_temp=80.0, max_temp=104.0, step=1.0
)
SETPOINT_RANGE_CELSIUS = SetpointRange(
    unit=UnitOfTemperature.CELSIUS, min_temp=26.0, max_temp=40.0, step=0.5
)


def setpoint_range(spa: Spa) -> SetpointRange:
    """Return the target temperature limits for the spa's configured unit."""
    if spa.heater.temperature_unit is TemperatureUnit.CELSIUS:
        return SETPOINT_RANGE_CELSIUS
    return SETPOINT_RANGE_FAHRENHEIT


def heating_mode_options(spa: Spa) -> list[str]:
    """Return the heating modes the spa supports."""
    options = [
        HEATING_MODE_HEAT_SAVER,
        HEATING_MODE_HEAT_WITH_BOOST,
        HEATING_MODE_AUTO_SAVER,
        HEATING_MODE_AUTO_WITH_BOOST,
    ]
    if spa.heater.heatpump_installed:
        options.append(HEATING_MODE_CHILL)
    return options


def hotspring_exception_handler[_HotSpringEntityT: HotSpringEntity, **_P](
    func: Callable[Concatenate[_HotSpringEntityT, _P], Coroutine[Any, Any, Any]],
) -> Callable[Concatenate[_HotSpringEntityT, _P], Coroutine[Any, Any, None]]:
    """Decorate Hot Spring calls to handle Hot Spring exceptions.

    A decorator that wraps the passed in function, catches Hot Spring errors,
    and raises a translated HomeAssistantError.
    """

    async def handler(
        self: _HotSpringEntityT, *args: _P.args, **kwargs: _P.kwargs
    ) -> None:
        try:
            await func(self, *args, **kwargs)
        except HotSpringConnectionError as error:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
            ) from error
        except HotSpringError as error:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="invalid_response",
            ) from error

    return handler
