````markdown
# Device Data Downloader

A GUI tool for downloading device data from IoT sensors.

## Features

- Asynchronous data and image downloads
- Support for customizable date ranges
- Excel export for sensor data
- Image downloading with rename options
- ZIP packaging option

## Function Versions
- v1.0 
- v2.0 增加功能：设备选择可以按名称搜索，多选，输入过程中在下拉菜单中显示局部匹配的设备名，标红相同部分，防抖下拉菜单自适应
- v2.1 增加功能：设备选择可以按ID搜索，多选输入过程中在下拉菜单中显示id匹配的设备名
- v2.2.1 代码改进：添加通用下拉组件，提高复用性
- v2.2.2 添加功能：Excel列名使用原始Key（不映射）
- v2.2.3 添加功能：限制并行下载请求数量避免卡死
- v2.2.4 添加功能：致命错误识别
- v2.2.5 代码修复：用户手动中断下载进程
- v2.2.6 添加功能：日期输入格式化字符串设置默认字符串
- v2.2.7 添加功能：选择某个设备查询他最新的一条数据
- v2.3.1 添加用户增删改查功能（CRUD）1.对于users要实现改name，email，password，当然还要记录updated_at。2.对于users要实现通过name或者phone查找用户。3.对于users要实现添加用户，但是不允许删除用户。4.对于device_user要允许删除添加数据，实现a添加用户设备绑定，b更改用户设备绑定（通过删增实现），c删除用户设备绑定。设备的查询是通过用户查他绑定了几台设备。


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
