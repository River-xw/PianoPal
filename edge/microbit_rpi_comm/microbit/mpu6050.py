"""MPU6050 gyroscope driver for micro:bit v2 (I2C on pin19=SCL, pin20=SDA)."""

from microbit import i2c, pin19, pin20

MPU6050_ADDR = 0x68
WHO_AM_I = 0x75
PWR_MGMT_1 = 0x6B
GYRO_CONFIG = 0x1B
GYRO_XOUT_H = 0x43

# ±250 °/s → 131 LSB per °/s
GYRO_SCALE = 131.0


def _to_signed(msb, lsb):
    value = (msb << 8) | lsb
    if value >= 0x8000:
        value -= 0x10000
    return value


def init():
    i2c.init(freq=400000, sda=pin20, scl=pin19)
    chip_id = i2c.readfrom_mem(MPU6050_ADDR, WHO_AM_I, 1)[0]
    if chip_id != 0x68:
        raise OSError("MPU6050 not found (WHO_AM_I=0x{:02x})".format(chip_id))
    i2c.writeto_mem(MPU6050_ADDR, PWR_MGMT_1, b"\x00")
    i2c.writeto_mem(MPU6050_ADDR, GYRO_CONFIG, b"\x00")


def read_gyro_raw():
    data = i2c.readfrom_mem(MPU6050_ADDR, GYRO_XOUT_H, 6)
    return (
        _to_signed(data[0], data[1]),
        _to_signed(data[2], data[3]),
        _to_signed(data[4], data[5]),
    )


def read_gyro_dps():
    gx, gy, gz = read_gyro_raw()
    return (
        int(gx / GYRO_SCALE),
        int(gy / GYRO_SCALE),
        int(gz / GYRO_SCALE),
    )
