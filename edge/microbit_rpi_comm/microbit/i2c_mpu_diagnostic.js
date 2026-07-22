// Minimal MPU6050 I2C diagnostic for MakeCode.
//
// Use this before the BLE firmware if MPU values stay at zero.
// Connect one MPU6050 first:
// VCC -> 3V, GND -> GND, SCL -> pin19, SDA -> pin20.
//
// The display shows:
// 3 = 0x68 and 0x69 both responded like MPU6050
// 1 = only 0x68 responded like MPU6050
// 2 = only 0x69 responded like MPU6050
// 0 = neither address responded like MPU6050

function readRegisterByte(address: number, registerAddress: number): number {
    pins.i2cWriteNumber(address, registerAddress, NumberFormat.UInt8BE, true)
    basic.pause(2)
    data = pins.i2cReadBuffer(address, 1, false)
    if (data.length < 1) {
        return -1
    }
    return data.getNumber(NumberFormat.UInt8BE, 0)
}

let who69 = 0
let who68 = 0
let data = pins.createBuffer(0)
let MPU_WHO_AM_I = 0x75

basic.forever(function () {
    who68 = readRegisterByte(0x68, MPU_WHO_AM_I)
    who69 = readRegisterByte(0x69, MPU_WHO_AM_I)

    if (who68 == 0x68 && who69 == 0x68) {
        basic.showNumber(3)
    } else if (who68 == 0x68) {
        basic.showNumber(1)
    } else if (who69 == 0x68) {
        basic.showNumber(2)
    } else {
        basic.showNumber(0)
    }

    basic.pause(1000)
})
