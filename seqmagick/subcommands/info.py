"""
Info action
"""

import collections
import csv
import multiprocessing
import sys

from functools import partial

from Bio import SeqIO

from seqmagick import fileformat

from . import common

def build_parser(parser):
    parser.add_argument('source_files', metavar='sequence_files', nargs='+')
    parser.add_argument('--input-format', help="""Input format. Overrides
            extension for all input files""")
    parser.add_argument('--out-file', dest='destination_file',
            type=common.FileType('wt'), default=sys.stdout,
            metavar='destination_file',
            help='Output destination. Default: STDOUT')
    parser.add_argument('--format', dest='output_format',
        choices=('tab', 'csv', 'align'), help="""Specify output format as
        tab-delimited, CSV or aligned in a borderless table.  Default is
        tab-delimited if the output is directed to a file, aligned if output to
        the console.""")
    parser.add_argument('--threads', default=1,
            type=int,
            help="""Number of threads (CPUs). [%(default)s] """)

class SeqInfoWriter(object):
    """
    Base writer for sequence files
    """

    def __init__(self, sequence_files, rows, output):
        self.sequence_files = sequence_files
        self.rows = rows
        self.output = output

    def write_row(self, row):
        raise NotImplementedError("Override in subclass")

    def write_header(self, header):
        self.write_row(header)

    def write(self):
        header = ('name', 'alignment', 'min_len', 'max_len', 'avg_len',
                  'num_seqs')

        self.write_header(header)

        for row in self.rows:
            self.write_row(_SeqFileInfo(*row))

class CsvSeqInfoWriter(SeqInfoWriter):
    delimiter = ','
    def __init__(self, sequence_files, rows, output):
        super(CsvSeqInfoWriter, self).__init__(sequence_files, rows, output)
        self.writer = csv.writer(self.output, delimiter=self.delimiter,
                lineterminator='\n')

    def write_row(self, row):
        # To cope with header
        if hasattr(row, '_replace'):
            row = row._replace(avg_len='{0:.2f}'.format(row.avg_len))
        self.writer.writerow(row)

class TsvSeqInfoWriter(CsvSeqInfoWriter):
    delimiter = '\t'

class AlignedSeqInfoWriter(SeqInfoWriter):
    def __init__(self, sequence_files, rows, output):
        super(AlignedSeqInfoWriter, self).__init__(sequence_files, rows, output)
        self.max_name_length = max(len(f) for f in self.sequence_files)

    def write_header(self, header):
        fmt = ('{0:' + str(self.max_name_length + 1) + 's}{1:10s}'
                '{2:>10s}{3:>10s}{4:>10s}{5:>10s}')
        print(fmt.format(*header), file=self.output)

    def write_row(self, row):
        fmt = ('{name:' + str(self.max_name_length + 1) + 's}{alignment:10s}'
                '{min_len:10d}{max_len:10d}{avg_len:10.2f}{num_seqs:10d}')
        print(fmt.format(**row._asdict()), file=self.output)

_WRITERS = {'csv': CsvSeqInfoWriter, 'tab': TsvSeqInfoWriter, 'align':
        AlignedSeqInfoWriter}

_HEADERS = ('name', 'alignment', 'min_len', 'max_len', 'avg_len',
              'num_seqs')
_SeqFileInfo = collections.namedtuple('SeqFileInfo', _HEADERS)

def summarize_sequence_file(source_file, file_type=None):
    """
    Summarizes a sequence file, returning a tuple containing the name,
    whether the file is an alignment, minimum sequence length, maximum
    sequence length, average length, number of sequences.
    """
    is_alignment = True
    avg_length = None
    min_length = sys.maxsize
    max_length = 0
    sequence_count = 0

    # Get an iterator and analyze the data.
    with common.FileType('rt')(source_file) as fp:
        if not file_type:
            file_type = fileformat.from_handle(fp)
        for record in SeqIO.parse(fp, file_type):
            sequence_count += 1
            sequence_length = len(record)
            if max_length != 0:
                # If even one sequence is not the same length as the others,
                # we don't consider this an alignment.
                if sequence_length != max_length:
                    is_alignment = False

            # Lengths
            if sequence_length > max_length:
                max_length = sequence_length
            if sequence_length < min_length:
                min_length = sequence_length

            # Average length
            if sequence_count == 1:
                avg_length = float(sequence_length)
            else:
                avg_length = avg_length + ((sequence_length - avg_length) /
                                           sequence_count)

    # Handle an empty file:
    if avg_length is None:
        min_length = max_length = avg_length = 0
    if sequence_count <= 1:
        is_alignment = False

    return (source_file, str(is_alignment).upper(), min_length,
            max_length, avg_length, sequence_count)

def action(arguments):
    """
    Given one more more sequence files, determine if the file is an alignment,
    the maximum sequence length and the total number of sequences.  Provides
    different output formats including tab (tab-delimited), csv and align
    (aligned as if part of a borderless table).
    """
    # Ignore SIGPIPE, for head support
    common.exit_on_sigpipe()
    common.exit_on_sigint()

    handle = arguments.destination_file
    output_format = arguments.output_format
    if not output_format:
        try:
            output_format = 'align' if handle.isatty() else 'tab'
        except AttributeError:
            output_format = 'tab'

    writer_cls = _WRITERS[output_format]

    ssf = partial(summarize_sequence_file, file_type = arguments.input_format)

    # if only one thread, do not use the multithreading so parent process
    # can be terminated using ctrl+c
    if arguments.threads > 1:
        pool = multiprocessing.Pool(processes=arguments.threads)
        summary = pool.imap(ssf, arguments.source_files)
    else:
        summary = (ssf(f) for f in arguments.source_files)

    with handle:
        writer = writer_cls(arguments.source_files, summary, handle)
        writer.write()

