"""
Base qcodes driver for Agilent/Keysight series PNAs
http://na.support.keysight.com/pna/help/latest/Programming/GP-IB_Command_Finder/SCPI_Command_Tree.htm
"""
import logging
from typing import Any

from qcodes import VisaInstrument, InstrumentChannel, ChannelList
from qcodes.utils.validators import Numbers, Enum, Union
from qcodes.instrument_drivers.Keysight.N52xx.channel import N52xxChannel
from qcodes.instrument_drivers.Keysight.N52xx.trace import N52xxTrace


logger = logging.getLogger()


class N52xxPort(InstrumentChannel):
    """
    Allow operations on individual N52xx ports.
    """

    def __init__(
            self,
            parent: 'N52xxBase',
            name: str,
            port: int,
            min_power: Union[int, float],
            max_power: Union[int, float]
    ) -> None:

        super().__init__(parent, name)

        self.port = int(port)
        if self.port not in range(1, 5):
            raise ValueError("Port must be between 1 and 4.")

        self.add_parameter(
            "source_power",
            label="power",
            unit="dBm",
            get_cmd=f"SOUR:POW{self.port}?",
            set_cmd=f"SOUR:POW{self.port} {{}}",
            get_parser=float,
            vals=Numbers(min_value=min_power, max_value=max_power)
        )


class N52xxWindow(InstrumentChannel):

    max_trace_count = 24

    def __init__(self, parent: 'N52xxBase', window: int):
        super().__init__(parent, f"window{window}")

        self._window = window
        self._trace_count = 0

        self.create()

    def create(self):
        self.parent.write(f"DISP:WINDow{self._window} ON")

    def delete(self):
        self.parent.write(f"DISP:WINDow{self._window} OFF")

    def add_trace(self, trace: N52xxTrace):
        """
        Add a trace to the window
        """
        trace_number = self._trace_count + 1

        if trace_number > self.max_trace_count:
            raise RuntimeError("Maximum number of traces in this window "
                               "exceeded")

        trace_name = trace.short_name
        self.parent.write(
            f"DISP:WIND{self._window}:TRAC{trace_number}:FEED '{trace_name}'")

        self._trace_count += 1

    def add_channel(self, channel: N52xxChannel):
        """
        Add all traces in the channel to the window
        """
        for trace in channel.trace.values():
            self.add_trace(trace)


class N52xxBase(VisaInstrument):
    """
    TODO: Proper docstring
    """

    min_freq: float = None
    max_freq: float = None
    min_power: float = None
    max_power: float = None
    port_count: int = None

    def __init__(self, name: str, address: str, **kwargs: Any) -> None:

        super().__init__(name, address, terminator='\n', **kwargs)
        self.active_channel: N52xxChannel = None

        self.add_parameter(
            "trigger_source",
            get_cmd="TRIG:SOUR?",
            set_cmd="TRIG:SOUR {}",
            vals=Enum("EXT", "IMM", "INT", "MAN"),
            set_parser=lambda value: "IMM" if value is "INT" else value
        )

        self.add_parameter(
            "display_arrangement",
            set_cmd="DISP:ARR {}",
            vals=Enum("TILE", "CASC", "OVER", "STAC", "SPL", "QUAD")
        )

        # Ports
        ports = ChannelList(self, "port", N52xxPort)
        for port_num in range(1, self.port_count + 1):
            port = N52xxPort(
                self, f"port{port_num}", port_num, self.min_power,
                self.max_power
            )

            ports.append(port)
            self.add_submodule(f"port{port_num}", port)

        ports.lock()
        self.add_submodule("port", ports)

        self._channels = []
        self._windows = []
        self.connect_message()

    def add_channel(self) ->N52xxChannel:
        """
        Channels contain traces. The analyzer can have up to 200 independent
        channels. Channel settings determine how the trace data is measured .
        All traces that are assigned to a channel share the same channel
        settings.
        """
        channel_count = len(self._channels)
        if channel_count >= 200:
            raise RuntimeError("Cannot add more than 200 channels")

        channel = N52xxChannel(
            self, channel=channel_count + 1)
        self._channels.append(channel)
        return channel

    def add_window(self) ->N52xxWindow:
        """
        Windows are used for viewing traces. In principle, the analyzer can
        show an UNLIMITED number of windows on the screen. However, in practice,
        The SCPI status register can track the status of up to 576 traces. Since
        each window can have a maximum of 24 traces, the maximum number of
        windows shall be 24
        """
        window_count = len(self._windows)
        if window_count >= 24:
            raise RuntimeError("Cannot add more than 24 windows")

        window = N52xxWindow(self, window_count + 1)
        self._windows.append(window)
        return window

    @property
    def channel(self) ->list:
        """
        Public interface for access to channels
        """
        return self._channels

    def delete_all_traces(self) ->None:
        """
        Delete all traces from the instrument.
        """
        self.write("CALC:PAR:DEL:ALL")

    def synchronize(self):
        self.ask("*OPC?")

    def reset_instrument(self):
        self.write("*RST")
        self.write("*CLS")
        # sane settings
        self.write('FORM REAL,32')
        self.write('FORM:BORD NORM')
        self.trigger_source("IMM")
