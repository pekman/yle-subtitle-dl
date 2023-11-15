from datetime import datetime, timedelta
import logging
from pathlib import Path
import re
from typing import Optional


logger = logging.getLogger("yle_subtitle_dl")


class WebVTTMerge:
    """
    Merge WebVTT files with given start times.

    Times in each input file are assumed to start at 00:00:00.
    X-TIMESTAMP-MAP is ignored.
    """

    first_line_re = re.compile(r"\AWEBVTT(?: |\t|\Z)")

    timestamp_re = re.compile(r"""
        \A
        (?: (?P<hour> \d+ ) : )?
        (?P<min> \d+ ) : (?P<sec> \d+ )
        (?: \. (?P<ms> \d{0,3} ) \d* )?
        \Z
    """, re.VERBOSE | re.ASCII)
    _embedded_timestamp_re_str = r"(?:\d+:)?\d+:\d+(?:\.\d*)?"

    cue_timings_re = re.compile(fr"""
        \A (?P<start> {_embedded_timestamp_re_str} )
        \s* --> \s*
        (?P<end> {_embedded_timestamp_re_str} )
        (?P<settings> \s+ .*? )? \Z
    """, re.VERBOSE | re.ASCII)

    def __init__(self, output_filename: str, start_time: datetime):
        self.start_time = start_time

        self.is_first_file = True
        self.last_line_was_empty = False

        self.cur_file_log_label: Optional[str] = None

        try:
            self.output_file = open(output_filename, "x", encoding="utf-8")
        except FileExistsError as exc:
            orig = Path(output_filename)
            path = orig.parent
            base = orig.stem
            suffix = orig.suffix
            for i in range(1, 100):
                filename = path / f"{base}-{i}{suffix}"
                try:
                    self.output_file = filename.open("x", encoding="utf-8")
                    return
                except FileExistsError:
                    pass
            raise exc

    def close(self) -> None:
        self.output_file.close()

    def __enter__(self):
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def _warn(self, msg: str) -> None:
        logger.warning(f"WebVTT parser: {self.cur_file_log_label}: {msg}")

    def _writeln(self, line: str) -> None:
        print(line, file=self.output_file)
        self.last_line_was_empty = line == ""

    def _parse_timestamp(self, timestamp: str) -> int:
        """convert h:m:s string to milliseconds"""
        m = self.timestamp_re.match(timestamp)
        if m is None:
            self._warn("invalid timestamp")
            raise ValueError("invalid timestamp")
        return (
            int((m["ms"] or "0").ljust(3, "0")) + 1000*(
                int(m["sec"]) + 60*(
                    int(m["min"]) + 60*(
                        int(m["hour"] or 0)))))

    def convert_and_write(
            self,
            file_contents: str,
            file_start_time: datetime,
            file_log_label: str,
    ) -> None:
        self.cur_file_log_label = file_log_label
        file_localtime_offset = (
            (file_start_time - self.start_time) //
            timedelta(milliseconds=1))

        line_iter = iter(file_contents.splitlines(keepends=False))

        # Read header. For first file, copy everything but
        # X-TIMESTAMP-MAP line to output.

        # first line
        line = next(line_iter, None)
        if line is None or not self.first_line_re.match(line):
            self._warn("not a WebVTT file")
            return
        if self.is_first_file:
            self._writeln(line)

        # rest of header
        for line in line_iter:
            if line == "":
                break
            if self.is_first_file and not line.startswith("X-TIMESTAMP-MAP="):
                self._writeln(line)

        # if needed, print empty line to separate items from the last
        # item of previous file
        if not self.last_line_was_empty:
            self._writeln("")

        # non-header lines
        skip_until_nonempty = False
        for line in line_iter:
            if skip_until_nonempty:
                if line == "":
                    continue
                else:
                    skip_until_nonempty = False

            m = self.cue_timings_re.match(line)
            if m:
                try:
                    cue_start = (
                        self._parse_timestamp(m["start"]) +
                        file_localtime_offset)
                    cue_end = (
                        self._parse_timestamp(m["end"]) +
                        file_localtime_offset)
                except ValueError:
                    # if we can't parse the timestamps, assume that this isn't
                    # a cue timings line and leave it as is
                    pass
                else:
                    if cue_end < 0:
                        # skip subtitles before self.start_time
                        for cue_line in line_iter:
                            if cue_line == "":
                                break
                        skip_until_nonempty = True
                        continue
                    if cue_start < 0:
                        # Subtitle is being displayed at
                        # self.start_time. Set it to show right at the
                        # start.
                        cue_start = 0

                    # TODO: maybe also skip subtitles after given end time

                    s1, ms1 = divmod(cue_start, 1000)
                    m1, s1 = divmod(s1, 60)
                    h1, m1 = divmod(m1, 60)
                    s2, ms2 = divmod(cue_end, 1000)
                    m2, s2 = divmod(s2, 60)
                    h2, m2 = divmod(m2, 60)

                    line = (
                        f"{h1:02}:{m1:02}:{s1:02}.{ms1:03} --> "
                        f"{h2:02}:{m2:02}:{s2:02}.{ms2:03}"
                        f"{m['settings'] or ''}")

            self._writeln(line)

        self.is_first_file = False
