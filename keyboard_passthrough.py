"""
Keyboard Passthrough with Custom Actions
Waveshare RP2350-USB-A + CircuitPython 10.x

Requires in /lib:
  adafruit_hid/
  neopixel.mpy

Requires boot.py on CIRCUITPY root:
  import usb_host, board
  usb_host.Port(board.GP12, board.GP13)
"""

import usb.core
import usb_hid
import board
import time
import neopixel
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keycode import Keycode
from adafruit_hid.keyboard_layout_us import KeyboardLayoutUS

# ─── OUTPUT: HID keyboard that appears to the host PC ────────────────────────
kbd_out = Keyboard(usb_hid.devices)

# ─── NEOPIXEL LED ─────────────────────────────────────────────────────────────
np = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.2, auto_write=True)

def led(r, g, b):
    np[0] = (r, g, b)

def led_off():
    np[0] = (0, 0, 0)

def flash_led(r, g, b, times=3):
    for _ in range(times):
        led(r, g, b); time.sleep(0.05)
        led_off();    time.sleep(0.05)

# ─── MODIFIER BITMASKS ────────────────────────────────────────────────────────
MOD_LCTRL  = 0x01
MOD_LSHIFT = 0x02
MOD_LALT   = 0x04
MOD_LGUI   = 0x08
MOD_RCTRL  = 0x10
MOD_RSHIFT = 0x20
MOD_RALT   = 0x40
MOD_RGUI   = 0x80

# Modifier byte bit → adafruit_hid Keycode
MODIFIER_MAP = {
    MOD_LCTRL:  Keycode.LEFT_CONTROL,
    MOD_LSHIFT: Keycode.LEFT_SHIFT,
    MOD_LALT:   Keycode.LEFT_ALT,
    MOD_LGUI:   Keycode.LEFT_GUI,
    MOD_RCTRL:  Keycode.RIGHT_CONTROL,
    MOD_RSHIFT: Keycode.RIGHT_SHIFT,
    MOD_RALT:   Keycode.RIGHT_ALT,
    MOD_RGUI:   Keycode.RIGHT_GUI,
}

def modifier_keycodes(modifier_byte):
    return [kc for bit, kc in MODIFIER_MAP.items() if modifier_byte & bit]

# ─── CUSTOM ACTIONS ───────────────────────────────────────────────────────────
# Add your own actions here.
# Format: (modifier_byte, keycode): (function, pass_through_to_pc)
#   modifier_byte : combine MOD_* constants, or 0x00 for no modifier
#   keycode       : raw HID keycode byte (A=0x04, F1=0x3A, F13=0x68, etc.)
#   pass_through  : True = key is also forwarded to PC, False = consumed

custom_layer = False

def action_flash():
    """Flash LED green 3 times."""
    flash_led(0, 50, 0, times=3)

def action_type_macro():
    """Type a string on the host PC."""
    layout = KeyboardLayoutUS(kbd_out)
    layout.write("Hello from Pico!\n")

def action_toggle_layer():
    """Toggle a custom layer state, show on LED."""
    global custom_layer
    custom_layer = not custom_layer
    if custom_layer:
        led(0, 0, 50)   # blue = layer on
    else:
        led_off()
    print("Layer:", "ON" if custom_layer else "OFF")

# ── Edit this dict to define your key intercepts ─────────────────────────────
CUSTOM_ACTIONS = {
    (0x00, 0x04): (action_flash,           True),  # A → flash LED (consumed)
    (MOD_LCTRL, 0x3A): (action_type_macro, False),  # LCTRL+F1 → type macro
    (0x00, 0x47): (action_toggle_layer,    True),   # Scroll Lock → toggle layer
}

# ─── ENDPOINT AUTO-DETECTION ─────────────────────────────────────────────────
# Keyboards typically use 0x81, but composite devices may use 0x82, 0x83, etc.
CANDIDATE_ENDPOINTS = [0x81, 0x82, 0x83, 0x84]

def detect_endpoint(dev):
    """
    Try each candidate endpoint with a blocking wait for the first keypress.
    Returns (endpoint, report_has_id).

    report_has_id=True means the report starts with a report ID byte:
      Standard boot report: [modifier, reserved, kc0..kc5]
      Report-ID report:     [report_id, modifier, reserved, kc0..kc4]
    """
    probe = bytearray(8)
    print("Press any key on the keyboard to complete detection...")

    for ep in CANDIDATE_ENDPOINTS:
        try:
            dev.read(ep, probe, timeout=0)
            # A real keyboard boot report always has buf[1] == 0x00 (reserved)
            has_id = (probe[0] in range(1, 10)) and (probe[2] == 0x00)
            print("Endpoint found:", hex(ep), "| Report ID prefix:", has_id)
            print("Sample report:", list(probe))
            return ep, has_id
        except usb.core.USBTimeoutError:
            print("No response on", hex(ep), "— trying next...")
        except Exception as e:
            print("Probe error on", hex(ep), ":", e)

    print("No endpoint responded, defaulting to 0x81")
    return 0x81, False

# ─── USB HOST: find and connect to keyboard ───────────────────────────────────
def find_keyboard():
    for dev in usb.core.find(find_all=True):
        return dev
    return None

def connect_keyboard():
    global prev_buf
    dev = find_keyboard()
    if dev is None:
        return None, None, False
    try:
        dev.set_configuration()
        print("Keyboard connected:", dev.manufacturer, dev.product)
    except Exception as e:
        print("Connection error:", e)
        return None, None, False

    print("Detecting endpoint — press any key on the keyboard now...")
    ep, has_id = detect_endpoint(dev)
    if ep is None:
        print("No endpoint responded during probe, defaulting to 0x81")
        ep = 0x81
        has_id = False

    flash_led(0, 50, 0, times=2)
    prev_buf[:] = bytearray(8)  # reset change-detection on each connect
    return dev, ep, has_id

# ─── REPORT PARSING ───────────────────────────────────────────────────────────
def parse_report(buf, has_id):
    """
    Extract (modifier, keycodes) from an 8-byte HID report.

    Standard boot report (has_id=False):
      [0] modifier  [1] reserved  [2..7] keycodes

    Report-ID prefixed (has_id=True):
      [0] report_id  [1] modifier  [2] reserved  [3..7] keycodes
    """
    if has_id:
        modifier = buf[1]
        keycodes = [k for k in buf[3:8] if k != 0x00]
    else:
        modifier = buf[0]
        keycodes = [k for k in buf[2:8] if k != 0x00]
    return modifier, keycodes

# ─── MAIN LOOP ────────────────────────────────────────────────────────────────
print("Keyboard passthrough starting...")
print("Waiting for USB keyboard...")

kbd_dev = None
hid_endpoint = None
report_has_id = False
buf = bytearray(8)
prev_buf = bytearray(8)

while True:
    # ── Connect / reconnect ───────────────────────────────────────────────────
    if kbd_dev is None:
        kbd_dev, hid_endpoint, report_has_id = connect_keyboard()
        if kbd_dev is None:
            time.sleep(0.5)
            continue

    # ── Read HID report ───────────────────────────────────────────────────────
    try:
        kbd_dev.read(hid_endpoint, buf, timeout=10)
    except usb.core.USBTimeoutError:
        continue
    except Exception as e:
        print("Read error:", e)
        kbd_dev = None
        hid_endpoint = None
        kbd_out.release_all()
        led_off()
        continue

    # Skip if keyboard state unchanged (ignore any counter/padding bytes)
    modifier, keycodes = parse_report(buf, report_has_id)
    prev_modifier, prev_keycodes = parse_report(prev_buf, report_has_id)
    if modifier == prev_modifier and keycodes == prev_keycodes:
        continue
    prev_buf[:] = buf

    # ── Check custom actions ──────────────────────────────────────────────────
    pass_keycodes = list(keycodes)
    pass_modifier = modifier

    for kc in keycodes:
        key = (modifier, kc)
        if key in CUSTOM_ACTIONS:
            fn, pass_through = CUSTOM_ACTIONS[key]
            fn()
            if not pass_through:
                pass_keycodes.remove(kc)
                if not pass_keycodes:
                    pass_modifier = 0

    # ── Forward to host PC ────────────────────────────────────────────────────
    forward = modifier_keycodes(pass_modifier) + pass_keycodes

    try:
        if forward:
            kbd_out.press(*forward)
        else:
            kbd_out.release_all()
    except Exception as e:
        print("HID send error:", e)
