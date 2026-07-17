import asyncio
from bleak import BleakScanner

async def main():
    print("Scanning for 5 seconds...")
    devices = await BleakScanner.discover(timeout=5)

    for d in devices:
        print(f"Name: {d.name}")
        print(f"Address: {d.address}")
        print()

asyncio.run(main())