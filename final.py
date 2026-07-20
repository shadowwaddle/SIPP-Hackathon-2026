import gc
import time
import board
import displayio
import i2cdisplaybus
import adafruit_displayio_ssd1306
import pwmio
from digitalio import DigitalInOut, Direction, Pull

# Digit rows for 0-9, packed into one bytes object to save RAM.
DIGITS = bytes((
    7, 5, 5, 5, 7,
    2, 6, 2, 2, 7,
    7, 1, 7, 4, 7,
    7, 1, 7, 1, 7,
    5, 5, 7, 1, 1,
    7, 4, 7, 1, 7,
    7, 4, 7, 5, 7,
    7, 1, 2, 2, 2,
    7, 5, 7, 5, 7,
    7, 5, 7, 1, 7
))

# Shared I2C bus for the OLED and MPU6050.
displayio.release_displays()
i2c = board.I2C()

bus = i2cdisplaybus.I2CDisplayBus(i2c, device_address=0x3C)
display = adafruit_displayio_ssd1306.SSD1306(
    bus,
    width=128,
    height=64
)

# MM:SS needs only 38x10 pixels. The bitmap is 40x10 so it also
# fits vertically after rotation as 10x40 pixels.
bitmap = displayio.Bitmap(40, 10, 2)
palette = displayio.Palette(2)
palette[0] = 0
palette[1] = 0xFFFFFF

grid = displayio.TileGrid(bitmap, pixel_shader=palette, x=44, y=27)
group = displayio.Group()
group.append(grid)
display.root_group = group

# Wake the MPU6050.
while not i2c.try_lock():
    pass
try:
    i2c.writeto(0x68, b"\x6b\x00")
finally:
    i2c.unlock()

# Read Y and Z together. Y detects the two side orientations;
# Z distinguishes normal from upside down when Y is near zero.
yz_register = b"\x3d"
yz_data = bytearray(4)

button = DigitalInOut(board.D2)
button.direction = Direction.INPUT
button.pull = Pull.UP

buzzer = pwmio.PWMOut(board.D3, frequency=2000, duty_cycle=0)

# Release temporary setup objects before entering the main loop.
gc.collect()


def block(x, y):
    bitmap[x, y] = 1
    bitmap[x + 1, y] = 1
    bitmap[x, y + 1] = 1
    bitmap[x + 1, y + 1] = 1


def digit(number, x):
    start = number * 5
    row = 0
    while row < 5:
        bits = DIGITS[start + row]
        if bits & 4:
            block(x, row * 2)
        if bits & 2:
            block(x + 2, row * 2)
        if bits & 1:
            block(x + 4, row * 2)
        row += 1


def draw_time(seconds):
    if seconds < 0:
        seconds = 0

    minutes = seconds // 60
    if minutes > 99:
        minutes = 99

    seconds %= 60
    bitmap.fill(0)
    digit(minutes // 10, 0)
    digit(minutes % 10, 8)
    block(18, 1)
    block(18, 3)
    digit(seconds // 10, 24)
    digit(seconds % 10, 32)
    # display.refresh(minimum_frames_per_second=0)


def read_yz():
    while not i2c.try_lock():
        pass
    try:
        i2c.writeto_then_readfrom(0x68, yz_register, yz_data)
    finally:
        i2c.unlock()

    raw_y = (yz_data[0] << 8) | yz_data[1]
    raw_z = (yz_data[2] << 8) | yz_data[3]

    if raw_y & 0x8000:
        raw_y -= 65536
    if raw_z & 0x8000:
        raw_z -= 65536

    return raw_y / 16384, raw_z / 16384


def set_orientation(new_orientation):
    if new_orientation == 0:
        grid.transpose_xy = False
        grid.flip_x = False
        grid.flip_y = False
        grid.x = 44
        grid.y = 29
    elif new_orientation == 1:
        grid.transpose_xy = True
        grid.flip_x = True
        grid.flip_y = False
        grid.x = 61
        grid.y = 18
    elif new_orientation == 2:
        grid.transpose_xy = True
        grid.flip_x = False
        grid.flip_y = True
        grid.x = 61
        grid.y = 18
    else:
        # Upside down: rotate the horizontal clock by 180 degrees.
        grid.transpose_xy = False
        grid.flip_x = True
        grid.flip_y = True
        grid.x = 44
        grid.y = 29
    # display.refresh(minimum_frames_per_second=0)


def beep(duration):
    buzzer.duty_cycle = 32768
    time.sleep(duration)
    buzzer.duty_cycle = 0


def alarm():
    count = 0
    while count < 8:
        beep(0.3)
        time.sleep(0.2)
        count += 1


selected = 0
orientation = -1
running = False
end_time = 0
paused_seconds = 0
last_second = -1
last_button = button.value
loop_count = 0

draw_time(0)

while True:
    now = time.monotonic()
    y, z = read_yz()
    
    if y <= -0.7:
        new_orientation = 1
        choice = 10
    elif y >= 0.7:
        new_orientation = 2
        choice = 30
    elif z <= -0.7:
        new_orientation = 3
        choice = 60
    else:
        new_orientation = 0
        choice = 5

    # Change TileGrid properties only when the orientation actually changes.
    if new_orientation != orientation:
        orientation = new_orientation
        set_orientation(orientation)

    # A new side automatically starts that side's timer.
    if choice != selected:
        selected = choice
        paused_seconds = choice * 60
        end_time = now + paused_seconds
        running = True
        last_second = -1
        draw_time(paused_seconds)
        beep(0.3)

    current_button = button.value

    # Pull-up input: True means released, False means pressed.
    if last_button and not current_button:
        if running:
            paused_seconds = int(end_time - now + 0.999)
            if paused_seconds < 0:
                paused_seconds = 0
            running = False
            draw_time(paused_seconds)
        else:
            end_time = now + paused_seconds
            running = True
            last_second = -1
        beep(0.08)

    if running:
        remaining = int(end_time - now + 0.999)

        if remaining != last_second:
            draw_time(remaining)
            last_second = remaining

        if remaining <= 0:
            draw_time(0)
            alarm()
            selected = 0
            paused_seconds = 0
            running = False

    last_button = current_button

    # Occasionally collect unused temporary objects to reduce fragmentation.
    loop_count += 1
    if loop_count >= 250:
        loop_count = 0
        gc.collect()

    time.sleep(0.04)
