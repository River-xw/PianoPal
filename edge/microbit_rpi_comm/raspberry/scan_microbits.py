import asyncio
from bleak import BleakScanner


def is_likely_microbit(name):
    if not name:
        return False

    lowered = name.lower()
    return 'micro:bit' in lowered or lowered.startswith('bbc micro')


async def main():
    print('Scanning for nearby BLE devices (6 seconds)...')
    microbits = []

    try:
        # Newer Bleak versions can return advertisement data (including RSSI).
        discovered = await BleakScanner.discover(timeout=6.0, return_adv=True)
        for _address, (device, adv_data) in discovered.items():
            name = device.name or ''
            address = (device.address or '').upper()

            if is_likely_microbit(name):
                rssi = getattr(adv_data, 'rssi', 'N/A')
                microbits.append((name, address, rssi))
    except TypeError:
        # Older Bleak versions: discover returns BLEDevice list only.
        devices = await BleakScanner.discover(timeout=6.0)
        for device in devices:
            name = device.name or ''
            address = (device.address or '').upper()

            if is_likely_microbit(name):
                rssi = getattr(device, 'rssi', 'N/A')
                microbits.append((name, address, rssi))

    print('')
    if not microbits:
        print('No micro:bit devices found.')
        print('Tips:')
        print('- Ensure micro:bit is powered on')
        print('- Ensure BLE is enabled on the micro:bit program')
        print('- Move the micro:bit closer to the Raspberry Pi')
        return

    print('Discovered micro:bit devices:')
    for idx, (name, address, rssi) in enumerate(microbits, start=1):
        print(f'{idx}. Name: {name}')
        print(f'   Address: {address}')
        print(f'   RSSI: {rssi}')


if __name__ == '__main__':
    asyncio.run(main())
