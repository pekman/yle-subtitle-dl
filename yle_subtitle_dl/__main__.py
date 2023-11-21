import asyncio
import argparse
from datetime import datetime, timedelta
import logging
import sys

from .downloader import download_all_subtitles


def timeval(val: str) -> datetime:
    import dateparser
    import re

    t = dateparser.parse(val, settings=(
        # workaround for dateparser bug
        # https://github.com/scrapinghub/dateparser/issues/1125 which
        # messes up ISO 8601 date parsing when DATE_ORDER is set to
        # DMY
        {} if re.match(r"\A\s*\d\d\d\d-\d\d-\d\d[\sTt]", val, re.ASCII)
        else {"DATE_ORDER": "DMY"}
    ))
    if t is None:
        raise ValueError()
    if t.tzinfo is None:
        # if t has no timezone, set it to local timezone
        t = t.astimezone()
    return t


def durationval(val: str) -> timedelta:
    import re

    m = re.match(r"""
        \A \s*
        (?: (?: (\d+) : )? (\d+) : )?
        ( \d+ (?: [.,] \d* )? | [.,] \d+ )
        \s* \Z
    """, val, re.VERBOSE | re.ASCII | re.IGNORECASE)
    if m:
        if m[1] is None and m[2] is not None:
            # hh:mm
            return timedelta(
                hours=int(m[2]),
                minutes=int(m[3].replace(",", ".")))
        else:
            # hh:mm:ss or ss (no ":")
            return timedelta(
                hours=int(m[1] or 0),
                minutes=int(m[2] or 0),
                seconds=float(m[3].replace(",", ".")))

    part_re = re.compile(r"""
        \s*
        (?P<num> \d+ (?: [.,] \d* )? | [.,] \d+ ) \s*
        # in Finnish, English, and Swedish
        (?: (?P<hours> tuntia? | hours? | timm(?:e|ar) | t | hr | h )
        |   (?P<minutes> minuuttia? | minutes? | minut(?:er)? | min | m )
        |   (?P<seconds> sekuntia? | seconds? | sekund(?:er)? | se[kc] | s )
        ) \s*
        (?: \s ja | \s and | \s och | [,;+] )? \s*
        | .  # error
    """, re.VERBOSE | re.ASCII | re.IGNORECASE)

    t = timedelta()
    for m in part_re.finditer(val):
        unit = m.lastgroup
        if unit is None:
            raise ValueError()
        num = float(m["num"].replace(",", "."))
        t += timedelta(**{unit: num})

    if t < timedelta():
        raise ValueError("negative duration not allowed")
    return t


def main():
    parser = argparse.ArgumentParser(
        description="Download subtitles from Yle live stream",
        epilog="""
            Note: It's possible to set start time to some hours in the
            past and download subtitles from that time. Old subtitles
            remain in the server for some time.
        """)

    parser.add_argument(
        "url",
        help="Stream URL (output of 'yle-dl --showurl')")
    parser.add_argument(
        "output_basename",
        help="""
            Base for output filenames; may contain a path but should
            not have an extension. Subtitles are saved with names like
            'output_basename-fi.vtt'
        """)

    parser.add_argument('-v', '--verbose', action="count", default=0)

    time_group = parser.add_argument_group(
        "time options",
        description="""
            Time values can be given in human-readable form.
            For start and end time, see
            <https://dateparser.readthedocs.io/>.
            Duration can be given in any of the following forms:
            "hh:mm:ss[.sss]", "hh:mm", "ss[.sss]", or something like
            "1h 2m 3s" or "1 hour 2 minutes 3 seconds". This works in
            Finnish, English, and Swedish.
        """)

    time_group.add_argument(
        "--start-time", "-s",
        type=timeval,
        default="now",
        help="""
            No subtitles older than this will be downloaded. This is
            also the zero point of saved subtitle time values.
            (default = now)
        """)

    endtime_group = time_group.add_mutually_exclusive_group()
    endtime_group.add_argument("--end-time", "-e", type=timeval)
    endtime_group.add_argument("--duration", "-d", type=durationval)

    args = parser.parse_args()

    if args.verbose == 1:
        logging.basicConfig(level=logging.INFO)
    elif args.verbose >= 2:
        logging.basicConfig(level=logging.DEBUG)

    if args.duration is not None:
        args.end_time = args.start_time + args.duration
    elif args.end_time is not None:
        args.duration = args.end_time - args.start_time

    print("Downloading subtitles from the following time period:")
    print("  start:", args.start_time)
    print("  end:  ", args.end_time or "until stopped")
    print("  duration:", args.duration or "until stopped")
    print()

    try:
        asyncio.run(download_all_subtitles(
            args.url, args.output_basename,
            args.start_time, args.end_time,
        ))
    except KeyboardInterrupt:
        pass

    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
