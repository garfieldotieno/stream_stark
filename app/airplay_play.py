import asyncio
from pyatv import scan, connect, pair
from pytube import YouTube

async def main():
    YOUTUBE_URL = input("Enter YouTube URL: ").strip()

    print("Scanning for Apple TV / AirPlay devices...")
    devices = await scan(loop, timeout=5)

    if not devices:
        print("No devices found.")
        return

    # Show devices
    for i, device in enumerate(devices, start=1):
        print(f"{i}. {device.name} ({device.identifier})")
    choice = int(input("\nSelect a device by number: ")) - 1
    selected_device = devices[choice]

    # Check AirPlay service
    airplay_service = selected_device.get_service("AirPlay")
    if not airplay_service:
        print("Selected device does not support AirPlay.")
        return

    # Pair if necessary
    if not airplay_service.credentials:
        print("\nPairing required...")
        pairing = await pair(selected_device, "AirPlay", loop)
        await pairing.begin()
        code = input("Enter the PIN displayed on screen: ")
        await pairing.finish(code)
        print("Pairing complete.")

    # Connect to device
    atv = await connect(selected_device, loop)
    try:
        # Extract direct stream from YouTube
        print(f"\nExtracting stream from {YOUTUBE_URL} ...")
        yt = YouTube(YOUTUBE_URL)
        stream = yt.streams.filter(progressive=True, file_extension="mp4").order_by("resolution").desc().first()
        if not stream:
            print("No MP4 stream found!")
            return
        video_url = stream.url
        print(f"Streaming URL: {video_url}")

        # Play video
        print(f"\nCasting video to {selected_device.name} ...")
        await atv.airplay.play_url(video_url)

    finally:
        atv.close()  # synchronous close

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
