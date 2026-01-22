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
- v2.3.2 界面变回左右两列右列是日志，把设备数据下载配置模块里的内容作为和设备查询，用户管理并列的tab整合到工具面板里，新的工具面板做为左列
- v2.3.3 禁用设置修复，电子邮件的验证修补，格式把状态和日志放在数据下载的tab里
- v2.3.4 添加新功能：选择设备图片的key下载对应key的图片，在数据下载模块的下载选项里添加一个显示选择框名字叫“设备-key选择”，当用户选择设备后将会在“设备-key选择”按条显示设备id-key（假设用户选择了两个设备，每个设备有两个image_fields的key那么就会有4条数据），用户可以点击条目选择自己希望下载的设备对应的的image_fields的key的图片，这个选择将会把对应条目变成红色表示该条目已经被选择，当用户没有进行选择时默认选择全部（也就是说在设备选择界面提那家设备后将会在“设备-key选择”框里用红色显示条目但是当用户点击其中一个条目进行选择时所有的条目会变成黑色，然后被选择的条目会变成红色），当然下载选项里的选择下载内容类型的选项优先级要高于这个功能
- v2.4.5 添加新功能：通用可滚动容器
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
