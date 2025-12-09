"""Base functionality for modbus communication.

Distributed under the GNU General Public License v2
"""
import asyncio

import pymodbus.exceptions
from pymodbus.client import AsyncModbusTcpClient

TYPE_START = {
    'discrete_output': 0,
    'discrete_input': 100000,
    'input': 300000,
    'holding': 400000,
}

DATA_TYPES = {
    'AIF32': 'float',  # Analog Input Float 32-bit
    'F32': 'float',    # Float 32-bit
    'AIS32': 'int32',  # Analog Input Signed integer 32-bit
    'AOS32': 'int32',  # Analog Output Signed integer 32-bit
    'S16': 'int16',    # Signed integer 16-bit
    'S32': 'int32',    # Signed integer 32-bit
    'C': 'bool',       # (C) Boolean
    'DI': 'bool',      # Discrete Input
    'DO': 'bool',      # Discrete Output
    'SBR': 'bool',     # System Boolean Read-only
    'SBRW': 'bool',    # System Boolean Read-Write
    'MST': 'bool',     # Module STatus bit
    'STR': 'str',      # STRing
    'SSTR': 'str',     # System STRing
    'SWR': 'int16',    # System Word Read-only
    'SWRW': 'int16'    # System Word Read-Write
}


class AsyncioModbusClient:
    """A generic asyncio client.

    This expands upon the pymodbus AsyncModbusTcpClient by
    including standard timeouts, async context manager, and queued requests.
    """

    def __init__(self, address: str, timeout: float = 1):
        """Set up communication parameters."""
        self.ip = address
        self.timeout = timeout
        self._register_types = ['holding', 'input']
        self._detect_pymodbus_version()
        self.client = AsyncModbusTcpClient(address, timeout=timeout)
        self.lock = asyncio.Lock()
        self.connectTask = asyncio.create_task(self._connect())

    async def __aenter__(self):
        """Asynchronously connect with the context manager."""
        return self

    async def __aexit__(self, *args):
        """Provide exit to the context manager."""
        await self._close()

    def _detect_pymodbus_version(self) -> None:
        """Detect various pymodbus versions."""
        self.pymodbus30plus = int(pymodbus.__version__[0]) == 3
        self.pymodbus32plus = self.pymodbus30plus and int(pymodbus.__version__[2]) >= 2
        self.pymodbus33plus = self.pymodbus30plus and int(pymodbus.__version__[2]) >= 3
        self.pymodbus35plus = self.pymodbus30plus and int(pymodbus.__version__[2]) >= 5

    async def _connect(self):
        """Start asynchronous reconnect loop."""
        try:
            await asyncio.wait_for(self.client.connect(), timeout=self.timeout)
        except Exception as e:
            raise OSError(f"Could not connect to '{self.ip}'.") from e

    async def read_coils(self, address, count):
        """Read modbus output coils (0 address prefix)."""
        return await self._request('read_coils', address, count)

    async def read_discrete_inputs(self, address, count):
        """Read modbus discrete inputs (1 address prefix)."""
        return await self._request('read_discrete_inputs', address, count)

    async def read_registers(self, address, count, type='holding', max_count=125):
        """Read modbus registers.

        The Modbus protocol doesn't allow responses longer than 250 bytes
        (ie. 125 registers, 62 DF addresses), which this function manages by
        chunking larger requests.
        """
        if max_count > 125:
            raise ValueError("Maximum of 125 registers can be read in one request.")
        if type not in self._register_types:
            raise ValueError(f"Register type {type} not in {self._register_types}.")
        registers = []
        while count > max_count:
            # if the last address read will be in the middle of a 32-bit tag
            # read one less address to avoid bad replies
            # https://github.com/numat/productivity/issues/38
            last_address = self.map.get(TYPE_START[type] + address + max_count, None)  # type: ignore
            offset = -1 if (last_address
                            and self.tags[last_address]['type'] in ['int32', 'float']) else 0  # type: ignore
            r = await self._request(f'read_{type}_registers', address, max_count + offset)
            address, count = address + (max_count + offset), count - (max_count + offset)
            registers += r.registers
        r = await self._request(f'read_{type}_registers', address, count)
        registers += r.registers
        return registers

    async def write_coil(self, address, value):
        """Write modbus coils."""
        return await self._request('write_coil', address, value)

    async def write_coils(self, address, values):
        """Write modbus coils."""
        return await self._request('write_coils', address, values)

    async def write_register(self, address, value):
        """Write a modbus register."""
        return await self._request('write_register', address, value)

    async def write_registers(self, address, values):
        """Write modbus registers.

        The Modbus protocol doesn't allow requests longer than 250 bytes
        (ie. 125 registers, 62 DF addresses), which this function manages by
        chunking larger requests.
        """
        responses = []
        while len(values) > 62:
            responses.append(await self._request('write_registers', address, values))
            address, values = address + 124, values[62:]
        responses.append(await self._request('write_registers', address, values))
        return responses

    async def _request(self, method, *args, **kwargs):
        """Send a request to the device and awaits a response.

        This mainly ensures that requests are sent serially, as the Modbus
        protocol does not allow simultaneous requests (it'll ignore any
        request sent while it's processing something). The driver handles this
        by assuming there is only one client instance. If other clients
        exist, other logic will have to be added to either prevent or manage
        race conditions.
        """
        await self.connectTask  # ensure the _connect Task triggered from _init is complete
        async with self.lock:
            try:
                if self.pymodbus32plus:
                    future = getattr(self.client, method)
                else:
                    future = getattr(self.client.protocol, method)  # type: ignore
                return await future(*args, **kwargs)
            except (asyncio.TimeoutError, pymodbus.exceptions.ConnectionException) as e:
                raise TimeoutError("Not connected to PLC.") from e

    async def _close(self) -> None:
        """Close the TCP connection."""
        if self.pymodbus33plus:
            self.client.close()  # 3.3.x
        else:
            await self.client.close()  # type: ignore  # 3.0.x - 3.2.x
