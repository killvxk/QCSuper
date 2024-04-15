#!/usr/bin/python3
#-*- encoding: Utf-8 -*-

from logging import DEBUG, INFO, basicConfig, error, info, debug, warning
from argparse import RawTextHelpFormatter
from argparse import ArgumentParser
from os.path import expanduser
from pathlib import Path
from sys import stderr

from .modules.json_geo_dump import JsonGeoDumper
from .modules.memory_dump import MemoryDumper
from .modules.cli import CommandLineInterface
from .modules.dlf_dump import DlfDumper
from .modules.info import InfoRetriever
from .modules._utils import FileType

from .inputs.json_geo_read import JsonGeoReader
from .inputs.usb_modem_pyserial import UsbModemPyserialConnector
from .inputs.usb_modem_pyusb import UsbModemPyusbConnector
from .inputs.usb_modem_pyusb_devfinder import PyusbDevInterface, PyusbDevNotFoundReason
from .inputs.usb_modem_argparser import UsbModemArgParser, UsbModemArgType
from .inputs.dlf_read import DlfReader
from .inputs.adb import AdbConnector
from .inputs.adb_wsl2 import AdbWsl2Connector

def main():

    parser = ArgumentParser(
        description = 'A tool for communicating with the Qualcomm DIAG protocol (also called QCDM or DM).',
        formatter_class = RawTextHelpFormatter
    )

    parser.add_argument('--cli', action = 'store_true', help = 'Use a command prompt, allowing for interactive completion of commands.')
    parser.add_argument('--efs-shell', action = 'store_true', help = 'Spawn an interactive shell to navigate within the embedded filesystem (EFS) of the baseband device.')
    parser.add_argument('-v', '--verbose', action = 'store_true', help = 'Add output for each received or sent Diag packet.')

    input_mode = parser.add_argument_group(title = 'Input mode', description = 'Choose an one least input mode for DIAG data.')

    input_mode = input_mode.add_mutually_exclusive_group(required = True)

    input_mode.add_argument('--adb', action = 'store_true', help = 'Use a rooted Android phone with USB debugging enabled as input (requires adb).')
    input_mode.add_argument('--adb-wsl2', action = 'store', default=None, help = 'Unix path to the Windows adb executable. Equivalent of --adb command but with WSL2/Windows interoperability.')
    input_mode.add_argument('--usb-modem', metavar = 'TTY_DEV', help = 'Use an USB modem exposing a DIAG pseudo-serial port through USB.\n' +
        'Possible syntaxes:\n' +
        '  - "auto": Use the first device interface in the system found where the\n' +
        '    following criteria is matched, by order of preference:\n' +
        '    - bInterfaceClass=255/bInterfaceSubClass=255/bInterfaceProtocol=48/bNumEndpoints=2\n' +
        '    - bInterfaceClass=255/bInterfaceSubClass=255/bInterfaceProtocol=255/bNumEndpoints=2\n' +
        '  - usbserial or hso device name (Linux/macOS): "/dev/tty{USB,HS,other}{0-9}"\n' +
        '  - COM port identifier (Windows): "COM{0-9}"\n' +
        '  - "vid:pid[:cfg:intf]" (vendor ID/product ID/optional bConfigurationValue/optional\n' +
        '    bInterfaceNumber) format in hexa: e.g. "05c6:9091" or "05c6:9091:1:0 (vid and pid\n' +
        '    are four zero-padded hex digits, cfg and intf are canonical values from the USB\n' +
        '    descriptor, or guessed using the criteria specified for "auto" above if not specified)\n' +
        '  - "bus:addr[:cfg:intf]" (USB bus/device address/optional bConfigurationValue/optional\n' +
        '    bInterfaceNumber) format in decimal: e.g "001:003" or "001:003:0:3" (bus and addr are\n' +
        '    three zero-padded digits, cfg and intf are canonical values from the USB descriptor)')
    input_mode.add_argument('--dlf-read', metavar = 'DLF_FILE', type = FileType('rb'), help = 'Read a DLF file generated by QCSuper or QXDM, enabling interoperability with vendor software.')
    input_mode.add_argument('--json-geo-read', metavar = 'JSON_FILE', type = FileType('r'), help = 'Read a JSON file generated using --json-geo-dump.')

    modules = parser.add_argument_group(title = 'Modules', description = 'Modules writing to a file will append when it already exists, and consider it Gzipped if their name contains ".gz".')

    modules.add_argument('--info', action = 'store_true', help = 'Read generic information about the baseband device.')
    modules.add_argument('--pcap-dump', metavar = 'PCAP_FILE', type = FileType('ab'), help = 'Generate a PCAP file containing GSMTAP frames for 2G/3G/4G, to be loaded using Wireshark.')
    modules.add_argument('--wireshark-live', action = 'store_true', help = 'Same as --pcap-dump, but directly spawn a Wireshark instance.')
    # modules.add_argument('--efs-dump', metavar = 'OUTPUT_DIR', help = 'Dump the internal EFS filesystem of the device.')
    modules.add_argument('--memory-dump', metavar = 'OUTPUT_DIR', help = 'Dump the memory of the device (may not or partially work with recent devices).')
    modules.add_argument('--dlf-dump', metavar = 'DLF_FILE', type = FileType('ab'), help = 'Generate a DLF file to be loaded using QCSuper or QXDM, with network protocols logging.')
    modules.add_argument('--json-geo-dump', metavar = 'JSON_FILE', type = FileType('a'), help = 'Generate a JSON file containing both raw log frames and GPS coordinates, for further reprocessing. ' +
        'To be used in combination with --adb.')
    modules.add_argument('--decoded-sibs-dump', action = 'store_true', help = 'Print decoded SIBs to stdout (experimental, requires pycrate).')

    pcap_options = parser.add_argument_group(title = 'PCAP generation options', description = 'To be used along with --pcap-dump or --wireshark-live.')

    pcap_options.add_argument('--reassemble-sibs', action = 'store_true', help = 'Include reassembled UMTS SIBs as supplementary frames, also embedded fragmented in RRC frames.')
    pcap_options.add_argument('--decrypt-nas', action = 'store_true', help = 'Include unencrypted LTE NAS as supplementary frames, also embedded ciphered in RRC frames.')
    pcap_options.add_argument('--include-ip-traffic', action = 'store_true', help = 'Include unframed IP traffic from the UE.')

    memory_options = parser.add_argument_group(title = 'Memory dumping options', description = 'To be used along with --memory-dump.')

    memory_options.add_argument('--start', metavar = 'MEMORY_START', default = '00000000', help = 'Offset at which to start to dump memory (hex number), by default 00000000.')
    memory_options.add_argument('--stop', metavar = 'MEMORY_STOP', default = 'ffffffff', help = 'Offset at which to stop to dump memory (hex number), by default ffffffff.')

    args = parser.parse_args()

    basicConfig(stream = stderr, level = DEBUG if args.verbose else INFO,
                format='[%(asctime)s | %(levelname)s @ %(filename)s:%(lineno)d ] %(message)s',
                force = True, datefmt = '%H:%M:%S')

    if args.dlf_read:
        diag_input = DlfReader(args.dlf_read)
    elif args.adb_wsl2:
        win_adb_path = Path(args.adb_wsl2).resolve()
        if not win_adb_path.is_file():
            error("--adb-wsl2 is not a valid path to Windows adb executable")
            exit()
        diag_input = AdbWsl2Connector(f'{win_adb_path}')
        if diag_input.usb_modem and not diag_input.usb_modem.not_found_reason:
            usb_modem : PyusbDevInterface = diag_input.usb_modem
            if usb_modem.chardev_if_mounted:
                diag_input = UsbModemPyserialConnector(usb_modem.chardev_if_mounted)
            else:
                diag_input = UsbModemPyusbConnector(usb_modem)
    elif args.adb:
        diag_input = AdbConnector()
        if diag_input.usb_modem and not diag_input.usb_modem.not_found_reason:
            usb_modem : PyusbDevInterface = diag_input.usb_modem
            if usb_modem.chardev_if_mounted:
                diag_input = UsbModemPyserialConnector(usb_modem.chardev_if_mounted)
            else:
                diag_input = UsbModemPyusbConnector(usb_modem)
    elif args.usb_modem:
        usb_arg = UsbModemArgParser(args.usb_modem)
        if not usb_arg.arg_type:
            error("You didn't pass a valid value for the --usb-modem " +
                    "argument. Please check digit padding (if any) and see " +
                    "--help for further details.")
            exit()
        elif usb_arg.arg_type == UsbModemArgType.pyserial_dev:
            diag_input = UsbModemPyserialConnector(usb_arg.pyserial_device)
        else:
            dev_intf = PyusbDevInterface.from_arg(usb_arg)
            if dev_intf.not_found_reason:
                error('No Qualcomm Diag interface was found with the specified ' +
                    'criteria. Please be more specific.')
                exit()
                # TODO: Print a more user-friendly message here?
            elif dev_intf.chardev_if_mounted:
                diag_input = UsbModemPyserialConnector(dev_intf.chardev_if_mounted)
            else:
                diag_input = UsbModemPyusbConnector(dev_intf)
        
    elif args.json_geo_read:
        diag_input = JsonGeoReader(args.json_geo_read)
    else:
        raise NotImplementedError

    """
        The classes implementing the modules are instancied below.
    """

    def parse_modules_args(args):

        if args.memory_dump:
            diag_input.add_module(MemoryDumper(diag_input, expanduser(args.memory_dump), int(args.start, 16), int(args.stop, 16)))
        if args.pcap_dump:
            from .modules.pcap_dump import PcapDumper
            diag_input.add_module(PcapDumper(diag_input, args.pcap_dump, args.reassemble_sibs, args.decrypt_nas, args.include_ip_traffic))
        if args.wireshark_live:
            from .modules.pcap_dump import WiresharkLive
            diag_input.add_module(WiresharkLive(diag_input, args.reassemble_sibs, args.decrypt_nas, args.include_ip_traffic))
        if args.json_geo_dump:
            diag_input.add_module(JsonGeoDumper(diag_input, args.json_geo_dump))
        if args.decoded_sibs_dump:
            from .modules.decoded_sibs_dump import DecodedSibsDumper
            diag_input.add_module(DecodedSibsDumper(diag_input))
        if args.info:
            diag_input.add_module(InfoRetriever(diag_input))
        if args.dlf_dump:
            diag_input.add_module(DlfDumper(diag_input, args.dlf_dump))

    # if args.efs_dump:
    #     raise NotImplementedError

    parse_modules_args(args)

    if args.cli:
        
        if diag_input.modules or args.efs_shell:
            error('You can not both specify the use of CLI and a module')
            exit()
        
        diag_input.add_module(CommandLineInterface(diag_input, parser, parse_modules_args))

    if args.efs_shell:
        
        if diag_input.modules:
            error('You can not both specify the use of EFS shell and a module')
            exit()
            
        from .modules.efs_shell import EfsShell
        diag_input.add_module(EfsShell(diag_input))
            


    if not diag_input.modules:
        
        parser.print_usage()
        
        error('You must specify either a module or --cli')
        exit()

    # Enter the main loop.

    try:
        diag_input.run()
    finally:
        diag_input.dispose()

    return 0