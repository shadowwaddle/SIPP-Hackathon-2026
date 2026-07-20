import time
import board
import struct
import displayio
import i2cdisplaybus
import adafruit_displayio_ssd1306
import pwmio
from digitalio import DigitalInOut, Direction, Pull

# ---------- Hardware and timer settings ----------
BUTTON_PIN = board.D2
BUZZER_PIN = board.D3
MPU_ADDRESS = 0x68
OLED_ADDRESS = 0x3C

TIMER_1 = 1
TIMER_2 = 10
TIMER_3 = 30

# Each digit is stored as five rows of three binary pixels.
DIGITS = (
    (7, 5, 5, 5, 7),
    (2, 6, 2, 2, 7),
    (7, 1, 7, 4, 7),
    (7, 1, 7, 1, 7),
    (5, 5, 7, 1, 1),
    (7, 4, 7, 1, 7),
    (7, 4, 7, 5, 7),
    (7, 1, 2, 2, 2),
    (7, 5, 7, 5, 7),
    (7, 5, 7, 1, 7),
)

# ---------- OLED setup ----------
displayio.release_displays()
i2c = board.I2C()

display_bus = i2cdisplaybus.I2CDisplayBus(
    i2c,
    device_address=OLED_ADDRESS
)

display = adafruit_displayio_ssd1306.SSD1306(
    display_bus,
    width=128,
    height=64
)

clock_bitmap = displayio.Bitmap(72, 15, 2)
palette = displayio.Palette(2)
palette[0] = 0x000000
palette[1] = 0xFFFFFF

screen = displayio.Group()
screen.append(
    displayio.TileGrid(
        clock_bitmap,
        pixel_shader=palette,
        x=28,
        y=24
    )
)
display.root_group = screen

# ---------- MPU6050 setup ----------
while not i2c.try_lock():
    pass
try:
    # Write 0 to the power-management register to wake the sensor.
    i2c.writeto(MPU_ADDRESS, bytes((0x6B, 0x00)))
finally:
    i2c.unlock()

mpu_data = bytearray(6)
mpu_register = bytes((0x3B,))

# ---------- Button and buzzer setup ----------
button = DigitalInOut(BUTTON_PIN)
button.direction = Direction.INPUT
button.pull = Pull.UP

buzzer = pwmio.PWMOut(
    BUZZER_PIN,
    frequency=2000,
    duty_cycle=0
)


# ---------- Display functions ----------
def draw_block(x, y):
    """Draw one 3x3 white square."""
    for px in range(x, x + 3):
        for py in range(y, y + 3):
            clock_bitmap[px, py] = 1


def draw_digit(number, x):
    """Draw one digit using the small 3x5 font."""
    for row, bits in enumerate(DIGITS[number]):
        for column in range(3):
            if bits & (4 >> column):
                draw_block(x + column * 3, row * 3)


def draw_time(total_seconds):
    """Display a countdown value as MM:SS."""
    total_seconds = max(0, total_seconds)
    minutes = min(99, total_seconds // 60)
    seconds = total_seconds % 60

    clock_bitmap.fill(0)
    draw_digit(minutes // 10, 0)
    draw_digit(minutes % 10, 12)
    draw_block(27, 3)
    draw_block(27, 9)
    draw_digit(seconds // 10, 36)
    draw_digit(seconds % 10, 48)


# ---------- Sensor and sound functions ----------
def read_y():
    """Read and return only the MPU6050 Y-axis acceleration."""
    while not i2c.try_lock():
        pass
    try:
        i2c.writeto_then_readfrom(
            MPU_ADDRESS,
            mpu_register,
            mpu_data
        )
    finally:
        i2c.unlock()

    # The middle value is the Y-axis reading.
    _, raw_y, _ = struct.unpack(">hhh", mpu_data)
    return raw_y / 16384.0


def choose_timer(y):
    """Map the Y-axis orientation to a timer duration."""
    if -0.7 < y < 0.7:
        return TIMER_1
    if y <= -0.7:
        return TIMER_2
    return TIMER_3


def beep(duration):
    """Sound the buzzer for a short time."""
    buzzer.duty_cycle = 32768
    time.sleep(duration)
    buzzer.duty_cycle = 0


def alarm():
    """Play the completion alarm."""
    for _ in range(5):
        beep(0.3)
        time.sleep(0.2)


# ---------- Timer state ----------
selected_minutes = 0
running = False
end_time = 0
paused_seconds = 0
last_second = -1
last_button = button.value
last_print = 0

draw_time(0)
print("Timer ready")
print("Tilt to choose a time. Press the button to pause or resume.")

# ---------- Main loop ----------
while True:
    now = time.monotonic()
    current_button = button.value
    y = read_y()
    choice = choose_timer(y)

    # A different orientation selects and starts a new timer.
    if choice != selected_minutes:
        selected_minutes = choice
        paused_seconds = selected_minutes * 60
        end_time = now + paused_seconds
        running = True
        last_second = -1
        draw_time(paused_seconds)
        beep(0.08)
        print("Selected and started:", selected_minutes, "minutes")

    # Print only the Y value once per second.
    if now - last_print >= 1:
        print("Y:", round(y, 2))
        last_print = now

    # A new button press toggles pause and resume.
    if last_button and not current_button and selected_minutes:
        if running:
            paused_seconds = max(0, int(end_time - now + 0.999))
            running = False
            draw_time(paused_seconds)
            print("Paused")
        else:
            end_time = now + paused_seconds
            running = True
            last_second = -1
            print("Resumed")

        beep(0.08)

    # Update the countdown only when the displayed second changes.
    if running:
        remaining = int(end_time - now + 0.999)

        if remaining != last_second:
            draw_time(remaining)
            last_second = remaining

        if remaining <= 0:
            draw_time(0)
            alarm()
            selected_minutes = 0
            paused_seconds = 0
            running = False
            print("Time is up")

    last_button = current_button
    time.sleep(0.04)
