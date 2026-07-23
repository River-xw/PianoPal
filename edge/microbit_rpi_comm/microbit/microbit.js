// PianoPal hand micro:bit firmware for MakeCode.
//
// One micro:bit is mounted on each hand. This low-memory firmware reads:
// - fingertip MPU6050 acceleration + gyroscope at I2C address 0x68
// - hand-back MPU6050 acceleration + gyroscope at I2C address 0x69
// - wrist x/y/z acceleration from the micro:bit itself
//
// Data packet, one line per sample. The Raspberry Pi keeps this CSV protocol:
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
    running = false
    initializeSensors()
    hand = label
    seq = 0
    startTime = input.runningTime()
    running = true
    if (tipReady && handBackReady) {
        basic.showIcon(IconNames.Happy)
        sendUartMessage("SENSORS_OK," + hand + "\n")
    } else {
        reportSensorError(hand)
        showSensorStatus()
    }
}

function sendUartMessage(message: string) {
    let offset = 0
    while (offset < message.length) {
        bluetooth.uartWriteString(message.substr(offset, UART_CHUNK_CHARS))
        offset += UART_CHUNK_CHARS
        if (offset < message.length) {
            basic.pause(UART_CHUNK_PAUSE_MS)
        }
    }
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
    writeRegister(address, MPU_CONFIG, MPU_DLPF_44HZ)
    writeRegister(address, MPU_SMPLRT_DIV, 4)
    writeRegister(address, MPU_ACCEL_CONFIG, MPU_ACCEL_RANGE_8G)
    writeRegister(address, MPU_GYRO_CONFIG, MPU_GYRO_RANGE_2000DPS)
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

function initializeSensors() {
    tipReady = initMpu(TIP_MPU_ADDR)
    handBackReady = initMpu(HAND_BACK_MPU_ADDR)

    if (!(tipReady)) {
        clearTipMpu()
    }

    if (!(handBackReady)) {
        clearHandBackMpu()
    }
}

function showSensorStatus() {
    if (tipReady && handBackReady) {
        basic.showNumber(2)
    } else if (tipReady || handBackReady) {
        basic.showNumber(1)
    } else {
        basic.showNumber(0)
    }
}

function reportSensorError(label: string) {
    let failed = "BOTH"
    if (tipReady && !(handBackReady)) {
        failed = "HAND_BACK"
    } else if (!(tipReady) && handBackReady) {
        failed = "FINGERTIP"
    }
    sendUartMessage("SENSOR_ERROR," + label + "," + failed + "\n")
}

function readTipMpu(): boolean {
    if (!(tipReady)) {
        return false
    }
    pins.i2cWriteNumber(TIP_MPU_ADDR, MPU_ACCEL_XOUT_H, NumberFormat.UInt8BE, true)
    sensorBuffer = pins.i2cReadBuffer(TIP_MPU_ADDR, 14, false)
    if (sensorBuffer.length < 14) {
        return false
    }

    tipAx = sensorBuffer.getNumber(NumberFormat.Int16BE, 0)
    tipAy = sensorBuffer.getNumber(NumberFormat.Int16BE, 2)
    tipAz = sensorBuffer.getNumber(NumberFormat.Int16BE, 4)
    tipGx = sensorBuffer.getNumber(NumberFormat.Int16BE, 8)
    tipGy = sensorBuffer.getNumber(NumberFormat.Int16BE, 10)
    tipGz = sensorBuffer.getNumber(NumberFormat.Int16BE, 12)
    return !(
        tipAx == 0 && tipAy == 0 && tipAz == 0 &&
        tipGx == 0 && tipGy == 0 && tipGz == 0
    )
}

function readHandBackMpu(): boolean {
    if (!(handBackReady)) {
        return false
    }
    pins.i2cWriteNumber(HAND_BACK_MPU_ADDR, MPU_ACCEL_XOUT_H, NumberFormat.UInt8BE, true)
    sensorBuffer = pins.i2cReadBuffer(HAND_BACK_MPU_ADDR, 14, false)
    if (sensorBuffer.length < 14) {
        return false
    }

    handBackAx = sensorBuffer.getNumber(NumberFormat.Int16BE, 0)
    handBackAy = sensorBuffer.getNumber(NumberFormat.Int16BE, 2)
    handBackAz = sensorBuffer.getNumber(NumberFormat.Int16BE, 4)
    handBackGx = sensorBuffer.getNumber(NumberFormat.Int16BE, 8)
    handBackGy = sensorBuffer.getNumber(NumberFormat.Int16BE, 10)
    handBackGz = sensorBuffer.getNumber(NumberFormat.Int16BE, 12)
    return !(
        handBackAx == 0 && handBackAy == 0 && handBackAz == 0 &&
        handBackGx == 0 && handBackGy == 0 && handBackGz == 0
    )
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
let packetLine = ""
let loopStartedMs = 0
let loopElapsedMs = 0
let tipReadOk = false
let handBackReadOk = false
let sensorStatusChanged = false
let startTime = 0
let seq = 0
let running = false
let connected = false
let hand = "L"
let handBackReady = false
let tipReady = false
let TARGET_SAMPLE_PERIOD_MS = 50
let UART_CHUNK_CHARS = 18
let UART_CHUNK_PAUSE_MS = 3
let TIP_MPU_ADDR = 0x68
let HAND_BACK_MPU_ADDR = 0x69
let MPU_PWR_MGMT_1 = 0x6B
let MPU_SMPLRT_DIV = 0x19
let MPU_CONFIG = 0x1A
let MPU_ACCEL_CONFIG = 0x1C
let MPU_GYRO_CONFIG = 0x1B
let MPU_ACCEL_XOUT_H = 0x3B
let MPU_WHO_AM_I = 0x75
let MPU_DLPF_44HZ = 0x03
let MPU_ACCEL_RANGE_8G = 0x10
let MPU_GYRO_RANGE_2000DPS = 0x18
let sensorBuffer = pins.createBuffer(0)

bluetooth.startUartService()
initializeSensors()
showSensorStatus()

basic.forever(function () {
    if (!(connected)) {
        basic.pause(500)
        return
    }

    if (!(running)) {
        basic.pause(100)
        return
    }

    loopStartedMs = input.runningTime()
    timestampMs = input.runningTime() - startTime
    seq += 1

    tipReadOk = readTipMpu()
    handBackReadOk = readHandBackMpu()
    sensorStatusChanged = false
    if (tipReady && !(tipReadOk)) {
        tipReady = false
        clearTipMpu()
        sensorStatusChanged = true
    }
    if (handBackReady && !(handBackReadOk)) {
        handBackReady = false
        clearHandBackMpu()
        sensorStatusChanged = true
    }
    if (sensorStatusChanged) {
        reportSensorError(hand)
        showSensorStatus()
    }

    wristAx = input.acceleration(Dimension.X)
    wristAy = input.acceleration(Dimension.Y)
    wristAz = input.acceleration(Dimension.Z)

    packetLine = (
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
    sendUartMessage(packetLine)

    loopElapsedMs = input.runningTime() - loopStartedMs
    if (loopElapsedMs < TARGET_SAMPLE_PERIOD_MS) {
        basic.pause(TARGET_SAMPLE_PERIOD_MS - loopElapsedMs)
    } else {
        // Yield to the Bluetooth stack without adding another fixed 50 ms.
        basic.pause(1)
    }
})
