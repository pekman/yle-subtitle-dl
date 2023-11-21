import unittest
from unittest.mock import Mock, AsyncMock, patch

from datetime import datetime, time, timedelta, timezone

from yle_subtitle_dl.downloader import download_subtitles


MOCK_VTT_HEADER = """\
WEBVTT
"""

MOCK_VTT_CUE_TMPL = """\

{0} --> {1}
text ({0})
"""

# [vtt segment time, [(start time, end time), ...], ...]
# Segment times are seconds after midnight. Start and end times are
# seconds after segment time.
MOCK_VTT_TIMES = [
    [600, [
        (1, 2),
        (5, 6),
    ]],
    [610, [
        (2, 3),
        (6, 7),
    ]],
    [620, [
        (3, 4),
        (7, 8),
    ]],
]

# [(start time, end time), ...] seconds after midnight
MOCK_VTT_MERGEDTIMES = [
    tuple(
        base + t
        for t in start_stop
    )
    for base, timings in MOCK_VTT_TIMES
    for start_stop in timings
]

# start 1 sec before second subtitle
MOCK_START_TIME = datetime(2024, 1, 1, 0, 10, 4, tzinfo=timezone.utc)

# seconds after MOCK_START_TIME, i.e. correct result of merging segments
MOCK_VTT_MERGED_ADJUSTED_TIMES = [
    tuple(
        t - (600 + 4)
        for t in start_stop
    )
    # skip 1st subtitle, which is before MOCK_START_TIME
    for start_stop in MOCK_VTT_MERGEDTIMES[1:]
]

MOCK_PLAYLIST_HEADER = """\
#EXTM3U
#EXT-X-TARGETDURATION:10
#EXT-X-VERSION:3
"""

MOCK_PLAYLIST_ITEM = """\
#EXT-X-PROGRAM-DATE-TIME:{0}Z
#EXTINF:10
x-invalid-url://{0}
"""

MOCK_PLAYLIST = (
    MOCK_PLAYLIST_HEADER +
    "".join(
        MOCK_PLAYLIST_ITEM.format(
            (
                datetime.combine(MOCK_START_TIME.date(), time()) +
                timedelta(seconds=t)
            ).isoformat(timespec="milliseconds"))
        for t, _ in MOCK_VTT_TIMES
    ) +
    "#EXT-X-ENDLIST\n"
)


def mock_vtt_segment(basetime, cue_times):
    dummy_dt = datetime(2020, 1, 1, 0, 0, 0)
    return MOCK_VTT_HEADER + "".join(
        MOCK_VTT_CUE_TMPL.format(
            (dummy_dt+timedelta(seconds=t1)).time().isoformat("milliseconds"),
            (dummy_dt+timedelta(seconds=t2)).time().isoformat("milliseconds"),
        )
        for t1, t2 in cue_times
    )


MOCK_VTTS = [
    mock_vtt_segment(basetime, cue_times)
    for basetime, cue_times in MOCK_VTT_TIMES
]


def get_vtt_cue_times(vttline):
    def time2timedelta(t):
        return timedelta(
            seconds=t.second + 60*(t.minute + 60*t.hour),
            microseconds=t.microsecond,
        )

    start, _, end = vttline.partition(" --> ")
    t1 = time2timedelta(time.fromisoformat(start)).total_seconds()
    t2 = time2timedelta(time.fromisoformat(end)).total_seconds()
    return t1, t2


def mock_session():
    session = Mock()
    session.__aenter__ = AsyncMock(return_value=session)
    downloader = AsyncMock()
    session.get = Mock(return_value=downloader)
    downloader.__aenter__ = AsyncMock(return_value=downloader)
    downloader.text = AsyncMock(side_effect=[
        MOCK_PLAYLIST,
        *MOCK_VTTS,
    ])
    return session


class TestVttDownloadAndMerge(unittest.IsolatedAsyncioTestCase):

    @patch("yle_subtitle_dl.downloader.asyncio.sleep")
    @patch("yle_subtitle_dl.vttmerge.open")
    @patch("yle_subtitle_dl.vttmerge.WebVTTMerge._writeln")
    async def asyncSetUp(
            self,
            mock_writeln, mock_open, mock_sleep,
    ):
        await download_subtitles(
            session=mock_session(),
            subinfo=dict(
                name="testsubs",
                language="fin",
                url="x-invalid-url://",
                characteristics=None,
            ),
            output_filename_base=(
                "/dev/null/impossible-filename-that-raises-OSError"
                "-if-open-somehow-not-properly-mocked"),
            start_time=MOCK_START_TIME,
            end_time=None,
        )

        self.mock_writeln = mock_writeln
        self.mock_sleep = mock_sleep

    def test_downloading_with_no_need_to_reload(self):
        """No unnecessary media manifest reloads"""
        self.mock_sleep.assert_not_called()

    def test_vttmerge_skip_before_starttime(self):
        """
        Subtitles must be included and excluded correctly.

        Subtitles before start time must be skipped and all subtitles
        after it included.
        """

        cue_timing_lines = [
            kall.args[0]
            for kall in self.mock_writeln.mock_calls
            if "-->" in kall.args[0]
        ]
        self.assertEqual(
            len(cue_timing_lines), len(MOCK_VTT_MERGED_ADJUSTED_TIMES),
            "subtitle count should be correct")

    def test_vttmerge_timing_adjustment(self):
        """
        Subtitle timing must be properly adjusted when merging segments.
        """

        cue_times = [
            get_vtt_cue_times(kall.args[0])
            for kall in self.mock_writeln.mock_calls
            if "-->" in kall.args[0]
        ]
        for (t1, t2), (correct_t1, correct_t2) in zip(
                cue_times,
                MOCK_VTT_MERGED_ADJUSTED_TIMES,
        ):
            delta = 0.001  # allow ±1ms rounding error
            self.assertAlmostEqual(
                t1, correct_t1,
                delta=delta,
                msg="cue start times should be properly adjusted")
            self.assertAlmostEqual(
                t2, correct_t2,
                delta=delta,
                msg="cue end times should be properly adjusted")
