"""
Python mock driver for AutomationDirect Productivity Series PLCs.

Uses local storage instead of remote communications.

Distributed under the GNU General Public License v2
"""
from collections import defaultdict
from dataclasses import dataclass
from unittest.mock import MagicMock

try:
    from pymodbus.pdu.bit_message import (  # type: ignore[import-not-found]
        ReadCoilsResponse,  # type: ignore[reportAssignmentType]
        WriteMultipleCoilsResponse,  # type: ignore[reportAssignmentType]
        WriteSingleCoilResponse,  # type: ignore[reportAssignmentType]
    )
    from pymodbus.pdu.register_message import (  # type: ignore[import-not-found]
        ReadHoldingRegistersResponse,  # type: ignore[reportAssignmentType]
        WriteMultipleRegistersResponse,  # type: ignore[reportAssignmentType]
        WriteSingleRegisterResponse,  # type: ignore[reportAssignmentType]
    )
except ImportError:
    @dataclass
    class ReadDiscreteInputsResponse:  # type: ignore[no-redef] # noqa: D101
        bits: list[bool]
    @dataclass
    class ReadCoilsResponse:  # type: ignore[no-redef] # noqa: D101
        bits: list[bool]
    class WriteMultipleCoilsResponse(MagicMock): ...  # type: ignore[no-redef] # noqa: D101
    class WriteSingleCoilResponse(MagicMock):  # type: ignore[no-redef] # noqa: D101
        def isError(self): return False  # noqa: D102
    @dataclass
    class ReadHoldingRegistersResponse:  # type: ignore[no-redef] # noqa: D101
        registers: list[int]
    class WriteMultipleRegistersResponse(MagicMock):  # type: ignore[no-redef] # noqa: D101
        def isError(self): return False  # noqa: D102
    class WriteSingleRegisterResponse(MagicMock): ...  # type: ignore[no-redef] # noqa: D101

from productivity.driver import ProductivityPLC as realProductivityPLC


class AsyncClientMock(MagicMock):
    """Magic mock that works with async methods."""

    async def __call__(self, *args, **kwargs):
        """Convert regular mocks into into an async coroutine."""
        return super().__call__(*args, **kwargs)


class ProductivityPLC(realProductivityPLC):
    """Mock Productivity driver using local storage instead of remote communication."""

    def __init__(self, address: str, tag_filepath, timeout: float = 1, *args, **kwargs):
        self.discontinuous_discrete_output = False
        self.tags = self._load_tags(tag_filepath)
        self.addresses = self._calculate_addresses(self.tags)
        self.map = {data['address']['start']: tag for tag, data in self.tags.items()}
        self.client = AsyncClientMock()
        self._coils: defaultdict[int, bool] = defaultdict(bool)
        self._discrete_inputs: defaultdict[int, bool] = defaultdict(bool)
        self._registers: defaultdict[int, bytes] = defaultdict(bytes)
        self._register_types = ['holding', 'input']
        self._detect_pymodbus_version()
        if self.pymodbus33plus:
            self.client.close = lambda: None

    async def _request(self, method, *args, **kwargs):
        if method == 'read_coils':
            address, count = args
            return ReadCoilsResponse(bits=[self._coils[address + i] for i in range(count)])
        if method == 'read_discrete_inputs':
            address, count = args
            return ReadDiscreteInputsResponse(bits=[self._discrete_inputs[address + i]
                                                for i in range(count)])
        elif method == 'read_holding_registers':
            address, count = args
            return ReadHoldingRegistersResponse(registers=[int.from_bytes(self._registers[address + i], byteorder='big')
                                                 for i in range(count)])
        elif method == 'write_coil':
            address, data = args
            self._coils[address] = data
            return WriteSingleCoilResponse(address, data)
        elif method == 'write_coils':
            address, data = args
            for i, d in enumerate(data):
                self._coils[address + i] = d
            return WriteMultipleCoilsResponse(address, len(data))
        elif method == 'write_register':
            address, data = args
            self._registers[address] = data.to_bytes(2, byteorder='big')
            return WriteSingleRegisterResponse(address, data)
        elif method == 'write_registers':
            address, data = args
            for i, d in enumerate(data):
                self._registers[address + i] = d.to_bytes(2, byteorder='big')
            return WriteMultipleRegistersResponse(address, len(data))
        return NotImplementedError(f'Unrecognised method: {method}')
