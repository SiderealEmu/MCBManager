# MCBManager

A desktop application for managing Minecraft Bedrock Dedicated Server addons. Provides a GUI for importing, enabling, disabling, and deleting behavior and resource packs.

## Features

- Import addons from `.mcaddon`, `.mcpack`, and `.zip` files
- Enable/disable behavior and resource packs per world
- Bulk operations for managing multiple addons
- Server status monitoring
- Version compatibility checking (NOT IMPLEMENTED)
- Search and filter installed addons

## Requirements

- Python 3.8+
- Minecraft Bedrock Dedicated Server

## Installation

```bash
# Clone the repository
git clone https://github.com/SiderealEmu/MCBManager.git
cd MCBManager

# Install dependencies
pip install -r requirements.txt
```

## Usage

```bash
python main.py
```

On first launch, a setup wizard will guide you through configuring the path to your Bedrock Dedicated Server.

## Configuration

Configuration is stored in `~/.minecraft_addon_manager/config.json`.

## License

MIT
