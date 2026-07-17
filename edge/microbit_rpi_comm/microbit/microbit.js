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
    } else if (msg == "START LEFT") {
        if (connected) {
            running = true
            hand = "left"
            startTime = input.runningTime()
            bluetooth.uartWriteString("STARTED LEFT\n")
            basic.showIcon(IconNames.Happy)
        }
    } else if (msg == "START RIGHT") {
        if (connected) {
            running = true
            hand = "right"
            startTime = input.runningTime()
            bluetooth.uartWriteString("STARTED RIGHT\n")
            basic.showIcon(IconNames.Happy)
        }
    } else if (msg == "STOP") {
        running = false
        bluetooth.uartWriteString("STOPPED\n")
        basic.showIcon(IconNames.No)
    }
})

let az = 0
let ay = 0
let ax = 0
let t = 0
let startTime = 0
let running = false
let connected = false
let msg = ""
let hand = ""

hand = "left"

bluetooth.startUartService()
basic.showIcon(IconNames.Yes)

basic.forever(function () {
    if (!(connected)) {
        basic.showIcon(IconNames.No)
        basic.pause(500)
        return
    }

    if (!(running)) {
        basic.pause(20)
        return
    }

    t = input.runningTime() - startTime
    ax = input.acceleration(Dimension.X)
    ay = input.acceleration(Dimension.Y)
    az = input.acceleration(Dimension.Z)

    bluetooth.uartWriteString(
        "DATA," +
        hand + "," +
        t + "," +
        ax + "," +
        ay + "," +
        az + "\n"
    )

    basic.pause(20)
})