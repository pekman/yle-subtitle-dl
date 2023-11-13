import unittest
from unittest.mock import Mock, AsyncMock, patch

import asyncio
from datetime import datetime, timezone

from yle_subtitle_dl.downloader import download_subtitles


MOCK_RESPONSE_HEADER = """\
#EXTM3U
#EXT-X-TARGETDURATION:60
#EXT-X-MEDIA-SEQUENCE:1234
"""

MOCK_RESPONSE_TMPL = """\
#EXT-X-PROGRAM-DATE-TIME:2011-11-11T11:{n:02d}:11.000Z
#EXTINF:60.000,
mock-{n}.vtt
"""

MOCK_RESPONSE_ENDLIST = MOCK_RESPONSE_HEADER + "#EXT-X-ENDLIST\n"


def mock_session(**kwargs):
    session = Mock()
    session.__aenter__ = AsyncMock(return_value=session)
    downloader = AsyncMock()
    session.get = Mock(return_value=downloader)
    downloader.__aenter__ = AsyncMock(return_value=downloader)
    downloader.text = AsyncMock(**kwargs)
    return session


def mock_response(num_segments):
    return MOCK_RESPONSE_HEADER + "".join(
        MOCK_RESPONSE_TMPL.format(n=i)
        for i in range(num_segments)
    )


@patch("yle_subtitle_dl.downloader.asyncio.sleep")
@patch("yle_subtitle_dl.downloader.WebVTTMerge")
class TestRfc8216TimingConformance(unittest.IsolatedAsyncioTestCase):

    async def _download_subtitles(self, num_segments_list):
        with patch.object(asyncio.get_running_loop(), "time") as mock_time:
            # act as if no time passes so that elapsed time
            # calculation doesn't subtract any time from the delay
            mock_time.return_value = 0

            await download_subtitles(
                session=mock_session(side_effect=[
                    *(mock_response(n) for n in num_segments_list),
                    MOCK_RESPONSE_ENDLIST,
                ]),
                subinfo=dict(
                    name="testsubs",
                    language="fin",
                    url="x-invalid-url://",
                    characteristics=None,
                ),
                output_filename_base=(
                    "/dev/null/impossible-filename-that-raises-OSError"
                    "-if-WebVTTMerge-somehow-not-properly-mocked"),
                start_time=datetime(2024, 1, 1, 11, 00, 11,
                                    tzinfo=timezone.utc),
                end_time=None,
            )

    async def test_timing_when_playlist_doesnt_change(
            self,
            mock_vttmerge, mock_sleep,
    ):
        """
        Reload interval must follow RFC 8216 when playlist hasn't changed.

        Reload interval must be no shorter than half of TARGETDURATION
        when playlist hasn't changed. For the first reload, it must be
        no shorter than TARGETDURATION.
        """

        await self._download_subtitles([3, 3, 3, 3, 3])

        mock_sleep.assert_awaited()
        self.assertEqual(
            mock_sleep.await_count, 5,
            "asyncio.sleep should be called 5 times",
        )
        self.assertGreaterEqual(
            mock_sleep.await_args_list[0].args[0], 60,
            "first reload delay should be 60s",
        )
        for kall in mock_sleep.await_args_list[1:]:
            sleep_time_seconds = kall.args[0]
            self.assertGreaterEqual(
                sleep_time_seconds, 30,
                "reload delays should be 30s except for the first delay",
            )

    async def test_timing_when_playlist_changes(
            self,
            mock_vttmerge, mock_sleep,
    ):
        """
        Reload interval must follow RFC 8216 when playlist has changed.

        Reload interval must be no shorter than TARGETDURATION for the
        first reload and when playlist has changed.
        """

        await self._download_subtitles([3, 4, 7, 8, 10, 11])

        mock_sleep.assert_awaited()
        self.assertEqual(
            mock_sleep.await_count, 6,
            "asyncio.sleep should be called 6 times",
        )
        for kall in mock_sleep.await_args_list:
            sleep_time_seconds = kall.args[0]
            self.assertGreaterEqual(
                sleep_time_seconds, 60,
                "reload delays should all be 60s",
            )
