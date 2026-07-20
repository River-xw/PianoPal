// PianoPal hand micro:bit firmware for MakeCode.
//
// One micro:bit is mounted on each hand. It reads:
// - fingertip MPU6050 at I2C address 0x68
// - wrist MPU6050 at I2C address 0x69
// - hand-back acceleration from the micro:bit itself
//
// Data packet, one line per sample:
// hand,seq,timestamp_ms,
// tip_ax,tip_ay,tip_az,tip_gx,tip_gy,tip_gz,
// wrist_ax,wrist_ay,wrist_az,wrist_gx,wrist_gy,wrist_gz,
// back_ax,back_ay,back_az

bluetooth.onBluetoothConnected(function () {
    basic.showIcon(IconNames.Yes)
})

bluetooth.onBluetoothDisconnected(function () {
    connected = false
    running = false
    basic.showIcon(IconNames.No)
})

bluetooth.onUartDataReceived(serial.delimiters(Delimiters.NewLine), function () {
    msg = bluetooth.uartReadUntil(serial.delimiters(Delimiters.NewLine))
    if (msg == "CONNECT") {
        connected = true
        bluetooth.uartWriteString("READY\n")
        basic.showIcon(IconNames.Heart)
    } else if (msg == "START LEFT" || msg == "START L") {
        if (connected) {
            startStreaming("L")
            bluetooth.uartWriteString("STARTED LEFT\n")
        }
    } else if (msg == "START RIGHT" || msg == "START R") {
        if (connected) {
            startStreaming("R")
            bluetooth.uartWriteString("STARTED RIGHT\n")
        }
    } else if (msg == "STOP") {
        running = false
        bluetooth.uartWriteString("STOPPED\n")
        basic.showIcon(IconNames.No)
    }
})

function startStreaming(label: string) {
    hand = label
    running = true
    seq = 0
    startTime = input.runningTime()
    basic.showIcon(IconNames.Happy)
}

function writeRegister(address: number, registerAddress: number, value: number) {
    let buffer = pins.createBuffer(2)
    buffer.setNumber(NumberFormat.UInt8BE, 0, registerAddress)
    buffer.setNumber(NumberFormat.UInt8BE, 1, value)
    pins.i2cWriteBuffer(address, buffer, false)
}

function readRegisters(address: number, registerAddress: number, length: number): Buffer {
    pins.i2cWriteNumber(address, registerAddress, NumberFormat.UInt8BE, true)
    return pins.i2cReadBuffer(address, length, false)
}

function initMpu(address: number): boolean {
    let ok = true
    try {
        writeRegister(address, MPU_PWR_MGMT_1, 0)
        basic.pause(10)
        writeRegister(address, MPU_ACCEL_CONFIG, 0)
        writeRegister(address, MPU_GYRO_CONFIG, 0)
    } catch (e) {
        ok = false
    }
    return ok
}

function readMpu(address: number): number[] {
    let data = readRegisters(address, MPU_ACCEL_XOUT_H, 14)
    let ax = data.getNumber(NumberFormat.Int16BE, 0)
    let ay = data.getNumber(NumberFormat.Int16BE, 2)
    let az = data.getNumber(NumberFormat.Int16BE, 4)
    let gxRaw = data.getNumber(NumberFormat.Int16BE, 8)
    let gyRaw = data.getNumber(NumberFormat.Int16BE, 10)
    let gzRaw = data.getNumber(NumberFormat.Int16BE, 12)

    return [
        ax,
        ay,
        az,
        Math.round(gxRaw * 10 / GYRO_SCALE) / 10,
        Math.round(gyRaw * 10 / GYRO_SCALE) / 10,
        Math.round(gzRaw * 10 / GYRO_SCALE) / 10
    ]
}

function zeroMpu(): number[] {
    return [0, 0, 0, 0, 0, 0]
}

function packetLine(
    label: string,
    sequence: number,
    timestampMs: number,
    tip: number[],
    wrist: number[],
    backAx: number,
    backAy: number,
    backAz: number
): string {
    return "" +
        label + "," +
        sequence + "," +
        timestampMs + "," +
        tip[0] + "," +
        tip[1] + "," +
        tip[2] + "," +
        tip[3] + "," +
        tip[4] + "," +
        tip[5] + "," +
        wrist[0] + "," +
        wrist[1] + "," +
        wrist[2] + "," +
        wrist[3] + "," +
        wrist[4] + "," +
        wrist[5] + "," +
        backAx + "," +
        backAy + "," +
        backAz + "\n"
}

let backAz = 0
let backAy = 0
let backAx = 0
let wristValues: number[] = []
let tipValues: number[] = []
let timestampMs = 0
let startTime = 0
let seq = 0
let running = false
let connected = false
let msg = ""
let hand = "L"
let wristReady = false
let tipReady = false

let TIP_MPU_ADDR = 0x68
let WRIST_MPU_ADDR = 0x69
let MPU_PWR_MGMT_1 = 0x6B
let MPU_ACCEL_CONFIG = 0x1C
let MPU_GYRO_CONFIG = 0x1B
let MPU_ACCEL_XOUT_H = 0x3B
let GYRO_SCALE = 131

bluetooth.startUartService()
tipReady = initMpu(TIP_MPU_ADDR)
wristReady = initMpu(WRIST_MPU_ADDR)

if (tipReady && wristReady) {
    basic.showIcon(IconNames.Yes)
} else {
    basic.showIcon(IconNames.Sad)
}

basic.forever(function () {
    if (!(connected)) {
        basic.pause(500)
        return
    }

    if (!(running)) {
        basic.pause(20)
        return
    }

    timestampMs = input.runningTime() - startTime
    seq += 1

    if (tipReady) {
        tipValues = readMpu(TIP_MPU_ADDR)
    } else {
        tipValues = zeroMpu()
    }

    if (wristReady) {
        wristValues = readMpu(WRIST_MPU_ADDR)
    } else {
        wristValues = zeroMpu()
    }

    backAx = input.acceleration(Dimension.X)
    backAy = input.acceleration(Dimension.Y)
    backAz = input.acceleration(Dimension.Z)

    bluetooth.uartWriteString(packetLine(
        hand,
        seq,
        timestampMs,
        tipValues,
        wristValues,
        backAx,
        backAy,
        backAz
    ))

    basic.pause(20)
})
