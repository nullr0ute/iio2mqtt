# SPDX-License-Identifier: MIT
#
# Copyright (C) 2026, Peter Robinson

#!/usr/bin/env python3
"""
A small service to read sensor data from IIO sensor devices and publish to MQTT
"""

import sys
import time
import signal
import logging
import argparse
from datetime import datetime
from typing import Dict, List, Optional
import iio
import tomli
import tomli_w

logger = logging.getLogger('iio2mqtt')


class IIOSensorReader:
    """Reads data from IIO sensor devices using pylibiio"""

    def __init__(self, context: iio.Context, device_id: str):
        self.context = context
        self.device_id = device_id
        self.device = None
        self._initialize_device()

    def _initialize_device(self):
        """Initialize the IIO device"""
        try:
            self.device = self.context.find_device(self.device_id)
            if not self.device:
                raise ValueError(f"Device {self.device_id} not found")
            logger.info(f"Initialized device: {self.device.name or self.device.id}")
        except Exception as e:
            logger.error(f"Failed to initialize device {self.device_id}: {e}")
            raise

    def get_available_channels(self) -> List[str]:
        """Get list of available sensor channels"""
        if not self.device:
            return []

        channels = []
        for channel in self.device.channels:
            if channel.scan_element:
                channels.append(channel.id)
        return channels

    def enable_channels(self, channel_ids: List[str] = None):
        """Enable specified channels for reading"""
        if not self.device:
            return

        for channel in self.device.channels:
            if channel.scan_element:
                if channel_ids is None or channel.id in channel_ids:
                    channel.enabled = True
                else:
                    channel.enabled = False

    def read_channels(self) -> List[Dict]:
        """Read data from all enabled channels"""
        if not self.device:
            return []

        readings = []

        try:
            # Create a buffer for reading
            buffer = iio.Buffer(self.device, 1)
            buffer.refill()

            timestamp = datetime.now().isoformat()

            # Read each enabled channel
            for channel in self.device.channels:
                if channel.enabled and channel.scan_element:
                    try:
                        # Read the channel data
                        data = channel.read(buffer)

                        # Get scale attribute if available
                        scale = 1.0
                        if channel.attrs.get('scale'):
                            scale = float(channel.attrs['scale'].value)

                        # Get offset attribute if available
                        offset = 0.0
                        if channel.attrs.get('offset'):
                            offset = float(channel.attrs['offset'].value)

                        # Calculate actual value
                        actual_value = (data + offset) * scale

                        reading = {
                            'device': self.device.name or self.device.id,
                            'channel': channel.id,
                            'raw': data,
                            'scale': scale,
                            'offset': offset,
                            'value': actual_value,
                            'timestamp': timestamp
                        }
                        readings.append(reading)

                    except Exception as e:
                        logger.error(f"Error reading channel {channel.id}: {e}")

        except Exception as e:
            logger.error(f"Error reading device {self.device_id}: {e}")

        return readings


class iio2mqtt:
    """Main class for monitoring IIO sensors"""

    def __init__(self, config_path: str = '/etc/iio2mqtt.toml', log_file: str = None):
        self.config_path = config_path
        self.log_file_override = log_file
        self.config = {}
        self.running = False
        self.context = None
        self.readers = {}

    def setup_logging(self):
        """Configure logging with the appropriate log file"""
        # Determine which log file to use (command line takes precedence)
        if self.log_file_override:
            log_file = self.log_file_override
        else:
            log_file = self.config.get('log_file', '/var/log/iio2mqtt.log')

        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ],
            force=True  # Reconfigure if already configured
        )
        logger.info(f"Logging to: {log_file}")

    def load_config(self):
        """Load configuration from TOML file"""
        try:
            with open(self.config_path, 'rb') as f:
                self.config = tomli.load(f)
            logger.info(f"Configuration loaded from {self.config_path}")
            return True
        except FileNotFoundError:
            logger.error(f"Config file not found: {self.config_path}")
            self._create_default_config()
            return False
        except tomli.TOMLDecodeError as e:
            logger.error(f"Invalid TOML in config file: {e}")
            return False

    def _create_default_config(self):
        """Create a default configuration file"""
        default_config = {
            "interval_seconds": 5,
            "log_file": "/var/log/iio2mqtt.log",
            "output_file": "/var/log/iio2mqtt.log",
            "devices": [
                "iio:device0"
            ],
            "channels": ["all"]
        }

        try:
            with open(self.config_path, 'wb') as f:
                tomli_w.dump(default_config, f)
            logger.info(f"Created default config at {self.config_path}")
        except Exception as e:
            logger.error(f"Could not create default config: {e}")

    def initialize_context(self):
        """Initialize local IIO context"""
        try:
            self.context = iio.Context()

            logger.info(f"IIO context initialized: {self.context.name}")
            logger.info(f"Available devices: {[dev.id for dev in self.context.devices]}")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize IIO context: {e}")
            return False

    def initialize_readers(self):
        """Initialize sensor readers for configured devices"""
        devices = self.config.get('devices', [])
        configured_channels = self.config.get('channels', ['all'])

        for device_id in devices:
            try:
                reader = IIOSensorReader(self.context, device_id)

                # Get available channels
                available_channels = reader.get_available_channels()

                if not available_channels:
                    logger.warning(f"No channels found for {device_id}")
                    continue

                # Determine which channels to enable
                if 'all' in configured_channels:
                    channels_to_enable = None  # Enable all
                else:
                    channels_to_enable = [ch for ch in configured_channels 
                                         if ch in available_channels]

                # Enable the channels
                reader.enable_channels(channels_to_enable)

                self.readers[device_id] = reader
                logger.info(f"Initialized reader for {device_id} with channels: {available_channels}")

            except Exception as e:
                logger.error(f"Failed to initialize reader for {device_id}: {e}")

    def read_sensors(self):
        """Read data from all configured sensors"""
        data = []

        for device_id, reader in self.readers.items():
            readings = reader.read_channels()
            data.extend(readings)

        return data

    def log_data(self, data: List[Dict]):
        """Log sensor data to output file"""
        output_file = self.config.get('output_file', '/var/log/iio_sensor_data.log')

        try:
            with open(output_file, 'a') as f:
                for reading in data:
                    f.write(json.dumps(reading) + '\n')
        except Exception as e:
            logger.error(f"Failed to write data: {e}")

    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False

    def cleanup(self):
        """Clean up resources"""
        self.readers.clear()
        if self.context:
            del self.context
            self.context = None

    def run(self):
        """Main daemon loop"""
        # Load configuration first
        if not self.load_config():
            logger.error("Failed to load configuration, exiting")
            return 1

        # Set up logging (after config is loaded)
        self.setup_logging()

        # Set up signal handlers
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)

        # Initialize IIO context
        if not self.initialize_context():
            logger.error("Failed to initialize IIO context, exiting")
            return 1

        # Initialize sensor readers
        self.initialize_readers()

        if not self.readers:
            logger.error("No sensor readers initialized, exiting")
            self.cleanup()
            return 1

        # Get interval from config
        interval = self.config.get('interval_seconds', 5)
        logger.info(f"Starting daemon with {interval}s interval")

        self.running = True

        # Main loop
        try:
            while self.running:
                try:
                    # Read sensor data
                    data = self.read_sensors()

                    # Log data
                    if data:
                        self.log_data(data)
                        logger.debug(f"Logged {len(data)} sensor readings")

                    # Sleep for configured interval
                    time.sleep(interval)

                except Exception as e:
                    logger.error(f"Error in main loop: {e}")
                    time.sleep(1)  # Brief pause before retrying

        finally:
            self.cleanup()

        logger.info("Daemon stopped")
        return 0


def main():
    """Entry point"""
    parser = argparse.ArgumentParser(
        description='IIO to MQTT Daemon',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
  %(prog)s -c /path/to/config.toml
  %(prog)s -l /var/log/custom_daemon.log
  %(prog)s -c /path/to/config.toml -l /var/log/custom_daemon.log
        """
    )

    parser.add_argument(
        '-c', '--config',
        default='/etc/iio2mqtt.toml',
        help='Path to configuration file (default: /etc/iio2mqtt.toml)'
    )

    parser.add_argument(
        '-l', '--log-file',
        help='Path to daemon log file (overrides config file setting)'
    )

    args = parser.parse_args()

    # Create and run daemon
    daemon = iio2mqtt(args.config, args.log_file)
    return daemon.run()


if __name__ == '__main__':
    sys.exit(main())
