import aiohttp
import asyncio
from datetime import datetime, timedelta
import ipaddress
import logging
import random
import re
from urllib.parse import urljoin
from typing import Optional

from .vttmerge import WebVTTMerge


logger = logging.getLogger("yle_subtitle_dl")


SUBINFO_TO_SUFFIX = {
    # (LANGUAGE, CHARACTERISTICS): filename suffix
    ("fin", ""): "fi",
    ("fin", "public.accessibility.transcribes-spoken-dialog"): "fih",
    ("swe", ""): "sv",
    ("swe", "public.accessibility.transcribes-spoken-dialog"): "svh",
    ("smi", ""): "se",
    ("smi", "public.accessibility.transcribes-spoken-dialog"): "seh",
    ("eng", ""): "en",
    ("eng", "public.accessibility.transcribes-spoken-dialog"): "enh",
}


_m3u8_attr_uri_re = re.compile(r"""
   \A \#EXT-X- [^:]+ :
   (?: (?: "[^"]*" | [^"] )+ , )?
   URI=" ([^"]+) "
""", re.VERBOSE | re.ASCII)

_m3u8_subtitle_re = re.compile(r"""
    \A \#EXT-X-MEDIA:
    (?: (?: (?P<is_sub> TYPE=SUBTITLES )
        |   NAME=" (?P<name> [^\"]* ) "
        |   LANGUAGE=" (?P<language> [^\"]* ) "
        |   URI=" (?P<url> [^\"]* ) "
        |   CHARACTERISTICS=" (?P<characteristics> [^\"]* ) "
        |   (?: "[^\"]*" | [^\",] )+
        ) (?: , | \s*? \Z )
    )* \Z
""", re.VERBOSE | re.ASCII)


# borrowed from yle-dl {

def random_elisa_ipv4():
    return str(random_ip(ipaddress.ip_network('91.152.0.0/13')))


def random_ip(ip_network):
    # Convert to an int range, because sampling from a range is efficient
    ip_range_start = ip_network.network_address + 1
    ip_range_end = ip_network.broadcast_address - 1
    int_ip_range = range(int(ip_range_start), int(ip_range_end) + 1)
    return ipaddress.ip_address(random.choice(int_ip_range))

# }


async def download_all_subtitles(
        hls_master_playlist_url: str,
        output_filename_base: str,
        start_time: datetime,
        end_time: Optional[datetime],
) -> None:
    async with aiohttp.ClientSession(
            raise_for_status=True,
            headers={
                "User-Agent": "yle-subtitle-dl",
                "X-Forwarded-For": random_elisa_ipv4(),
            },
    ) as session:
        logger.debug(f"Loading master manifest from {hls_master_playlist_url}")
        async with session.get(hls_master_playlist_url) as resp:
            master_playlist = await resp.text(encoding="utf-8")

        subtitles = []  # list of subtitle info dicts
        for line in master_playlist.splitlines(keepends=False):
            # if this is a subtitle, add it to the list
            m = _m3u8_subtitle_re.match(line)
            if m and all(m.group("is_sub", "name", "language", "url")):
                subinfo = m.groupdict()
                # make url absolute
                subinfo["url"] = urljoin(
                    hls_master_playlist_url, subinfo["url"])
                subtitles.append(subinfo)
                logger.debug("Subtitle found:"
                             f" name={m['name']!r},"
                             f" language={m['language']!r},"
                             f" url={m['url']!r}")

        downloaders = [
            download_subtitles(
                session,
                subinfo,
                output_filename_base,
                start_time, end_time)
            for subinfo in subtitles
        ]
        await asyncio.gather(*downloaders)


_media_playlist_re = re.compile(r"""
    (?: \#EXT  # tag
        (?: -X-TARGETDURATION: [ \t]* (?P<targetduration> \d+ )
        |   -X-MEDIA-SEQUENCE: [ \t]* (?P<media_sequence> \d+ )
        |   -X-PROGRAM-DATE-TIME: [ \t]* (?P<program_date_time> \S+ )
        |   INF: [ \t]* (?P<extinf> [\d\.]+ )
        |   -X-ENDLIST \b (?P<endlist>)
        |   (?P<unknown_tag>)
        )
    |   \# (?P<comment>)
    |   [ \t]* (?= \r\n | \r | \n | \Z ) (?P<empty_line>)
    |   (?P<url> \S+ )
    |   (?P<error> [^\r\n]* )
    ) [^\r\n]*? (?: \r\n | \r | \n | \Z )
""", re.VERBOSE | re.ASCII)


async def download_subtitles(
        session: aiohttp.ClientSession,
        subinfo: dict[str, str],
        output_filename_base: str,
        start_time: datetime,
        end_time: Optional[datetime],
) -> None:
    loop = asyncio.get_running_loop()

    output_filename = (
        output_filename_base + "-" +
        SUBINFO_TO_SUFFIX.get(
            (subinfo["language"], subinfo["characteristics"] or ""),
            "unknown") +
        ".vtt")

    targetduration = 0.0
    vttfile_start_time = start_time
    vttfile_duration = 0.0
    next_media_sequence_to_dl = 0

    with WebVTTMerge(output_filename, start_time) as vttwriter:
        while True:
            # (re)load playlist
            logger.info(f"(Re)loading subtitle manifest {subinfo['name']!r}")
            logger.debug(subinfo["url"])
            last_reload = loop.time()
            async with session.get(subinfo["url"]) as resp:
                media_playlist = await resp.text(encoding="utf-8")

            media_sequence = 0
            has_new_segments = False

            # parse playlist
            for m in _media_playlist_re.finditer(media_playlist):
                kind: str = m.lastgroup  # type: ignore
                val = m[kind]

                if kind == "targetduration":
                    targetduration = float(val)

                elif kind == "media_sequence":
                    media_sequence = int(val)

                elif kind == "program_date_time":
                    try:
                        vttfile_start_time = datetime.fromisoformat(
                            # datetime.fromisoformat doesn't like "Z"
                            # as timezone before python 3.11
                            val[:-1] + "+00:00"
                            if val.endswith("Z") or val.endswith("z")
                            else val
                        )
                    except ValueError:
                        logger.warning("Unrecognized time value in "
                                       "media manifest of "
                                       f"{subinfo['name']!r}: {val!r}")
                    else:
                        if next_media_sequence_to_dl == 0:
                            logger.info("Earliest time available in "
                                        "manifest of "
                                        f"{subinfo['name']!r}: {val}")

                    if end_time is not None and vttfile_start_time >= end_time:
                        logger.debug("End time reached for "
                                     f"{subinfo['name']!r}. Stopping.")
                        return

                elif kind == "extinf":
                    vttfile_duration = float(val)

                elif kind == "url":
                    vttfile_end_time = (
                        vttfile_start_time +
                        timedelta(seconds=vttfile_duration))
                    vtt_log_label = (
                        f"{subinfo['name']!r}: {vttfile_start_time} "
                        f"{vttfile_duration:+}s")

                    if media_sequence >= next_media_sequence_to_dl:
                        next_media_sequence_to_dl = media_sequence + 1
                        has_new_segments = True

                        if vttfile_end_time > start_time:
                            # download new subtitle segment and
                            # convert and write it
                            logger.info("Loading subtitle segment "
                                        f"{vtt_log_label}")
                            logger.debug(val)
                            abs_vtt_url = urljoin(subinfo["url"], val)
                            async with session.get(abs_vtt_url) as resp:
                                vttdata = await resp.text(encoding="utf-8-sig")

                            vttwriter.convert_and_write(
                                vttdata,
                                start_time,
                                vtt_log_label)

                            if (end_time is not None and
                                    vttfile_end_time >= end_time):
                                logger.debug("End time reached for "
                                             f"{subinfo['name']!r}. "
                                             "Stopping.")
                                return

                    elif vttfile_end_time > start_time:
                        logger.debug("Skipping already downloaded "
                                     f"subtitle segment {vtt_log_label}")

                    media_sequence += 1

                elif kind == "endlist":
                    logger.debug("End marker in media manifest of "
                                 f"{subinfo['name']!r}. Stopping.")
                    return

                elif kind == "error":
                    logger.warning("error parsing subtitle manifest "
                                   f"of {subinfo['name']!r}")
                    logger.debug(f"manifest line: {val!r}")

            # set minimum reload interval according to RFC 8216
            if has_new_segments:
                # playlist changed or downloaded for the first time
                min_reload_interval = targetduration
            else:
                # playlist not changed (or at least hasn't grown)
                min_reload_interval = targetduration / 2

            # wait before playlist reload as instructed in RFC 8216
            time_elapsed = loop.time() - last_reload
            await asyncio.sleep(
                max(0, min_reload_interval - time_elapsed))
