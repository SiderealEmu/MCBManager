# MCBManager

A desktop application for managing Minecraft Bedrock Dedicated Server addons. Provides a GUI for importing, enabling, disabling, and deleting behavior and resource packs.

## Features

- Import addons from `.mcaddon`, `.mcpack`, and `.zip` files
- Enable/disable behavior and resource packs per world
- Bulk operations for managing multiple addons
- Server status monitoring
- Version compatibility checking
- Search and filter installed addons

## Requirements

- Minecraft Bedrock Dedicated Server installed locally
- **Note:** MCBManager is currently intended to run on the same machine as your Bedrock server. Remote server management is not supported yet.

### Download (Recommended)

Download the latest release for your platform from the [Releases](https://github.com/SiderealEmu/MCBManager/releases) page:

- **Windows:** `MCBManager-windows.exe`
- **macOS:** `MCBManager-macos`
- **Linux:** `MCBManager-linux`

Simply download and run the executable. No installation required.

#### Platform Notes

**Windows:** You may see a SmartScreen warning on first run. Click "More info" → "Run anyway".

**macOS:** You may need to allow the app in System Preferences → Security & Privacy. If you get a "damaged" error, run:
```bash
xattr -cr /path/to/MCBManager-macos
```

**Linux:** Make the file executable before running:
```bash
chmod +x MCBManager-linux
./MCBManager-linux
```

### From Source

Requires Python 3.8+ and Minecraft Bedrock Dedicated Server.

```bash
# Clone the repository
git clone https://github.com/SiderealEmu/MCBManager.git
cd MCBManager

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

## Getting Started

1. Launch MCBManager
2. On first run, a setup wizard will guide you through configuring the path to your Bedrock Dedicated Server
3. Start importing and managing your addons

## Configuration

Configuration is stored in `~/.minecraft_addon_manager/config.json`.

## Support

If you find MCBManager useful, consider supporting development:

[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/siderealemu)

## License

MIT
