"""USB hardware interface for Proxmark and other serial devices."""

import asyncio
import glob
import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)


class HardwareManager:
    """Manages USB hardware connections, primarily Proxmark devices."""

    def __init__(self) -> None:
        self._serial_conn: Any = None
        self._device_path: str | None = None
        self._lock = asyncio.Lock()

    async def list_usb_devices(self) -> list[dict[str, str]]:
        """List available USB serial devices (cross-platform)."""
        devices: list[dict[str, str]] = []

        if sys.platform == "win32":
            # Windows: Check COM ports
            devices.extend(self._list_windows_com_ports())
        else:
            # Linux/macOS: Check /dev/tty* patterns
            patterns = [
                "/dev/ttyACM*",   # Proxmark3, Arduino
                "/dev/ttyUSB*",   # USB-Serial adapters
                "/dev/ttyS*",     # Built-in serial ports
            ]

            for pattern in patterns:
                for path in glob.glob(pattern):
                    device_type = "unknown"
                    if "ACM" in path:
                        device_type = "CDC ACM (Proxmark3/Arduino)"
                    elif "USB" in path:
                        device_type = "USB-Serial adapter"
                    elif "ttyS" in path:
                        device_type = "Built-in serial"

                    devices.append({
                        "path": path,
                        "type": device_type,
                        "accessible": os.access(path, os.R_OK | os.W_OK),
                    })

            # Also check for Proxmark specifically via lsusb-style detection
            try:
                proc = await asyncio.create_subprocess_exec(
                    "lsusb",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                usb_list = stdout.decode()
                for line in usb_list.splitlines():
                    if any(kw in line.lower() for kw in ["proxmark", "9ac4", "2d2d"]):
                        devices.append({
                            "path": line.strip(),
                            "type": "Proxmark3 (USB)",
                            "accessible": True,
                        })
            except FileNotFoundError:
                pass  # lsusb not available

        return devices

    def _list_windows_com_ports(self) -> list[dict[str, str]]:
        """List COM ports on Windows."""
        devices: list[dict[str, str]] = []

        # Try pyserial's list_ports (best method)
        try:
            from serial.tools import list_ports
            for port in list_ports.comports():
                device_type = "Serial device"
                desc_lower = (port.description or "").lower()
                if any(kw in desc_lower for kw in ["proxmark", "acm", "arduino"]):
                    device_type = "CDC ACM (Proxmark3/Arduino)"
                elif "usb" in desc_lower:
                    device_type = "USB-Serial adapter"

                devices.append({
                    "path": port.device,
                    "type": device_type,
                    "description": port.description or "",
                    "accessible": True,
                })
            return devices
        except ImportError:
            pass

        # Fallback: scan COM1-COM20
        for i in range(1, 21):
            port = f"COM{i}"
            try:
                import serial
                s = serial.Serial(port)
                s.close()
                devices.append({
                    "path": port,
                    "type": "Serial device",
                    "accessible": True,
                })
            except (ImportError, OSError):
                continue

        return devices

    async def connect_proxmark(self, device_path: str | None = None) -> dict[str, Any]:
        """Connect to a Proxmark device."""
        if device_path is None:
            # Auto-detect
            devices = await self.list_usb_devices()
            pm_devices = [d for d in devices if "ACM" in d.get("type", "") or "COM" in d.get("path", "")]
            if not pm_devices:
                return {"success": False, "error": "No Proxmark device found. Connect device and try again."}
            device_path = pm_devices[0]["path"]

        try:
            import serial
            async with self._lock:
                self._serial_conn = serial.Serial(
                    device_path,
                    baudrate=115200,
                    timeout=2,
                )
                self._device_path = device_path
                logger.info("Connected to Proxmark at %s", device_path)
                return {"success": True, "device": device_path}
        except ImportError:
            return {
                "success": False,
                "error": "pyserial not installed. Run: pip install pyserial",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def proxmark_command(self, command: str) -> dict[str, Any]:
        """Execute a Proxmark3 client command.

        Uses the pm3 CLI tool if available, falls back to direct serial.
        """
        # Try using pm3 CLI first (more reliable)
        try:
            proc = await asyncio.create_subprocess_exec(
                "pm3",
                "-c",
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=30.0
            )
            return {
                "success": proc.returncode == 0,
                "output": stdout.decode(),
                "error": stderr.decode() if proc.returncode != 0 else "",
            }
        except FileNotFoundError:
            pass  # pm3 CLI not installed
        except asyncio.TimeoutError:
            return {"success": False, "error": "Command timed out"}

        # Fall back to direct serial
        if not self._serial_conn:
            devices = await self.list_usb_devices()
            pm_devices = [d for d in devices if "ACM" in d.get("type", "") or "COM" in d.get("path", "")]
            if pm_devices:
                result = await self.connect_proxmark(pm_devices[0]["path"])
                if not result["success"]:
                    return result

        if not self._serial_conn:
            return {
                "success": False,
                "error": "No Proxmark connection. Install pm3 CLI or connect device.",
            }

        try:
            async with self._lock:
                self._serial_conn.write(f"{command}\n".encode())
                await asyncio.sleep(0.5)
                output = ""
                while self._serial_conn.in_waiting:
                    output += self._serial_conn.read(self._serial_conn.in_waiting).decode(
                        errors="replace"
                    )
                    await asyncio.sleep(0.1)
                return {"success": True, "output": output}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def execute_system_command(self, command: str) -> dict[str, Any]:
        """Execute a system shell command (with safety checks)."""
        # Block dangerous commands
        blocked = ["rm -rf /", "mkfs", "dd if=", ":(){", "fork bomb",
                   "format c:", "del /s /q", "rd /s /q c:\\"]
        cmd_lower = command.lower()
        for b in blocked:
            if b in cmd_lower:
                return {"success": False, "error": f"Blocked dangerous command: {command}"}

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=60.0
            )
            return {
                "success": proc.returncode == 0,
                "output": stdout.decode(errors="replace"),
                "error": stderr.decode(errors="replace") if proc.returncode != 0 else "",
                "return_code": proc.returncode,
            }
        except asyncio.TimeoutError:
            return {"success": False, "error": "Command timed out (60s)"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def disconnect(self) -> None:
        """Disconnect from the current device."""
        if self._serial_conn:
            try:
                self._serial_conn.close()
            except Exception:
                pass
            self._serial_conn = None
            self._device_path = None
