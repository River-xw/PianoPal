// PianoPal hand micro:bit firmware for MakeCode.
//
// One micro:bit is mounted on each hand. This low-memory firmware reads:
// - fingertip MPU6050 acceleration + gyroscope at I2C address 0x68
// - hand-back MPU6050 acceleration + gyroscope at I2C address 0x69
// - wrist x/y/z acceleration from the micro:bit itself
//
// Data packet, one line per sample:
// hand,seq,timestamp_ms,
// tip_ax,tip_ay,tip_az,tip_gx,tip_gy,tip_gz,
// back_ax,back_ay,back_az,back_gx,back_gy,back_gz,
// wrist_ax,wrist_ay,wrist_az

bluetooth.onBluetoothConnected(function () {
    basic.showIcon(IconNames.Yes)
})

bluetooth.onBluetoothDisconnected(function () {
    connected = false
    running = false
    basic.showIcon(IconNames.No)
})

bluetooth.onUartDataReceived(serial.delimiters(Delimiters.NewLine), function () {
    let msg = bluetooth.uartReadUntil(serial.delimiters(Delimiters.NewLine))
    if (msg == "CONNECT") {
        connected = true
        basic.showIcon(IconNames.Heart)
    } else if (msg == "START LEFT" || msg == "START L") {
        if (connected) {
            startStreaming("L")
        }
    } else if (msg == "START RIGHT" || msg == "START R") {
        if (connected) {
            startStreaming("R")
        }
    } else if (msg == "STOP") {
        running = false
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
    pins.i2cWriteNumber(
        address,
        registerAddress * 256 + value,
        NumberFormat.UInt16BE,
        false
    )
}

function readRegisterByte(address: number, registerAddress: number): number {
    pins.i2cWriteNumber(address, registerAddress, NumberFormat.UInt8BE, true)
    sensorBuffer = pins.i2cReadBuffer(address, 1, false)
    if (sensorBuffer.length < 1) {
        return -1
    }
    return sensorBuffer.getNumber(NumberFormat.UInt8BE, 0)
}

function initMpu(address: number): boolean {
    if (readRegisterByte(address, MPU_WHO_AM_I) != 0x68) {
        return false
    }
    writeRegister(address, MPU_PWR_MGMT_1, 0)
    basic.pause(5)
    writeRegister(address, MPU_ACCEL_CONFIG, 0)
    writeRegister(address, MPU_GYRO_CONFIG, 0)
    return true
}

function clearTipMpu() {
    tipAx = 0
    tipAy = 0
    tipAz = 0
    tipGx = 0
    tipGy = 0
    tipGz = 0
}

function clearHandBackMpu() {
    handBackAx = 0
    handBackAy = 0
    handBackAz = 0
    handBackGx = 0
    handBackGy = 0
    handBackGz = 0
}

function refreshMpuStatus() {
    if (readRegisterByte(TIP_MPU_ADDR, MPU_WHO_AM_I) == 0x68) {
        if (!(tipReady)) {
            tipReady = initMpu(TIP_MPU_ADDR)
        }
    } else {
        tipReady = false
    }

    if (readRegisterByte(HAND_BACK_MPU_ADDR, MPU_WHO_AM_I) == 0x68) {
        if (!(handBackReady)) {
            handBackReady = initMpu(HAND_BACK_MPU_ADDR)
        }
    } else {
        handBackReady = false
    }

    if (!(tipReady)) {
        clearTipMpu()
    }

    if (!(handBackReady)) {
        clearHandBackMpu()
    }
}

function readTipMpu() {
    if (!(tipReady)) {
        return
    }
    pins.i2cWriteNumber(TIP_MPU_ADDR, MPU_ACCEL_XOUT_H, NumberFormat.UInt8BE, true)
    sensorBuffer = pins.i2cReadBuffer(TIP_MPU_ADDR, 14, false)
    if (sensorBuffer.length >= 14) {
        tipAx = sensorBuffer.getNumber(NumberFormat.Int16BE, 0)
        tipAy = sensorBuffer.getNumber(NumberFormat.Int16BE, 2)
        tipAz = sensorBuffer.getNumber(NumberFormat.Int16BE, 4)
        tipGx = sensorBuffer.getNumber(NumberFormat.Int16BE, 8)
        tipGy = sensorBuffer.getNumber(NumberFormat.Int16BE, 10)
        tipGz = sensorBuffer.getNumber(NumberFormat.Int16BE, 12)
    }
}

function readHandBackMpu() {
    if (!(handBackReady)) {
        return
    }
    pins.i2cWriteNumber(HAND_BACK_MPU_ADDR, MPU_ACCEL_XOUT_H, NumberFormat.UInt8BE, true)
    sensorBuffer = pins.i2cReadBuffer(HAND_BACK_MPU_ADDR, 14, false)
    if (sensorBuffer.length >= 14) {
        handBackAx = sensorBuffer.getNumber(NumberFormat.Int16BE, 0)
        handBackAy = sensorBuffer.getNumber(NumberFormat.Int16BE, 2)
        handBackAz = sensorBuffer.getNumber(NumberFormat.Int16BE, 4)
        handBackGx = sensorBuffer.getNumber(NumberFormat.Int16BE, 8)
        handBackGy = sensorBuffer.getNumber(NumberFormat.Int16BE, 10)
        handBackGz = sensorBuffer.getNumber(NumberFormat.Int16BE, 12)
    }
}

let wristAz = 0
let wristAy = 0
let wristAx = 0
let handBackGz = 0
let handBackGy = 0
let handBackGx = 0
let handBackAz = 0
let handBackAy = 0
let handBackAx = 0
let tipAz = 0
let tipAy = 0
let tipAx = 0
let tipGz = 0
let tipGy = 0
let tipGx = 0
let timestampMs = 0
let lastMpuRefreshMs = 0
let startTime = 0
let seq = 0
let running = false
let connected = false
let hand = "L"
let handBackReady = false
let tipReady = false
let SAMPLE_INTERVAL_MS = 500
let MPU_REFRESH_INTERVAL_MS = 10000
let TIP_MPU_ADDR = 0x68
let HAND_BACK_MPU_ADDR = 0x69
let MPU_PWR_MGMT_1 = 0x6B
let MPU_ACCEL_CONFIG = 0x1C
let MPU_GYRO_CONFIG = 0x1B
let MPU_ACCEL_XOUT_H = 0x3B
let MPU_WHO_AM_I = 0x75
let sensorBuffer = pins.createBuffer(0)

bluetooth.startUartService()
refreshMpuStatus()

if (tipReady && handBackReady) {
    basic.showNumber(2)
} else if (tipReady || handBackReady) {
    basic.showNumber(1)
} else {
    basic.showNumber(0)
}

basic.forever(function () {
    if (!(connected)) {
        basic.pause(500)
        return
    }

    if (!(running)) {
        basic.pause(100)
        return
    }

    timestampMs = input.runningTime() - startTime
    seq += 1

    if (input.runningTime() - lastMpuRefreshMs >= MPU_REFRESH_INTERVAL_MS) {
        lastMpuRefreshMs = input.runningTime()
        refreshMpuStatus()
    }

    readTipMpu()
    readHandBackMpu()

    wristAx = input.acceleration(Dimension.X)
    wristAy = input.acceleration(Dimension.Y)
    wristAz = input.acceleration(Dimension.Z)

    bluetooth.uartWriteString(
        "" +
        hand + "," +
        seq + "," +
        timestampMs + "," +
        tipAx + "," +
        tipAy + "," +
        tipAz + "," +
        tipGx + "," +
        tipGy + "," +
        tipGz + "," +
        handBackAx + "," +
        handBackAy + "," +
        handBackAz + "," +
        handBackGx + "," +
        handBackGy + "," +
        handBackGz + "," +
        wristAx + "," +
        wristAy + "," +
        wristAz + "\n"
    )

    basic.pause(SAMPLE_INTERVAL_MS)
})
