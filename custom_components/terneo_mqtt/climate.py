"""Terneo MQTT Climate Platform."""
import json
import logging
import voluptuous as vol

from homeassistant.components import mqtt
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    CONF_NAME,
    PRECISION_TENTHS,
    UnitOfTemperature,
)
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

CONF_SERIAL = "serial"

PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_SERIAL): cv.string,
        vol.Optional(CONF_NAME): cv.string,
    }
)

OFFSET = 160.0
DIVIDER = 10.0


def terneo_to_temp(raw_val) -> float:
    """Convert raw Terneo value to Celsius."""
    try:
        return (float(raw_val) - OFFSET) / DIVIDER
    except (ValueError, TypeError):
        return None


def temp_to_terneo(celsius: float) -> str:
    """Convert Celsius to raw Terneo integer string."""
    return str(int(round((celsius * DIVIDER) + OFFSET)))


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up Terneo thermostat via MQTT."""
    serial = config[CONF_SERIAL]
    name = config.get(CONF_NAME, f"Terneo {serial[-6:]}")

    async_add_entities([TerneoMqttClimate(hass, name, serial)])


class TerneoMqttClimate(ClimateEntity):
    """Representation of Terneo thermostat over MQTT."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_TENTHS
    _attr_min_temp = 5.0
    _attr_max_temp = 45.0
    _attr_target_temperature_step = 1.0
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )

    def __init__(self, hass, name: str, serial: str):
        """Initialize entity."""
        self.hass = hass
        self._attr_name = name
        self._serial = serial
        self._attr_unique_id = f"terneo_mqtt_{serial}"
        
        # Топіки протоколу Terneo MQTT
        self._topic_tele = f"terneo/{serial}/tele"
        self._topic_cmd = f"terneo/{serial}/cmd"
        
        self._attr_current_temperature = None
        self._attr_target_temperature = None
        self._attr_hvac_mode = HVACMode.HEAT
        self._attr_hvac_action = HVACAction.IDLE
        self._attr_available = False

    async def async_added_to_hass(self):
        """Subscribe to MQTT telemetry."""
        await mqtt.async_subscribe(
            self.hass, self._topic_tele, self._message_received, 0
        )
        # Запит телеметрії при старті
        await mqtt.async_publish(self.hass, self._topic_cmd, json.dumps({"cmd": 4}))

    def _message_received(self, msg):
        """Handle incoming telemetry message."""
        try:
            payload = json.loads(msg.payload)
            self._attr_available = True

            # t.1 = поточна температура датчика
            if "t.1" in payload:
                self._current_temp_raw = payload["t.1"]
                self._attr_current_temperature = terneo_to_temp(self._current_temp_raw)

            # t.5 = цільова температура
            if "t.5" in payload:
                self._attr_target_temperature = terneo_to_temp(payload["t.5"])

            # f.0 = статус реле нагріву (0 - idle, 1 - heating)
            if "f.0" in payload:
                is_heating = str(payload["f.0"]) == "1"
                self._attr_hvac_action = HVACAction.HEATING if is_heating else HVACAction.IDLE

            # m.5 = стан живлення пристрою (0 - ON, 1 - OFF)
            if "m.5" in payload:
                is_off = str(payload["m.5"]) == "1"
                self._attr_hvac_mode = HVACMode.OFF if is_off else HVACMode.HEAT

            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("Failed to parse Terneo MQTT message: %s", err)

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        target_temp = kwargs.get("temperature")
        if target_temp is None:
            return

        raw_val = temp_to_terneo(target_temp)
        payload = {"cmd": 1, "t.5": raw_val}

        await mqtt.async_publish(self.hass, self._topic_cmd, json.dumps(payload))
        self._attr_target_temperature = target_temp
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode):
        """Enable or disable thermostat."""
        if hvac_mode == HVACMode.OFF:
            payload = {"cmd": 1, "m.5": "1"}
        else:
            payload = {"cmd": 1, "m.5": "0"}

        await mqtt.async_publish(self.hass, self._topic_cmd, json.dumps(payload))
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()
