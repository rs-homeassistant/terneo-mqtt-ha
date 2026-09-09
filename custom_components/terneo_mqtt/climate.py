"""Terneo MQTT Climate Platform for Home Assistant."""
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

CONF_DEVICE_ID = "device_id"

PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Optional(CONF_NAME): cv.string,
    }
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up Terneo thermostat via MQTT."""
    device_id = config[CONF_DEVICE_ID]
    name = config.get(CONF_NAME, f"Terneo {device_id}")

    async_add_entities([TerneoMqttClimate(hass, name, device_id)])


class TerneoMqttClimate(ClimateEntity):
    """Representation of Terneo thermostat over native MQTT topics."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_TENTHS
    _attr_min_temp = 5.0
    _attr_max_temp = 45.0
    _attr_target_temperature_step = 0.5
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )

    def __init__(self, hass, name: str, device_id: str):
        """Initialize entity."""
        self.hass = hass
        self._attr_name = name
        self._device_id = device_id
        self._attr_unique_id = f"terneo_mqtt_{device_id.replace(' ', '_').lower()}"

        # Топіки згідно з реальними даними пристрою
        self._base_topic = f"house/{device_id}"
        self._topic_floor_temp = f"{self._base_topic}/get/floorTemp"
        self._topic_set_temp = f"{self._base_topic}/get/setTemp"
        self._topic_power_off = f"{self._base_topic}/get/powerOff"

        self._topic_send_temp = f"{self._base_topic}/set/setTemp"
        self._topic_send_power = f"{self._base_topic}/set/powerOff"

        self._attr_current_temperature = None
        self._attr_target_temperature = None
        self._attr_hvac_mode = HVACMode.HEAT
        self._attr_hvac_action = HVACAction.IDLE
        self._attr_available = False

    async def async_added_to_hass(self):
        """Subscribe to MQTT topics."""
        async def floor_temp_received(msg):
            try:
                self._attr_current_temperature = float(msg.payload)
                self._attr_available = True
                self._update_action()
                self.async_write_ha_state()
            except ValueError:
                pass

        async def set_temp_received(msg):
            try:
                self._attr_target_temperature = float(msg.payload)
                self._attr_available = True
                self._update_action()
                self.async_write_ha_state()
            except ValueError:
                pass

        async def power_off_received(msg):
            try:
                is_off = str(msg.payload).strip() == "1"
                self._attr_hvac_mode = HVACMode.OFF if is_off else HVACMode.HEAT
                self._attr_available = True
                self._update_action()
                self.async_write_ha_state()
            except ValueError:
                pass

        await mqtt.async_subscribe(self.hass, self._topic_floor_temp, floor_temp_received, 0)
        await mqtt.async_subscribe(self.hass, self._topic_set_temp, set_temp_received, 0)
        await mqtt.async_subscribe(self.hass, self._topic_power_off, power_off_received, 0)

    def _update_action(self):
        """Determine heating or idle state."""
        if self._attr_hvac_mode == HVACMode.OFF:
            self._attr_hvac_action = HVACAction.OFF
        elif (
            self._attr_current_temperature is not None
            and self._attr_target_temperature is not None
        ):
            if self._attr_current_temperature < self._attr_target_temperature:
                self._attr_hvac_action = HVACAction.HEATING
            else:
                self._attr_hvac_action = HVACAction.IDLE

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        target_temp = kwargs.get("temperature")
        if target_temp is None:
            return

        # Відправка температури напряму в градусах (наприклад, 23.5)
        await mqtt.async_publish(self.hass, self._topic_send_temp, f"{target_temp:.1f}")
        self._attr_target_temperature = target_temp
        self._update_action()
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode):
        """Set HVAC mode (turn on/off)."""
        if hvac_mode == HVACMode.OFF:
            await mqtt.async_publish(self.hass, self._topic_send_power, "1")
            self._attr_hvac_mode = HVACMode.OFF
        else:
            await mqtt.async_publish(self.hass, self._topic_send_power, "0")
            self._attr_hvac_mode = HVACMode.HEAT

        self._update_action()
        self.async_write_ha_state()
