````markdown
# Device Data Downloader

A GUI tool for downloading device data from IoT sensors.

## Features

- Asynchronous data and image downloads
- Support for customizable date ranges
- Excel export for sensor data
- Image downloading with rename options
- ZIP packaging option

## Versions

### Standard Version
The standard version allows downloading data from multiple devices with customizable options.

```bash
python main.py
```

### Simple Version (Tashigang Specific)
A simplified version specifically for downloading data from the Tashigang Quinoa GIES Station (Bhutan).
This version only allows downloading one month of data at a time from device ID 2594.

```bash
python simple_downloader.py
```

## Building Executables

To build the standard version:
```bash
python build_app.py
```

To build the simplified version:
```bash
python build_simple_app.py
```

## Requirements

- Python 3.12+
- Dependencies managed via `pyproject.toml`
- tkinter (included with standard Python installation)

Install dependencies with your preferred PEP 517 tool (e.g. `uv`, `pip`, or `pipx`). With pip:

```bash
pip install -e .
```

## Configuration

This project now loads all sensitive settings from environment variables (using `python-dotenv`). To configure the app:

1. Copy `.env.example` to `.env` in the project root.
2. Fill in the required MySQL and OSS credentials.
3. (Optional) Override the `DB_*` values if they differ from the `MYSQL_*` ones.

The `.env` file is ignored by git so credentials stay local.

## Project Structure

- `main.py` - Main entry point for standard version
- `simple_downloader.py` - Main entry point for simplified version
- `tui_app.py` - Standard GUI implementation
- `download/async_downloader.py` - Core async download functionality
- `download/db.py` - Database connection utilities
- `config/config.py` - Configuration settings
