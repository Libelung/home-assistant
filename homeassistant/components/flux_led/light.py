"""Support for Flux lights."""
import logging
import socket
import random

from flux_led import BulbScanner, WifiLedBulb
import voluptuous as vol

from homeassistant.const import CONF_DEVICES, CONF_NAME, CONF_PROTOCOL, ATTR_MODE
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_HS_COLOR,
    ATTR_EFFECT,
    ATTR_WHITE_VALUE,
    ATTR_COLOR_TEMP,
    EFFECT_COLORLOOP,
    EFFECT_RANDOM,
    SUPPORT_BRIGHTNESS,
    SUPPORT_EFFECT,
    SUPPORT_COLOR,
    SUPPORT_WHITE_VALUE,
    SUPPORT_COLOR_TEMP,
    Light,
    PLATFORM_SCHEMA,
)
import homeassistant.helpers.config_validation as cv
import homeassistant.util.color as color_util

_LOGGER = logging.getLogger(__name__)

CONF_AUTOMATIC_ADD = "automatic_add"
CONF_CUSTOM_EFFECT = "custom_effect"
CONF_CUSTOM_EFFECTS = "custom_effects"
CONF_COLORS = "colors"
CONF_SPEED_PCT = "speed_pct"
CONF_TRANSITION = "transition"

DOMAIN = "flux_led"

SUPPORT_FLUX_LED = SUPPORT_BRIGHTNESS | SUPPORT_EFFECT | SUPPORT_COLOR

MODE_RGB = "rgb"
MODE_RGBW = "rgbw"
MODE_RGBCW = "rgbcw"
MODE_RGBWW = "rgbww"

# This mode enables white value to be controlled by brightness.
# RGB value is ignored when this mode is specified.
MODE_WHITE = "w"

# Constant color temp values for 2 flux_led special modes
# Warm-white and Cool-white modes
COLOR_TEMP_WARM_VS_COLD_WHITE_CUT_OFF = 285

# List of supported effects which aren't already declared in LIGHT
EFFECT_RED_FADE = "red_fade"
EFFECT_GREEN_FADE = "green_fade"
EFFECT_BLUE_FADE = "blue_fade"
EFFECT_YELLOW_FADE = "yellow_fade"
EFFECT_CYAN_FADE = "cyan_fade"
EFFECT_PURPLE_FADE = "purple_fade"
EFFECT_WHITE_FADE = "white_fade"
EFFECT_RED_GREEN_CROSS_FADE = "rg_cross_fade"
EFFECT_RED_BLUE_CROSS_FADE = "rb_cross_fade"
EFFECT_GREEN_BLUE_CROSS_FADE = "gb_cross_fade"
EFFECT_COLORSTROBE = "colorstrobe"
EFFECT_RED_STROBE = "red_strobe"
EFFECT_GREEN_STROBE = "green_strobe"
EFFECT_BLUE_STROBE = "blue_strobe"
EFFECT_YELLOW_STROBE = "yellow_strobe"
EFFECT_CYAN_STROBE = "cyan_strobe"
EFFECT_PURPLE_STROBE = "purple_strobe"
EFFECT_WHITE_STROBE = "white_strobe"
EFFECT_COLORJUMP = "colorjump"
EFFECT_CUSTOM = "custom"

EFFECT_MAP = {
    EFFECT_COLORLOOP: 0x25,
    EFFECT_RED_FADE: 0x26,
    EFFECT_GREEN_FADE: 0x27,
    EFFECT_BLUE_FADE: 0x28,
    EFFECT_YELLOW_FADE: 0x29,
    EFFECT_CYAN_FADE: 0x2A,
    EFFECT_PURPLE_FADE: 0x2B,
    EFFECT_WHITE_FADE: 0x2C,
    EFFECT_RED_GREEN_CROSS_FADE: 0x2D,
    EFFECT_RED_BLUE_CROSS_FADE: 0x2E,
    EFFECT_GREEN_BLUE_CROSS_FADE: 0x2F,
    EFFECT_COLORSTROBE: 0x30,
    EFFECT_RED_STROBE: 0x31,
    EFFECT_GREEN_STROBE: 0x32,
    EFFECT_BLUE_STROBE: 0x33,
    EFFECT_YELLOW_STROBE: 0x34,
    EFFECT_CYAN_STROBE: 0x35,
    EFFECT_PURPLE_STROBE: 0x36,
    EFFECT_WHITE_STROBE: 0x37,
    EFFECT_COLORJUMP: 0x38,
}
EFFECT_CUSTOM_CODE = 0x60

TRANSITION_GRADUAL = "gradual"
TRANSITION_JUMP = "jump"
TRANSITION_STROBE = "strobe"

FLUX_EFFECT_LIST = sorted(list(EFFECT_MAP)) + [EFFECT_RANDOM]

CUSTOM_EFFECT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_COLORS): vol.All(
            cv.ensure_list,
            vol.Length(min=1, max=16),
            [
                vol.All(
                    vol.ExactSequence((cv.byte, cv.byte, cv.byte)), vol.Coerce(tuple)
                )
            ],
        ),
        vol.Optional(CONF_SPEED_PCT, default=50): vol.All(
            vol.Range(min=0, max=100), vol.Coerce(int)
        ),
        vol.Optional(CONF_TRANSITION, default=TRANSITION_GRADUAL): vol.All(
            cv.string, vol.In([TRANSITION_GRADUAL, TRANSITION_JUMP, TRANSITION_STROBE])
        ),
    }
)

DEVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME): cv.string,
        vol.Optional(ATTR_MODE, default=MODE_RGBW): vol.All(
            cv.string, vol.In([MODE_RGBW, MODE_RGBWW, MODE_RGBCW, MODE_RGB, MODE_WHITE])
        ),
        vol.Optional(CONF_PROTOCOL): vol.All(cv.string, vol.In(["ledenet"])),
        vol.Optional(CONF_CUSTOM_EFFECT): CUSTOM_EFFECT_SCHEMA,
        vol.Optional(CONF_CUSTOM_EFFECTS): {cv.string: CUSTOM_EFFECT_SCHEMA},
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_DEVICES, default={}): {cv.string: DEVICE_SCHEMA},
        vol.Optional(CONF_AUTOMATIC_ADD, default=False): cv.boolean,
    }
)


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the Flux lights."""
    lights = []
    light_ips = []

    for ipaddr, device_config in config.get(CONF_DEVICES, {}).items():
        device = {}
        device["name"] = device_config[CONF_NAME]
        device["ipaddr"] = ipaddr
        device[CONF_PROTOCOL] = device_config.get(CONF_PROTOCOL)
        device[ATTR_MODE] = device_config[ATTR_MODE]
        device[CONF_CUSTOM_EFFECT] = device_config.get(CONF_CUSTOM_EFFECT)
        device[CONF_CUSTOM_EFFECTS] = device_config.get(CONF_CUSTOM_EFFECTS)
        light = FluxLight(device)
        lights.append(light)
        light_ips.append(ipaddr)

    if not config.get(CONF_AUTOMATIC_ADD, False):
        add_entities(lights, True)
        return

    # Find the bulbs on the LAN
    scanner = BulbScanner()
    scanner.scan(timeout=10)
    for device in scanner.getBulbInfo():
        ipaddr = device["ipaddr"]
        if ipaddr in light_ips:
            continue
        device["name"] = "{} {}".format(device["id"], ipaddr)
        device[ATTR_MODE] = None
        device[CONF_PROTOCOL] = None
        device[CONF_CUSTOM_EFFECT] = None
        device[CONF_CUSTOM_EFFECTS] = None
        light = FluxLight(device)
        lights.append(light)

    add_entities(lights, True)


class FluxLight(Light):
    """Representation of a Flux light."""

    def __init__(self, device):
        """Initialize the light."""
        self._name = device["name"]
        self._ipaddr = device["ipaddr"]
        self._protocol = device[CONF_PROTOCOL]
        self._mode = device[ATTR_MODE]
        self._custom_effect = device[CONF_CUSTOM_EFFECT]
        self._custom_effects = device[CONF_CUSTOM_EFFECTS]
        self._selected_custom_effect = None
        self._bulb = None
        self._error_reported = False

    def _connect(self):
        """Connect to Flux light."""

        self._bulb = WifiLedBulb(self._ipaddr, timeout=5)
        if self._protocol:
            self._bulb.setProtocol(self._protocol)

        # After bulb object is created the status is updated. We can
        # now set the correct mode if it was not explicitly defined.
        if not self._mode:
            if self._bulb.rgbwcapable:
                self._mode = MODE_RGBW
            else:
                self._mode = MODE_RGB

    def _disconnect(self):
        """Disconnect from Flux light."""
        self._bulb = None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._bulb is not None

    @property
    def name(self):
        """Return the name of the device if any."""
        return self._name

    @property
    def is_on(self):
        """Return true if device is on."""
        return self._bulb.isOn()

    @property
    def brightness(self):
        """Return the brightness of this light between 0..255."""
        if self._mode == MODE_WHITE:
            return self.white_value

        # RBGCW mode returns 0 in brightness if white LEDs are in use (since brightness is for RBG mode only)
        if self._mode == MODE_RGBCW:
            rgbww = self.temperature_cw
            if rgbww[0] or rgbww[1]:
                return 0

        # RGBWW mode returns 0 brightness if in WW mode (since warm white and RGB are handled separately and cannot be on at same time)
        if self._mode == MODE_RGBWW and self._bulb.mode == "ww":
            return 0

        return self._bulb.brightness

    @property
    def hs_color(self):
        """Return the color property."""
        return color_util.color_RGB_to_hs(*self._bulb.getRgb())

    @property
    def supported_features(self):
        """Flag supported features."""
        if self._mode == MODE_RGBW:
            return SUPPORT_FLUX_LED | SUPPORT_WHITE_VALUE | SUPPORT_COLOR_TEMP

        if self._mode == MODE_RGBCW:
            return SUPPORT_FLUX_LED | SUPPORT_WHITE_VALUE | SUPPORT_COLOR_TEMP

        if self._mode == MODE_RGBWW:
            return SUPPORT_FLUX_LED | SUPPORT_WHITE_VALUE

        if self._mode == MODE_WHITE:
            return SUPPORT_BRIGHTNESS

        return SUPPORT_FLUX_LED

    @property
    def temperature_cw(self):
        rgbww = self._bulb.getRgbww()
        return [rgbww[4], rgbww[3]]

    @property
    def temperature_ww(self):
        rgbww = self._bulb.getRgbww()
        return rgbww[3]

    @property
    def white_value(self):
        """Return the white value of this light between 0..255."""
        if self._mode == MODE_RGBCW:
            white_temp = self.temperature_cw
            return white_temp[0] if white_temp[0] > white_temp[1] else white_temp[1]
        elif self._mode == MODE_RGBWW:
            return self.temperature_ww

        return self._bulb.getRgbw()[3]

    @property
    def effect_list(self):
        """Return the list of supported effects."""
        if self._custom_effects is not None:
            return FLUX_EFFECT_LIST + [EFFECT_CUSTOM] + [custom_effect for custom_effect in self._custom_effects]

        return FLUX_EFFECT_LIST

    @property
    def effect(self):
        """Return the current effect."""
        current_mode = self._bulb.raw_state[3]

        if current_mode == EFFECT_CUSTOM_CODE:
            if self._selected_custom_effect is not None:
                return self._selected_custom_effect
            return EFFECT_CUSTOM

        for effect, code in EFFECT_MAP.items():
            if current_mode == code:
                return effect

        return None

    def turn_on(self, **kwargs):
        """Turn the specified or all lights on."""
        if not self.is_on:
            self._bulb.turnOn()

        hs_color = kwargs.get(ATTR_HS_COLOR)

        if hs_color:
            rgb = color_util.color_hs_to_RGB(*hs_color)
        else:
            rgb = None

        brightness = kwargs.get(ATTR_BRIGHTNESS)
        effect = kwargs.get(ATTR_EFFECT)
        white = kwargs.get(ATTR_WHITE_VALUE)
        color_temp = kwargs.get(ATTR_COLOR_TEMP)

        # Show warning if effect set with rgb, brightness, or white level
        if effect and (brightness or white or rgb):
            _LOGGER.warning(
                "RGB, brightness and white level are ignored when"
                " an effect is specified for a flux bulb"
            )

        # Random color effect
        if effect == EFFECT_RANDOM:
            self._bulb.setRgb(
                random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)
            )
            return
        if effect:
            if effect == CONF_CUSTOM_EFFECT and self._custom_effect is not None:
                self._selected_custom_effect = None
                self._bulb.setCustomPattern(
                    self._custom_effect[CONF_COLORS],
                    self._custom_effect[CONF_SPEED_PCT],
                    self._custom_effect[CONF_TRANSITION],
                )
                return
            for custom_effect in self._custom_effects:
                if custom_effect == effect:
                    self._selected_custom_effect = custom_effect
                    self._bulb.setCustomPattern(
                        self._custom_effects[custom_effect][CONF_COLORS],
                        self._custom_effects[custom_effect][CONF_SPEED_PCT],
                        self._custom_effects[custom_effect][CONF_TRANSITION],
                    )
                    return
        # Reset selected effect
        self._selected_custom_effect = None

        # Effect selection
        if effect in EFFECT_MAP:
            self._bulb.setPresetPattern(EFFECT_MAP[effect], 50)
            return

        # handle special modes
        if color_temp is not None:
            if white is None:
                white = self.white_value if self.white_value > 0 else 255
            if self._mode == MODE_RGBCW:
                # 153 - 500 color temp in mired

                # map mired range from light input to kelvin range for bulb
                miredMin = 500
                miredMax = 153
                kelvinMin = 2700
                kelvinMax = 6500

                # map mired to kelvin specifically for the setWhiteTemperature since it wants 2700~6500 kelvin and 
                # we have 153~500 mired as an input which doesn't match up the way we want
                color_temp_kelvin = (color_temp-miredMin)/(miredMax-miredMin)*(kelvinMax-kelvinMin)+kelvinMin

                # self._bulb.setWhiteTemperature(color_temp_kelvin, white)
                color_temp_kelvin = max(color_temp_kelvin-2700, 0)
                warm = 255 * (1 - (color_temp_kelvin/3800))
                cold = min(255 * color_temp_kelvin/3800, 255)
                warm *= white/255 # white controls brightness
                cold *= white/255

                if warm > cold: # warm side will activate both cold and warm leds at same rate (much brighter warm mode)
                    cold = warm

                self._bulb.setRgbw(w=warm, w2=cold)
                return
            if brightness is None:
                brightness = self.brightness
            if color_temp > COLOR_TEMP_WARM_VS_COLD_WHITE_CUT_OFF:
                self._bulb.setRgbw(w=brightness)
            else:
                self._bulb.setRgbw(w2=brightness)
            return

        if white is not None:
            if self._mode == MODE_RGBCW:
                current_temp = self.temperature_cw
                if not current_temp[0] and not current_temp[1]:
                    current_temp[0] = 255
                    current_temp[1] = 255
                current_temp[0] *= white/255
                current_temp[1] *= white/255
                self._bulb.setRgbw(w=current_temp[1], w2=current_temp[0])
                return
            elif self._mode == MODE_RGBWW:
                self._bulb.setWarmWhite255(white)
                return


        # Preserve current brightness on color/white level change
        if brightness is None:
            brightness = self.brightness if self.brightness else 255

        # Preserve color on brightness/white level change
        if rgb is None:
            rgb = self._bulb.getRgb()
            if self._mode == MODE_RGBW and rgb[0] == 0 and rgb[1] == 0 and rgb[2] == 0:
                rgb = (255,255,255)


        if white is None and self._mode == MODE_RGBW:
            white = self.white_value

        # handle W only mode (use brightness instead of white value)
        if self._mode == MODE_WHITE:
            self._bulb.setRgbw(0, 0, 0, w=brightness)

        # handle RGBW mode
        elif self._mode == MODE_RGBW:
            self._bulb.setRgbw(*tuple(rgb), w=white, brightness=brightness)

        # handle RGB or RGBCW mode
        else:
            self._bulb.setRgb(*tuple(rgb), brightness=brightness)

    def turn_off(self, **kwargs):
        """Turn the specified or all lights off."""
        self._bulb.turnOff()

    def update(self):
        """Synchronize state with bulb."""
        if not self.available:
            try:
                self._connect()
                self._error_reported = False
            except socket.error:
                self._disconnect()
                if not self._error_reported:
                    _LOGGER.warning(
                        "Failed to connect to bulb %s, %s", self._ipaddr, self._name
                    )
                    self._error_reported = True
                return

        self._bulb.update_state(retry=2)
