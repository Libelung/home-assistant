"""Alexa capabilities."""
import logging

from homeassistant.const import (
    ATTR_SUPPORTED_FEATURES,
    ATTR_TEMPERATURE,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_ALARM_ARMED_AWAY,
    STATE_ALARM_ARMED_CUSTOM_BYPASS,
    STATE_ALARM_ARMED_HOME,
    STATE_ALARM_ARMED_NIGHT,
    STATE_CLOSED,
    STATE_LOCKED,
    STATE_OFF,
    STATE_ON,
    STATE_OPEN,
    STATE_PAUSED,
    STATE_PLAYING,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    STATE_UNLOCKED,
)
import homeassistant.components.climate.const as climate
import homeassistant.components.media_player.const as media_player
from homeassistant.components.alarm_control_panel import ATTR_CODE_FORMAT, FORMAT_NUMBER
from homeassistant.components import light, fan, cover
import homeassistant.util.color as color_util
import homeassistant.util.dt as dt_util

from .const import (
    Catalog,
    API_TEMP_UNITS,
    API_THERMOSTAT_MODES,
    API_THERMOSTAT_PRESETS,
    DATE_FORMAT,
    PERCENTAGE_FAN_MAP,
    RANGE_FAN_MAP,
    Inputs,
)
from .errors import UnsupportedProperty

_LOGGER = logging.getLogger(__name__)


class AlexaCapability:
    """Base class for Alexa capability interfaces.

    The Smart Home Skills API defines a number of "capability interfaces",
    roughly analogous to domains in Home Assistant. The supported interfaces
    describe what actions can be performed on a particular device.

    https://developer.amazon.com/docs/device-apis/message-guide.html
    """

    def __init__(self, entity, instance=None):
        """Initialize an Alexa capability."""
        self.entity = entity
        self.instance = instance

    def name(self):
        """Return the Alexa API name of this interface."""
        raise NotImplementedError

    @staticmethod
    def properties_supported():
        """Return what properties this entity supports."""
        return []

    @staticmethod
    def properties_proactively_reported():
        """Return True if properties asynchronously reported."""
        return False

    @staticmethod
    def properties_retrievable():
        """Return True if properties can be retrieved."""
        return False

    @staticmethod
    def properties_non_controllable():
        """Return True if non controllable."""
        return None

    @staticmethod
    def get_property(name):
        """Read and return a property.

        Return value should be a dict, or raise UnsupportedProperty.

        Properties can also have a timeOfSample and uncertaintyInMilliseconds,
        but returning those metadata is not yet implemented.
        """
        raise UnsupportedProperty(name)

    @staticmethod
    def supports_deactivation():
        """Applicable only to scenes."""
        return None

    @staticmethod
    def capability_proactively_reported():
        """Return True if the capability is proactively reported.

        Set properties_proactively_reported() for proactively reported properties.
        Applicable to DoorbellEventSource.
        """
        return None

    @staticmethod
    def capability_resources():
        """Applicable to ToggleController, RangeController, and ModeController interfaces."""
        return []

    @staticmethod
    def configuration():
        """Return the Configuration object."""
        return []

    @staticmethod
    def inputs():
        """Applicable only to media players."""
        return []

    @staticmethod
    def supported_operations():
        """Return the supportedOperations object."""
        return []

    def serialize_discovery(self):
        """Serialize according to the Discovery API."""
        result = {"type": "AlexaInterface", "interface": self.name(), "version": "3"}

        properties_supported = self.properties_supported()
        if properties_supported:
            result["properties"] = {
                "supported": self.properties_supported(),
                "proactivelyReported": self.properties_proactively_reported(),
                "retrievable": self.properties_retrievable(),
            }

        # pylint: disable=assignment-from-none
        proactively_reported = self.capability_proactively_reported()
        if proactively_reported is not None:
            result["proactivelyReported"] = proactively_reported

        # pylint: disable=assignment-from-none
        non_controllable = self.properties_non_controllable()
        if non_controllable is not None:
            result["properties"]["nonControllable"] = non_controllable

        # pylint: disable=assignment-from-none
        supports_deactivation = self.supports_deactivation()
        if supports_deactivation is not None:
            result["supportsDeactivation"] = supports_deactivation

        capability_resources = self.serialize_capability_resources()
        if capability_resources:
            result["capabilityResources"] = capability_resources

        configuration = self.configuration()
        if configuration:
            result["configuration"] = configuration

        # pylint: disable=assignment-from-none
        instance = self.instance
        if instance is not None:
            result["instance"] = instance

        supported_operations = self.supported_operations()
        if supported_operations:
            result["supportedOperations"] = supported_operations

        inputs = self.inputs()
        if inputs:
            result["inputs"] = inputs

        return result

    def serialize_properties(self):
        """Return properties serialized for an API response."""
        for prop in self.properties_supported():
            prop_name = prop["name"]
            # pylint: disable=assignment-from-no-return
            prop_value = self.get_property(prop_name)
            if prop_value is not None:
                result = {
                    "name": prop_name,
                    "namespace": self.name(),
                    "value": prop_value,
                    "timeOfSample": dt_util.utcnow().strftime(DATE_FORMAT),
                    "uncertaintyInMilliseconds": 0,
                }
                instance = self.instance
                if instance is not None:
                    result["instance"] = instance

                yield result

    def serialize_capability_resources(self):
        """Return capabilityResources friendlyNames serialized for an API response."""
        resources = self.capability_resources()
        if resources:
            return {"friendlyNames": self.serialize_friendly_names(resources)}

        return None

    @staticmethod
    def serialize_friendly_names(resources):
        """Return capabilityResources, ModeResources, or presetResources friendlyNames serialized for an API response."""
        friendly_names = []
        for resource in resources:
            if resource["type"] == Catalog.LABEL_ASSET:
                friendly_names.append(
                    {
                        "@type": Catalog.LABEL_ASSET,
                        "value": {"assetId": resource["value"]},
                    }
                )
            else:
                friendly_names.append(
                    {
                        "@type": Catalog.LABEL_TEXT,
                        "value": {"text": resource["value"], "locale": "en-US"},
                    }
                )

        return friendly_names


class Alexa(AlexaCapability):
    """Implements Alexa Interface.

    Although endpoints implement this interface implicitly,
    The API suggests you should explicitly include this interface.

    https://developer.amazon.com/docs/device-apis/alexa-interface.html
    """

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa"


class AlexaEndpointHealth(AlexaCapability):
    """Implements Alexa.EndpointHealth.

    https://developer.amazon.com/docs/smarthome/state-reporting-for-a-smart-home-skill.html#report-state-when-alexa-requests-it
    """

    def __init__(self, hass, entity):
        """Initialize the entity."""
        super().__init__(entity)
        self.hass = hass

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.EndpointHealth"

    def properties_supported(self):
        """Return what properties this entity supports."""
        return [{"name": "connectivity"}]

    def properties_proactively_reported(self):
        """Return True if properties asynchronously reported."""
        return False

    def properties_retrievable(self):
        """Return True if properties can be retrieved."""
        return True

    def get_property(self, name):
        """Read and return a property."""
        if name != "connectivity":
            raise UnsupportedProperty(name)

        if self.entity.state == STATE_UNAVAILABLE:
            return {"value": "UNREACHABLE"}
        return {"value": "OK"}


class AlexaPowerController(AlexaCapability):
    """Implements Alexa.PowerController.

    https://developer.amazon.com/docs/device-apis/alexa-powercontroller.html
    """

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.PowerController"

    def properties_supported(self):
        """Return what properties this entity supports."""
        return [{"name": "powerState"}]

    def properties_proactively_reported(self):
        """Return True if properties asynchronously reported."""
        return True

    def properties_retrievable(self):
        """Return True if properties can be retrieved."""
        return True

    def get_property(self, name):
        """Read and return a property."""
        if name != "powerState":
            raise UnsupportedProperty(name)

        if self.entity.domain == climate.DOMAIN:
            is_on = self.entity.state != climate.HVAC_MODE_OFF

        else:
            is_on = self.entity.state != STATE_OFF

        return "ON" if is_on else "OFF"


class AlexaLockController(AlexaCapability):
    """Implements Alexa.LockController.

    https://developer.amazon.com/docs/device-apis/alexa-lockcontroller.html
    """

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.LockController"

    def properties_supported(self):
        """Return what properties this entity supports."""
        return [{"name": "lockState"}]

    def properties_retrievable(self):
        """Return True if properties can be retrieved."""
        return True

    def properties_proactively_reported(self):
        """Return True if properties asynchronously reported."""
        return True

    def get_property(self, name):
        """Read and return a property."""
        if name != "lockState":
            raise UnsupportedProperty(name)

        if self.entity.state == STATE_LOCKED:
            return "LOCKED"
        if self.entity.state == STATE_UNLOCKED:
            return "UNLOCKED"
        return "JAMMED"


class AlexaSceneController(AlexaCapability):
    """Implements Alexa.SceneController.

    https://developer.amazon.com/docs/device-apis/alexa-scenecontroller.html
    """

    def __init__(self, entity, supports_deactivation):
        """Initialize the entity."""
        super().__init__(entity)
        self.supports_deactivation = lambda: supports_deactivation

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.SceneController"


class AlexaBrightnessController(AlexaCapability):
    """Implements Alexa.BrightnessController.

    https://developer.amazon.com/docs/device-apis/alexa-brightnesscontroller.html
    """

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.BrightnessController"

    def properties_supported(self):
        """Return what properties this entity supports."""
        return [{"name": "brightness"}]

    def properties_proactively_reported(self):
        """Return True if properties asynchronously reported."""
        return True

    def properties_retrievable(self):
        """Return True if properties can be retrieved."""
        return True

    def get_property(self, name):
        """Read and return a property."""
        if name != "brightness":
            raise UnsupportedProperty(name)
        if "brightness" in self.entity.attributes:
            return round(self.entity.attributes["brightness"] / 255.0 * 100)
        return 0


class AlexaColorController(AlexaCapability):
    """Implements Alexa.ColorController.

    https://developer.amazon.com/docs/device-apis/alexa-colorcontroller.html
    """

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.ColorController"

    def properties_supported(self):
        """Return what properties this entity supports."""
        return [{"name": "color"}]

    def properties_retrievable(self):
        """Return True if properties can be retrieved."""
        return True

    def get_property(self, name):
        """Read and return a property."""
        if name != "color":
            raise UnsupportedProperty(name)

        hue, saturation = self.entity.attributes.get(light.ATTR_HS_COLOR, (0, 0))

        return {
            "hue": hue,
            "saturation": saturation / 100.0,
            "brightness": self.entity.attributes.get(light.ATTR_BRIGHTNESS, 0) / 255.0,
        }


class AlexaColorTemperatureController(AlexaCapability):
    """Implements Alexa.ColorTemperatureController.

    https://developer.amazon.com/docs/device-apis/alexa-colortemperaturecontroller.html
    """

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.ColorTemperatureController"

    def properties_supported(self):
        """Return what properties this entity supports."""
        return [{"name": "colorTemperatureInKelvin"}]

    def properties_retrievable(self):
        """Return True if properties can be retrieved."""
        return True

    def get_property(self, name):
        """Read and return a property."""
        if name != "colorTemperatureInKelvin":
            raise UnsupportedProperty(name)
        if "color_temp" in self.entity.attributes:
            return color_util.color_temperature_mired_to_kelvin(
                self.entity.attributes["color_temp"]
            )
        return None


class AlexaPercentageController(AlexaCapability):
    """Implements Alexa.PercentageController.

    https://developer.amazon.com/docs/device-apis/alexa-percentagecontroller.html
    """

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.PercentageController"

    def properties_supported(self):
        """Return what properties this entity supports."""
        return [{"name": "percentage"}]

    def properties_retrievable(self):
        """Return True if properties can be retrieved."""
        return True

    def get_property(self, name):
        """Read and return a property."""
        if name != "percentage":
            raise UnsupportedProperty(name)

        if self.entity.domain == fan.DOMAIN:
            speed = self.entity.attributes.get(fan.ATTR_SPEED)

            return PERCENTAGE_FAN_MAP.get(speed, 0)

        if self.entity.domain == cover.DOMAIN:
            return self.entity.attributes.get(cover.ATTR_CURRENT_POSITION, 0)

        return 0


class AlexaSpeaker(AlexaCapability):
    """Implements Alexa.Speaker.

    https://developer.amazon.com/docs/device-apis/alexa-speaker.html
    """

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.Speaker"


class AlexaStepSpeaker(AlexaCapability):
    """Implements Alexa.StepSpeaker.

    https://developer.amazon.com/docs/device-apis/alexa-stepspeaker.html
    """

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.StepSpeaker"


class AlexaPlaybackController(AlexaCapability):
    """Implements Alexa.PlaybackController.

    https://developer.amazon.com/docs/device-apis/alexa-playbackcontroller.html
    """

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.PlaybackController"

    def supported_operations(self):
        """Return the supportedOperations object.

        Supported Operations: FastForward, Next, Pause, Play, Previous, Rewind, StartOver, Stop
        """
        supported_features = self.entity.attributes.get(ATTR_SUPPORTED_FEATURES, 0)

        operations = {
            media_player.SUPPORT_NEXT_TRACK: "Next",
            media_player.SUPPORT_PAUSE: "Pause",
            media_player.SUPPORT_PLAY: "Play",
            media_player.SUPPORT_PREVIOUS_TRACK: "Previous",
            media_player.SUPPORT_STOP: "Stop",
        }

        supported_operations = []
        for operation in operations:
            if operation & supported_features:
                supported_operations.append(operations[operation])

        return supported_operations


class AlexaInputController(AlexaCapability):
    """Implements Alexa.InputController.

    https://developer.amazon.com/docs/device-apis/alexa-inputcontroller.html
    """

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.InputController"

    def inputs(self):
        """Return the list of valid supported inputs."""
        source_list = self.entity.attributes.get(
            media_player.ATTR_INPUT_SOURCE_LIST, []
        )
        input_list = []
        for source in source_list:
            formatted_source = (
                source.lower().replace("-", "").replace("_", "").replace(" ", "")
            )
            if formatted_source in Inputs.VALID_SOURCE_NAME_MAP.keys():
                input_list.append(
                    {"name": Inputs.VALID_SOURCE_NAME_MAP[formatted_source]}
                )

        return input_list


class AlexaTemperatureSensor(AlexaCapability):
    """Implements Alexa.TemperatureSensor.

    https://developer.amazon.com/docs/device-apis/alexa-temperaturesensor.html
    """

    def __init__(self, hass, entity):
        """Initialize the entity."""
        super().__init__(entity)
        self.hass = hass

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.TemperatureSensor"

    def properties_supported(self):
        """Return what properties this entity supports."""
        return [{"name": "temperature"}]

    def properties_proactively_reported(self):
        """Return True if properties asynchronously reported."""
        return True

    def properties_retrievable(self):
        """Return True if properties can be retrieved."""
        return True

    def get_property(self, name):
        """Read and return a property."""
        if name != "temperature":
            raise UnsupportedProperty(name)

        unit = self.entity.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        temp = self.entity.state
        if self.entity.domain == climate.DOMAIN:
            unit = self.hass.config.units.temperature_unit
            temp = self.entity.attributes.get(climate.ATTR_CURRENT_TEMPERATURE)

        if temp in (STATE_UNAVAILABLE, STATE_UNKNOWN, None):
            return None

        try:
            temp = float(temp)
        except ValueError:
            _LOGGER.warning("Invalid temp value %s for %s", temp, self.entity.entity_id)
            return None

        return {"value": temp, "scale": API_TEMP_UNITS[unit]}


class AlexaContactSensor(AlexaCapability):
    """Implements Alexa.ContactSensor.

    The Alexa.ContactSensor interface describes the properties and events used
    to report the state of an endpoint that detects contact between two
    surfaces. For example, a contact sensor can report whether a door or window
    is open.

    https://developer.amazon.com/docs/device-apis/alexa-contactsensor.html
    """

    def __init__(self, hass, entity):
        """Initialize the entity."""
        super().__init__(entity)
        self.hass = hass

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.ContactSensor"

    def properties_supported(self):
        """Return what properties this entity supports."""
        return [{"name": "detectionState"}]

    def properties_proactively_reported(self):
        """Return True if properties asynchronously reported."""
        return True

    def properties_retrievable(self):
        """Return True if properties can be retrieved."""
        return True

    def get_property(self, name):
        """Read and return a property."""
        if name != "detectionState":
            raise UnsupportedProperty(name)

        if self.entity.state == STATE_ON:
            return "DETECTED"
        return "NOT_DETECTED"


class AlexaMotionSensor(AlexaCapability):
    """Implements Alexa.MotionSensor.

    https://developer.amazon.com/docs/device-apis/alexa-motionsensor.html
    """

    def __init__(self, hass, entity):
        """Initialize the entity."""
        super().__init__(entity)
        self.hass = hass

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.MotionSensor"

    def properties_supported(self):
        """Return what properties this entity supports."""
        return [{"name": "detectionState"}]

    def properties_proactively_reported(self):
        """Return True if properties asynchronously reported."""
        return True

    def properties_retrievable(self):
        """Return True if properties can be retrieved."""
        return True

    def get_property(self, name):
        """Read and return a property."""
        if name != "detectionState":
            raise UnsupportedProperty(name)

        if self.entity.state == STATE_ON:
            return "DETECTED"
        return "NOT_DETECTED"


class AlexaThermostatController(AlexaCapability):
    """Implements Alexa.ThermostatController.

    https://developer.amazon.com/docs/device-apis/alexa-thermostatcontroller.html
    """

    def __init__(self, hass, entity):
        """Initialize the entity."""
        super().__init__(entity)
        self.hass = hass

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.ThermostatController"

    def properties_supported(self):
        """Return what properties this entity supports."""
        properties = [{"name": "thermostatMode"}]
        supported = self.entity.attributes.get(ATTR_SUPPORTED_FEATURES, 0)
        if supported & climate.SUPPORT_TARGET_TEMPERATURE:
            properties.append({"name": "targetSetpoint"})
        if supported & climate.SUPPORT_TARGET_TEMPERATURE_RANGE:
            properties.append({"name": "lowerSetpoint"})
            properties.append({"name": "upperSetpoint"})
        return properties

    def properties_proactively_reported(self):
        """Return True if properties asynchronously reported."""
        return True

    def properties_retrievable(self):
        """Return True if properties can be retrieved."""
        return True

    def get_property(self, name):
        """Read and return a property."""
        if self.entity.state == STATE_UNAVAILABLE:
            return None

        if name == "thermostatMode":
            preset = self.entity.attributes.get(climate.ATTR_PRESET_MODE)

            if preset in API_THERMOSTAT_PRESETS:
                mode = API_THERMOSTAT_PRESETS[preset]
            else:
                mode = API_THERMOSTAT_MODES.get(self.entity.state)
                if mode is None:
                    _LOGGER.error(
                        "%s (%s) has unsupported state value '%s'",
                        self.entity.entity_id,
                        type(self.entity),
                        self.entity.state,
                    )
                    raise UnsupportedProperty(name)
            return mode

        unit = self.hass.config.units.temperature_unit
        if name == "targetSetpoint":
            temp = self.entity.attributes.get(ATTR_TEMPERATURE)
        elif name == "lowerSetpoint":
            temp = self.entity.attributes.get(climate.ATTR_TARGET_TEMP_LOW)
        elif name == "upperSetpoint":
            temp = self.entity.attributes.get(climate.ATTR_TARGET_TEMP_HIGH)
        else:
            raise UnsupportedProperty(name)

        if temp is None:
            return None

        try:
            temp = float(temp)
        except ValueError:
            _LOGGER.warning(
                "Invalid temp value %s for %s in %s", temp, name, self.entity.entity_id
            )
            return None

        return {"value": temp, "scale": API_TEMP_UNITS[unit]}

    def configuration(self):
        """Return configuration object.

        Translates climate HVAC_MODES and PRESETS to supported Alexa ThermostatMode Values.
        ThermostatMode Value must be AUTO, COOL, HEAT, ECO, OFF, or CUSTOM.
        """
        supported_modes = []
        hvac_modes = self.entity.attributes.get(climate.ATTR_HVAC_MODES)
        for mode in hvac_modes:
            thermostat_mode = API_THERMOSTAT_MODES.get(mode)
            if thermostat_mode:
                supported_modes.append(thermostat_mode)

        preset_modes = self.entity.attributes.get(climate.ATTR_PRESET_MODES)
        if preset_modes:
            for mode in preset_modes:
                thermostat_mode = API_THERMOSTAT_PRESETS.get(mode)
                if thermostat_mode:
                    supported_modes.append(thermostat_mode)

        # Return False for supportsScheduling until supported with event listener in handler.
        configuration = {"supportsScheduling": False}

        if supported_modes:
            configuration["supportedModes"] = supported_modes

        return configuration


class AlexaPowerLevelController(AlexaCapability):
    """Implements Alexa.PowerLevelController.

    https://developer.amazon.com/docs/device-apis/alexa-powerlevelcontroller.html
    """

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.PowerLevelController"

    def properties_supported(self):
        """Return what properties this entity supports."""
        return [{"name": "powerLevel"}]

    def properties_proactively_reported(self):
        """Return True if properties asynchronously reported."""
        return True

    def properties_retrievable(self):
        """Return True if properties can be retrieved."""
        return True

    def get_property(self, name):
        """Read and return a property."""
        if name != "powerLevel":
            raise UnsupportedProperty(name)

        if self.entity.domain == fan.DOMAIN:
            speed = self.entity.attributes.get(fan.ATTR_SPEED)

            return PERCENTAGE_FAN_MAP.get(speed, None)

        return None


class AlexaSecurityPanelController(AlexaCapability):
    """Implements Alexa.SecurityPanelController.

    https://developer.amazon.com/docs/device-apis/alexa-securitypanelcontroller.html
    """

    def __init__(self, hass, entity):
        """Initialize the entity."""
        super().__init__(entity)
        self.hass = hass

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.SecurityPanelController"

    def properties_supported(self):
        """Return what properties this entity supports."""
        return [{"name": "armState"}]

    def properties_proactively_reported(self):
        """Return True if properties asynchronously reported."""
        return True

    def properties_retrievable(self):
        """Return True if properties can be retrieved."""
        return True

    def get_property(self, name):
        """Read and return a property."""
        if name != "armState":
            raise UnsupportedProperty(name)

        arm_state = self.entity.state
        if arm_state == STATE_ALARM_ARMED_HOME:
            return "ARMED_STAY"
        if arm_state == STATE_ALARM_ARMED_AWAY:
            return "ARMED_AWAY"
        if arm_state == STATE_ALARM_ARMED_NIGHT:
            return "ARMED_NIGHT"
        if arm_state == STATE_ALARM_ARMED_CUSTOM_BYPASS:
            return "ARMED_STAY"
        return "DISARMED"

    def configuration(self):
        """Return configuration object with supported authorization types."""
        code_format = self.entity.attributes.get(ATTR_CODE_FORMAT)

        if code_format == FORMAT_NUMBER:
            return {"supportedAuthorizationTypes": [{"type": "FOUR_DIGIT_PIN"}]}
        return None


class AlexaModeController(AlexaCapability):
    """Implements Alexa.ModeController.

    https://developer.amazon.com/docs/device-apis/alexa-modecontroller.html
    """

    def __init__(self, entity, instance, non_controllable=False):
        """Initialize the entity."""
        super().__init__(entity, instance)
        self.properties_non_controllable = lambda: non_controllable

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.ModeController"

    def properties_supported(self):
        """Return what properties this entity supports."""
        return [{"name": "mode"}]

    def properties_proactively_reported(self):
        """Return True if properties asynchronously reported."""
        return True

    def properties_retrievable(self):
        """Return True if properties can be retrieved."""

    def get_property(self, name):
        """Read and return a property."""
        if name != "mode":
            raise UnsupportedProperty(name)

        if self.instance == f"{fan.DOMAIN}.{fan.ATTR_DIRECTION}":
            return self.entity.attributes.get(fan.ATTR_DIRECTION)

        if self.instance == f"{cover.DOMAIN}.{cover.ATTR_POSITION}":
            return self.entity.attributes.get(cover.ATTR_POSITION)

        return None

    def configuration(self):
        """Return configuration with modeResources."""
        return self.serialize_mode_resources()

    def capability_resources(self):
        """Return capabilityResources object."""
        capability_resources = []

        if self.instance == f"{fan.DOMAIN}.{fan.ATTR_DIRECTION}":
            capability_resources = [
                {"type": Catalog.LABEL_ASSET, "value": Catalog.SETTING_DIRECTION}
            ]

        if self.instance == f"{cover.DOMAIN}.{cover.ATTR_POSITION}":
            capability_resources = [
                {"type": Catalog.LABEL_ASSET, "value": Catalog.SETTING_MODE},
                {"type": Catalog.LABEL_ASSET, "value": Catalog.SETTING_PRESET},
            ]

        return capability_resources

    def mode_resources(self):
        """Return modeResources object."""
        mode_resources = None
        if self.instance == f"{fan.DOMAIN}.{fan.ATTR_DIRECTION}":
            mode_resources = {
                "ordered": False,
                "resources": [
                    {
                        "value": f"{fan.ATTR_DIRECTION}.{fan.DIRECTION_FORWARD}",
                        "friendly_names": [
                            {"type": Catalog.LABEL_TEXT, "value": fan.DIRECTION_FORWARD}
                        ],
                    },
                    {
                        "value": f"{fan.ATTR_DIRECTION}.{fan.DIRECTION_REVERSE}",
                        "friendly_names": [
                            {"type": Catalog.LABEL_TEXT, "value": fan.DIRECTION_REVERSE}
                        ],
                    },
                ],
            }

        if self.instance == f"{cover.DOMAIN}.{cover.ATTR_POSITION}":
            mode_resources = {
                "ordered": False,
                "resources": [
                    {
                        "value": f"{cover.ATTR_POSITION}.{STATE_OPEN}",
                        "friendly_names": [
                            {"type": Catalog.LABEL_TEXT, "value": "open"},
                            {"type": Catalog.LABEL_TEXT, "value": "opened"},
                            {"type": Catalog.LABEL_TEXT, "value": "raise"},
                            {"type": Catalog.LABEL_TEXT, "value": "raised"},
                        ],
                    },
                    {
                        "value": f"{cover.ATTR_POSITION}.{STATE_CLOSED}",
                        "friendly_names": [
                            {"type": Catalog.LABEL_TEXT, "value": "close"},
                            {"type": Catalog.LABEL_TEXT, "value": "closed"},
                            {"type": Catalog.LABEL_TEXT, "value": "shut"},
                            {"type": Catalog.LABEL_TEXT, "value": "lower"},
                            {"type": Catalog.LABEL_TEXT, "value": "lowered"},
                        ],
                    },
                ],
            }

        return mode_resources

    def serialize_mode_resources(self):
        """Return ModeResources, friendlyNames serialized for an API response."""
        mode_resources = []
        resources = self.mode_resources()
        ordered = resources["ordered"]
        for resource in resources["resources"]:
            mode_value = resource["value"]
            friendly_names = resource["friendly_names"]
            result = {
                "value": mode_value,
                "modeResources": {
                    "friendlyNames": self.serialize_friendly_names(friendly_names)
                },
            }
            mode_resources.append(result)

        return {"ordered": ordered, "supportedModes": mode_resources}


class AlexaRangeController(AlexaCapability):
    """Implements Alexa.RangeController.

    https://developer.amazon.com/docs/device-apis/alexa-rangecontroller.html
    """

    def __init__(self, entity, instance, non_controllable=False):
        """Initialize the entity."""
        super().__init__(entity, instance)
        self.properties_non_controllable = lambda: non_controllable

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.RangeController"

    def properties_supported(self):
        """Return what properties this entity supports."""
        return [{"name": "rangeValue"}]

    def properties_proactively_reported(self):
        """Return True if properties asynchronously reported."""
        return True

    def properties_retrievable(self):
        """Return True if properties can be retrieved."""
        return True

    def get_property(self, name):
        """Read and return a property."""
        if name != "rangeValue":
            raise UnsupportedProperty(name)

        if self.instance == f"{fan.DOMAIN}.{fan.ATTR_SPEED}":
            speed = self.entity.attributes.get(fan.ATTR_SPEED)
            return RANGE_FAN_MAP.get(speed, 0)

        return None

    def configuration(self):
        """Return configuration with presetResources."""
        return self.serialize_preset_resources()

    def capability_resources(self):
        """Return capabilityResources object."""
        capability_resources = []

        if self.instance == f"{fan.DOMAIN}.{fan.ATTR_SPEED}":
            return [{"type": Catalog.LABEL_ASSET, "value": Catalog.SETTING_FANSPEED}]

        return capability_resources

    def preset_resources(self):
        """Return presetResources object."""
        preset_resources = []

        if self.instance == f"{fan.DOMAIN}.{fan.ATTR_SPEED}":
            preset_resources = {
                "minimumValue": 1,
                "maximumValue": 3,
                "precision": 1,
                "presets": [
                    {
                        "rangeValue": 1,
                        "names": [
                            {
                                "type": Catalog.LABEL_ASSET,
                                "value": Catalog.VALUE_MINIMUM,
                            },
                            {"type": Catalog.LABEL_ASSET, "value": Catalog.VALUE_LOW},
                        ],
                    },
                    {
                        "rangeValue": 2,
                        "names": [
                            {"type": Catalog.LABEL_ASSET, "value": Catalog.VALUE_MEDIUM}
                        ],
                    },
                    {
                        "rangeValue": 3,
                        "names": [
                            {
                                "type": Catalog.LABEL_ASSET,
                                "value": Catalog.VALUE_MAXIMUM,
                            },
                            {"type": Catalog.LABEL_ASSET, "value": Catalog.VALUE_HIGH},
                        ],
                    },
                ],
            }

        return preset_resources

    def serialize_preset_resources(self):
        """Return PresetResources, friendlyNames serialized for an API response."""
        preset_resources = []
        resources = self.preset_resources()
        for preset in resources["presets"]:
            preset_resources.append(
                {
                    "rangeValue": preset["rangeValue"],
                    "presetResources": {
                        "friendlyNames": self.serialize_friendly_names(preset["names"])
                    },
                }
            )

        return {
            "supportedRange": {
                "minimumValue": resources["minimumValue"],
                "maximumValue": resources["maximumValue"],
                "precision": resources["precision"],
            },
            "presets": preset_resources,
        }


class AlexaToggleController(AlexaCapability):
    """Implements Alexa.ToggleController.

    https://developer.amazon.com/docs/device-apis/alexa-togglecontroller.html
    """

    def __init__(self, entity, instance, non_controllable=False):
        """Initialize the entity."""
        super().__init__(entity, instance)
        self.properties_non_controllable = lambda: non_controllable

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.ToggleController"

    def properties_supported(self):
        """Return what properties this entity supports."""
        return [{"name": "toggleState"}]

    def properties_proactively_reported(self):
        """Return True if properties asynchronously reported."""
        return True

    def properties_retrievable(self):
        """Return True if properties can be retrieved."""
        return True

    def get_property(self, name):
        """Read and return a property."""
        if name != "toggleState":
            raise UnsupportedProperty(name)

        if self.instance == f"{fan.DOMAIN}.{fan.ATTR_OSCILLATING}":
            is_on = bool(self.entity.attributes.get(fan.ATTR_OSCILLATING))
            return "ON" if is_on else "OFF"

        return None

    def capability_resources(self):
        """Return capabilityResources object."""
        capability_resources = []

        if self.instance == f"{fan.DOMAIN}.{fan.ATTR_OSCILLATING}":
            capability_resources = [
                {"type": Catalog.LABEL_ASSET, "value": Catalog.SETTING_OSCILLATE},
                {"type": Catalog.LABEL_TEXT, "value": "Rotate"},
                {"type": Catalog.LABEL_TEXT, "value": "Rotation"},
            ]

        return capability_resources


class AlexaChannelController(AlexaCapability):
    """Implements Alexa.ChannelController.

    https://developer.amazon.com/docs/device-apis/alexa-channelcontroller.html
    """

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.ChannelController"


class AlexaDoorbellEventSource(AlexaCapability):
    """Implements Alexa.DoorbellEventSource.

    https://developer.amazon.com/docs/device-apis/alexa-doorbelleventsource.html
    """

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.DoorbellEventSource"

    def capability_proactively_reported(self):
        """Return True for proactively reported capability."""
        return True


class AlexaPlaybackStateReporter(AlexaCapability):
    """Implements Alexa.PlaybackStateReporter.

    https://developer.amazon.com/docs/device-apis/alexa-playbackstatereporter.html
    """

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.PlaybackStateReporter"

    def properties_supported(self):
        """Return what properties this entity supports."""
        return [{"name": "playbackState"}]

    def properties_proactively_reported(self):
        """Return True if properties asynchronously reported."""
        return True

    def properties_retrievable(self):
        """Return True if properties can be retrieved."""
        return True

    def get_property(self, name):
        """Read and return a property."""
        if name != "playbackState":
            raise UnsupportedProperty(name)

        playback_state = self.entity.state
        if playback_state == STATE_PLAYING:
            return {"state": "PLAYING"}
        if playback_state == STATE_PAUSED:
            return {"state": "PAUSED"}

        return {"state": "STOPPED"}


class AlexaSeekController(AlexaCapability):
    """Implements Alexa.SeekController.

    https://developer.amazon.com/docs/device-apis/alexa-seekcontroller.html
    """

    def name(self):
        """Return the Alexa API name of this interface."""
        return "Alexa.SeekController"
