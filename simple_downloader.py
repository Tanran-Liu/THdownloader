#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simple Device Data Downloader
Specific for Device ID: 2594 - Rong Large Cardamon Himalaya GIES Station （Nepal）
"""

import asyncio
import logging
import threading
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import ttk, messagebox, scrolledtext
from typing import List, Optional, Dict, Any
import sys
import os
import calendar

from download.async_downloader import AsyncDeviceDataDownloader, DownloadError


class ProgressWidget:
    """Download progress display widget"""

    def __init__(self, parent):
        self.parent = parent
        self.current_message = ""
        self.current_progress = 0.0

        # Create progress frame
        self.frame = ttk.LabelFrame(parent, text="Download Progress", padding="10")

        # Progress bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            self.frame,
            variable=self.progress_var,
            maximum=100,
            length=400
        )
        self.progress_bar.pack(fill=tk.X, pady=(0, 5))

        # Progress message
        self.message_var = tk.StringVar(value="Ready...")
        self.message_label = ttk.Label(self.frame, textvariable=self.message_var)
        self.message_label.pack(pady=(0, 5))

        # Cancel button
        self.cancel_btn = ttk.Button(
            self.frame,
            text="Cancel Download",
            state=tk.DISABLED
        )
        self.cancel_btn.pack()

    def update_progress(self, message: str, progress: float):
        """Update progress"""
        self.current_message = message
        self.current_progress = progress * 100

        self.progress_var.set(self.current_progress)
        self.message_var.set(f"{message} ({self.current_progress:.1f}%)")

    def enable_cancel_button(self, enabled: bool = True):
        """Enable or disable cancel button"""
        self.cancel_btn.config(state=tk.NORMAL if enabled else tk.DISABLED)

    def reset(self):
        """Reset progress display"""
        self.current_message = ""
        self.current_progress = 0.0
        self.progress_var.set(0)
        self.message_var.set("Ready...")
        self.enable_cancel_button(False)


class DateSelectionWidget:
    """Month selection widget"""

    def __init__(self, parent):
        self.parent = parent

        # Create date range frame
        self.frame = ttk.LabelFrame(parent, text="Month Selection", padding="10")

        # Month selection label
        ttk.Label(
            self.frame, 
            text="Select a month to download data (YYYY-MM):"
        ).pack(anchor=tk.W, pady=(0, 5))

        # Month input
        self.month_var = tk.StringVar(
            value=datetime.now().strftime("%Y-%m")
        )
        self.month_entry = ttk.Entry(self.frame, textvariable=self.month_var, width=10)
        self.month_entry.pack(fill=tk.X, pady=(0, 5))

        # Example label
        ttk.Label(
            self.frame,
            text="Example: 2025-08 for August 2025"
        ).pack(anchor=tk.W)

    def get_date_range(self) -> tuple[str, str]:
        """Get date range for the selected month"""
        month_str = self.month_var.get()
        
        try:
            year, month = map(int, month_str.split("-"))
            
            # First day of month
            start_date = datetime(year, month, 1, 0, 0, 0)
            
            # Last day of month
            _, last_day = calendar.monthrange(year, month)
            end_date = datetime(year, month, last_day, 23, 59, 59)
            
            return start_date.strftime("%Y-%m-%d %H:%M:%S"), end_date.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return "", ""

    def validate_month(self) -> bool:
        """Validate month format"""
        month_str = self.month_var.get()
        try:
            year, month = map(int, month_str.split("-"))
            
            # Check valid year and month
            if not (2000 <= year <= 2100 and 1 <= month <= 12):
                return False
                
            return True
        except ValueError:
            return False


class DownloadDirWidget:
    """Download directory selection widget"""

    def __init__(self, parent):
        self.parent = parent

        # Create download directory frame
        self.frame = ttk.LabelFrame(parent, text="Download Location", padding="10")

        # Directory input frame
        dir_frame = ttk.Frame(self.frame)
        dir_frame.pack(fill=tk.X, pady=(0, 5))

        self.dir_var = tk.StringVar(value="./tmp/")
        self.dir_entry = ttk.Entry(dir_frame, textvariable=self.dir_var)
        self.dir_entry.pack(fill=tk.X, expand=True)

        # Hint label
        self.hint_var = tk.StringVar(value="Default: ./tmp/")
        self.hint_label = ttk.Label(self.frame, textvariable=self.hint_var)
        self.hint_label.pack(anchor=tk.W)

    def get_download_dir(self) -> str:
        """Get download directory path"""
        return self.dir_var.get().strip() or "./tmp/"

    def validate_directory(self) -> bool:
        """Validate directory path"""
        dir_path = self.get_download_dir()
        try:
            path = Path(dir_path)
            path.mkdir(parents=True, exist_ok=True)
            self.hint_var.set("Directory is valid")
            self.hint_label.config(foreground="green")
            return True
        except Exception as e:
            self.hint_var.set(f"Invalid directory: {str(e)}")
            self.hint_label.config(foreground="red")
            return False


class LogWidget:
    """Log display widget"""

    def __init__(self, parent):
        self.parent = parent
        self.log_messages = []

        # Create log frame
        self.frame = ttk.LabelFrame(parent, text="Log Information", padding="10")

        # Log text area
        self.log_text = scrolledtext.ScrolledText(
            self.frame,
            height=12,
            width=60,
            state=tk.DISABLED,
            wrap=tk.WORD
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def add_log(self, message: str, level: str = "INFO"):
        """Add log message"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] [{level}] {message}\n"
        self.log_messages.append(formatted_message)

        # Update text area
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, formatted_message)

        # Keep only the last 100 logs
        if len(self.log_messages) > 100:
            self.log_messages = self.log_messages[-100:]
            self.log_text.delete(1.0, tk.END)
            self.log_text.insert(1.0, "".join(self.log_messages))

        self.log_text.config(state=tk.DISABLED)
        self.log_text.see(tk.END)


class DeviceInfoWidget:
    """Device information widget"""
    
    def __init__(self, parent):
        self.parent = parent
        
        # Create device info frame
        self.frame = ttk.LabelFrame(parent, text="Device Information", padding="10")
        
        # Device ID
        id_frame = ttk.Frame(self.frame)
        id_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(id_frame, text="Device ID:", width=12).pack(side=tk.LEFT)
        ttk.Label(id_frame, text="2594", font=("TkDefaultFont", 9, "bold")).pack(side=tk.LEFT)
        
        # Device Name
        name_frame = ttk.Frame(self.frame)
        name_frame.pack(fill=tk.X)
        
        ttk.Label(name_frame, text="Device Name:", width=12).pack(side=tk.LEFT)
        ttk.Label(
            name_frame, 
            text="Rong Large Cardamon Himalaya GIES Station （Nepal）",
            font=("TkDefaultFont", 9, "bold")
        ).pack(side=tk.LEFT)


class SimpleDownloaderApp:
    """Main application class"""

    def __init__(self):
        self.downloader = None
        self.current_worker = None
        self.download_dir = "./tmp/"
        self.download_thread = None
        self.is_downloading = False
        
        # Fixed device ID and content types
        self.DEVICE_ID = 2594
        self.DEVICE_NAME = "Rong Large Cardamon Himalaya GIES Station （Nepal）"
        self.CONTENT_TYPES = ["data", "image"]

        # Create main window
        self.root = tk.Tk()
        self.root.title("Device Data Downloader")
        self.root.geometry("900x600")
        self.root.minsize(800, 500)

        # Set encoding and font
        self.setup_fonts()

        self.setup_ui()
        self.setup_bindings()

        # Initialize downloader
        self.update_downloader()

    def setup_fonts(self):
        """Set fonts for UI"""
        # Set default font, prioritize fonts that support Unicode
        if sys.platform == "win32":
            default_font = ("Segoe UI", 9)
        elif sys.platform == "darwin":
            default_font = ("Helvetica Neue", 9)
        else:
            import tkinter.font as tkFont
            available_fonts = tkFont.families()
            system_fonts = ["DejaVu Sans", "Liberation Sans", "Noto Sans", "Ubuntu"]
            selected_font = "TkDefaultFont"

            for font in system_fonts:
                if font in available_fonts:
                    selected_font = font
                    break

            default_font = (selected_font, 9)

        # Configure ttk style
        style = ttk.Style()

        # Try to set theme
        try:
            if sys.platform == "win32":
                style.theme_use('vista')
            elif sys.platform == "darwin":
                style.theme_use('aqua')
            else:
                style.theme_use('clam')
        except:
            pass

        # Configure fonts
        style.configure(".", font=default_font)
        style.configure("TLabel", font=default_font)
        style.configure("TButton", font=default_font)
        style.configure("TCheckbutton", font=default_font)
        style.configure("TEntry", font=default_font)
        style.configure("TLabelFrame.Label", font=default_font)

        # Set accent button style
        style.configure("Accent.TButton", font=default_font)

        # Set root window default font
        self.root.option_add('*Font', default_font)

    def setup_ui(self):
        """Set up user interface"""
        # Create main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Create left and right columns
        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # Left side configuration area
        config_label = ttk.Label(
            left_frame, 
            text="Download Configuration", 
            font=("TkDefaultFont", 12, "bold")
        )
        config_label.pack(anchor=tk.W, pady=(0, 10))

        # Create configuration components container
        config_container = ttk.Frame(left_frame)
        config_container.pack(fill=tk.BOTH, expand=True)
        
        # Device information widget
        self.device_widget = DeviceInfoWidget(config_container)
        self.device_widget.frame.pack(fill=tk.X, pady=(0, 10))

        # Month selection widget
        self.date_widget = DateSelectionWidget(config_container)
        self.date_widget.frame.pack(fill=tk.X, pady=(0, 10))

        # Download directory widget
        self.dir_widget = DownloadDirWidget(config_container)
        self.dir_widget.frame.pack(fill=tk.X)

        # Button area
        button_frame = ttk.Frame(left_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))

        self.download_btn = ttk.Button(
            button_frame,
            text="Start Download",
            command=self.handle_download,
            style="Accent.TButton"
        )
        self.download_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.test_btn = ttk.Button(
            button_frame,
            text="Test Connection",
            command=self.handle_test_connections
        )
        self.test_btn.pack(side=tk.LEFT)

        # Right side status area
        status_label = ttk.Label(
            right_frame, 
            text="Status and Logs", 
            font=("TkDefaultFont", 12, "bold")
        )
        status_label.pack(anchor=tk.W, pady=(0, 10))

        self.progress_widget = ProgressWidget(right_frame)
        self.progress_widget.frame.pack(fill=tk.X, pady=(0, 10))

        self.log_widget = LogWidget(right_frame)
        self.log_widget.frame.pack(fill=tk.BOTH, expand=True)
    
    def setup_bindings(self):
        """Set keyboard bindings"""
        self.root.bind('<Control-d>', lambda e: self.handle_download())
        self.root.bind('<Control-t>', lambda e: self.handle_test_connections())
        self.root.bind('<Control-q>', lambda e: self.root.quit())

        # Set cancel button command
        self.progress_widget.cancel_btn.config(command=self.handle_cancel_download)

    def update_downloader(self):
        """Update downloader instance"""
        download_dir = self.dir_widget.get_download_dir()
        self.download_dir = download_dir

        try:
            self.downloader = AsyncDeviceDataDownloader(root_path=download_dir)
            self.log_widget.add_log(f"Downloader initialized successfully, directory: {download_dir}", "INFO")
        except Exception as e:
            self.log_widget.add_log(f"Initialization failed: {str(e)}", "ERROR")

    def handle_download(self):
        """Handle download request"""
        if not self.is_downloading:
            self.start_download()

    def handle_test_connections(self):
        """Handle connection test request"""
        if not self.is_downloading:
            self.test_connections()

    def handle_cancel_download(self):
        """Handle cancel download request"""
        if self.is_downloading and self.downloader:
            self.downloader.cancel()
            self.log_widget.add_log("Download task canceled", "WARNING")
            self.is_downloading = False
            self.progress_widget.enable_cancel_button(False)
            self.download_btn.config(state=tk.NORMAL)
    
    def test_connections(self):
        """Test database and OSS connections"""
        if not self.downloader:
            self.log_widget.add_log("Downloader not initialized", "ERROR")
            return

        self.log_widget.add_log("Testing connections...", "INFO")

        def test_worker():
            try:
                # Run async method in a new event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                results = loop.run_until_complete(self.downloader.test_connections())

                # Use after method to update UI in the main thread
                self.root.after(0, self.update_test_results, results)

            except Exception as e:
                self.root.after(0, lambda: self.log_widget.add_log(f"Connection test failed: {str(e)}", "ERROR"))
            finally:
                loop.close()

        # Run test in a new thread
        test_thread = threading.Thread(target=test_worker, daemon=True)
        test_thread.start()

    def update_test_results(self, results):
        """Update test results to UI"""
        if results["database"]:
            self.log_widget.add_log("✓ Database connection successful", "INFO")
        else:
            self.log_widget.add_log("✗ Database connection failed", "ERROR")

        if results["oss"]:
            self.log_widget.add_log("✓ OSS connection successful", "INFO")
        else:
            self.log_widget.add_log("✗ OSS connection failed", "ERROR")
    
    def start_download(self):
        """Start download task"""
        # Validate input
        if not self.date_widget.validate_month():
            messagebox.showerror("Invalid Month", "Please enter a valid month in YYYY-MM format.")
            self.log_widget.add_log("Invalid month format", "ERROR")
            return

        if not self.dir_widget.validate_directory():
            self.log_widget.add_log("Invalid download directory", "ERROR")
            return

        # Update downloader directory
        self.update_downloader()

        # Get date range for the selected month
        start_time, end_time = self.date_widget.get_date_range()
        
        self.log_widget.add_log(f"Starting download for device ID {self.DEVICE_ID} ({self.DEVICE_NAME})...", "INFO")
        self.log_widget.add_log(f"Time period: {start_time} to {end_time}", "INFO")
        self.log_widget.add_log(f"Download directory: {self.download_dir}", "INFO")

        # Set progress callback
        self.downloader.set_progress_callback(self.progress_widget.update_progress)

        # Set download state
        self.is_downloading = True
        self.download_btn.config(state=tk.DISABLED)
        self.progress_widget.enable_cancel_button(True)
        self.progress_widget.reset()

        # Start download thread
        self.download_thread = threading.Thread(
            target=self.download_worker,
            args=(start_time, end_time),
            daemon=True
        )
        self.download_thread.start()
    
    def download_worker(self, start_time, end_time):
        """Download worker thread"""
        try:
            # Run async download in a new event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Set default image rename format to YYYY-MM-DD HH:MM:SS
            # Using dash instead of colon to avoid Windows filename errors
            image_format = "%Y-%m-%d %H-%M-%S"
            self.log_widget.add_log(f"Using image naming format: {image_format}", "INFO")
            self.log_widget.add_log("Note: Special characters like ':' will be replaced with '-' in filenames", "INFO")

            results = loop.run_until_complete(
                self.downloader.download_device_data(
                    devices=[self.DEVICE_ID],
                    contents=self.CONTENT_TYPES,
                    start_at=start_time,
                    end_at=end_time,
                    is_zip=True,
                    thumbnail=False,
                    rename_images=True,
                    rename_format=image_format
                )
            )

            # Use after method to update UI in the main thread
            self.root.after(0, self.update_download_results, results)

        except DownloadError as e:
            self.root.after(0, lambda: self.log_widget.add_log(f"Download error: {str(e)}", "ERROR"))
        except Exception as e:
            self.root.after(0, lambda: self.log_widget.add_log(f"Unknown error: {str(e)}", "ERROR"))
        finally:
            loop.close()
            # Reset state in the main thread
            self.root.after(0, self.download_finished)

    def update_download_results(self, results):
        """Update download results to UI"""
        if results["success"]:
            self.log_widget.add_log("Download completed!", "INFO")

            if results["failed_devices"]:
                self.log_widget.add_log(f"Failed devices: {results['failed_devices']}", "WARNING")

            if results["download_path"]:
                self.log_widget.add_log(f"Download directory: {results['download_path']}", "INFO")

            if results["zip_path"]:
                self.log_widget.add_log(f"ZIP file: {results['zip_path']}", "INFO")
        else:
            self.log_widget.add_log("Download failed!", "ERROR")
            for error in results["errors"]:
                self.log_widget.add_log(error, "ERROR")

    def download_finished(self):
        """Clean up after download is complete"""
        self.is_downloading = False
        self.download_btn.config(state=tk.NORMAL)
        self.progress_widget.enable_cancel_button(False)

    def run(self):
        """Run application"""
        self.root.mainloop()


def main():
    """Main function"""
    # Configure system encoding
    import locale

    # Configure environment variables to support Unicode
    if sys.platform.startswith('linux'):
        try:
            locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
        except locale.Error:
            try:
                locale.setlocale(locale.LC_ALL, 'C.UTF-8')
            except locale.Error:
                pass
        os.environ['LANG'] = 'en_US.UTF-8'
        os.environ['LC_ALL'] = 'en_US.UTF-8'
        os.environ['PYTHONIOENCODING'] = 'utf-8'

    # Force set standard output encoding
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('download.log', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )

    # Start Tkinter GUI application
    try:
        app = SimpleDownloaderApp()
        app.run()
    except Exception as e:
        logging.error(f"Application startup failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
