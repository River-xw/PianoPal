# micro:bit v2 ↔ Raspberry Pi 5 (BLE)

通过蓝牙同时连接两块 micro:bit v2，将手部传感器数据传到树莓派 Pi 5。当前提交的 MakeCode 示例读取 micro:bit 内置加速度计；`mpu6050.py` 保留为外接 MPU6050 的 MicroPython 实验驱动。

## 目录结构

```
edge/microbit_rpi_comm/
├── microbit/
│   ├── mpu6050.py        # MPU6050 驱动（与 main 一起烧录）
│   └── microbit.js       # MakeCode BLE UART 发送示例
└── raspberry/
    ├── requirements.txt
    ├── config.example.json
    └── ble_sensor_reader.py
```

## 硬件要求

- 2 × BBC micro:bit v2
- 2 × MPU6050 陀螺仪模块（或兼容的 6 轴 IMU，默认读取陀螺仪部分）
- 1 × Raspberry Pi 5（内置蓝牙）
-杜邦线 / breakout 板

### MPU6050 接线（每块 micro:bit）

| MPU6050 | micro:bit v2 |
|---------|--------------|
| VCC | 3V |
| GND | GND |
| SCL | Pin 19 |
| SDA | Pin 20 |

> micro:bit 内置加速度计仍可用，但本方案读取的是外接 MPU6050 的**陀螺仪角速度**（°/s）。

## micro:bit 端

1. 用 MakeCode 打开或导入 `microbit/microbit.js`
2. 按需要把 `START LEFT` 或 `START RIGHT` 指令发给对应手的 micro:bit
3. 上电后屏幕显示：
   - 启动：`L` 或 `R`
   - MPU6050 未检测到：😞（检查接线）
   - 等待蓝牙连接：`✗`
   - 连接成功：`✓`

若改用 MicroPython 和外接 MPU6050，可以继续基于 `mpu6050.py` 扩展烧录脚本。

## 树莓派 Pi 5 配置

> Raspberry Pi OS (Bookworm) 不允许直接用系统 `pip install`（会报 `externally-managed-environment`）。
> **必须先创建虚拟环境**，再在虚拟环境里安装依赖。

```bash
sudo systemctl enable bluetooth
sudo systemctl start bluetooth

cd edge/microbit_rpi_comm/raspberry

# 若提示 venv 模块不存在，先运行：
# sudo apt install python3-venv python3-full

python3 -m venv .venv
source .venv/bin/activate        # 激活后，提示符前会出现 (.venv)
pip install -r requirements.txt

# 之后每次使用前都要先激活虚拟环境：
# source .venv/bin/activate
```

## 使用步骤

### 1. 扫描两块 micro:bit 的 MAC 地址

两块板子上电并运行程序后：

```bash
python ble_sensor_reader.py --scan
```

若扫不到，先看能不能看到任何蓝牙设备：

```bash
python ble_sensor_reader.py --scan-all
```

若 `--scan-all` 也看不到设备，可临时关闭 Wi-Fi 再试（Pi 5 内置 Wi-Fi/蓝牙会互相干扰）：

```bash
sudo rfkill block wlan
python ble_sensor_reader.py --scan-all
sudo rfkill unblock wlan
```

### 2. 填写配置文件

```bash
cp config.example.json config.json
```

```json
{
  "devices": [
    {"name": "left",  "address": "AA:BB:CC:DD:EE:01"},
    {"name": "right", "address": "AA:BB:CC:DD:EE:02"}
  ]
}
```

### 3. 启动双设备连接

```bash
python ble_sensor_reader.py
```

预期输出：

```
[left] linked: AA:BB:CC:DD:EE:01
[left] connected
[left] tag=L gx=12 gy=-34 gz=5 dps
[right] linked: AA:BB:CC:DD:EE:02
[right] connected
[right] tag=R gx=0 gy=2 gz=-1 dps
```

## 通信协议

```
树莓派  --CONNECT-->  micro:bit
树莓派  <--READY---   micro:bit（屏幕显示 ✓）
树莓派  <--L:gx,gy,gz---  左手陀螺仪（约 10Hz，单位 °/s）
树莓派  <--R:gx,gy,gz---  右手陀螺仪（约 10Hz，单位 °/s）
```

BLE 使用 Nordic UART Service：

| 用途 | UUID |
|------|------|
| Service | `6e400001-b5a3-f393-e0a9-e50e24dcca9e` |
| 树莓派 → micro:bit (RX) | `6e400002-b5a3-f393-e0a9-e50e24dcca9e` |
| micro:bit → 树莓派 (TX) | `6e400003-b5a3-f393-e0a9-e50e24dcca9e` |

## 常见问题

| 问题 | 处理 |
|------|------|
| `externally-managed-environment` | 不要直接用系统 pip；先 `python3 -m venv .venv`，再 `source .venv/bin/activate`，然后 `pip install -r requirements.txt` |
| `No module named 'venv'` | 运行 `sudo apt install python3-venv python3-full` |
| micro:bit 显示 😞 | 检查 MPU6050 接线；确认模块为 3.3V 供电 |
| 扫描不到 micro:bit | 确认已烧录 `mpu6050.py` + `main_*.py`；板子显示 `L`/`R`；运行 `--scan-all`；靠近 Pi；临时 `sudo rfkill block wlan` |
| 只能连上一块 | 先 `--scan` 确认两个不同 MAC |
| 数据全为 0 | 转动 MPU6050 模块验证；检查 I2C 地址是否为 0x68 |
| 频繁断线 | 减少遮挡；脚本已内置 5 秒自动重连 |

## 与 score_to_reference 集成

树莓派可订阅左右手陀螺仪角速度，结合 `score_to_reference` 生成的 JSON 乐谱，用于检测手部旋转动作或演奏姿态。
