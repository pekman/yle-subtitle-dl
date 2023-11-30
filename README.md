Yle live stream subtitle downloader
===================================

A hacky little companion application for [yle-dl][], which currently
cannot download subtitles for live streams due to an ffmpeg bug (see
[yle-dl bug 295][bug]). This program is meant for Yle live streams and
may or may not work on other videos — just use yle-dl for them.

**Note**: Downloaded subtitles will be out of sync with the video.
This is because they are downloaded separately with no guarantee of
exact same start time and no timestamps stored in the video file.
Subtitled must be synchronized manually, either with a subtitle resync
tool or by using a video player that supports subtitle timing
adjustment.

This project is not actively maintained. It's just something I threw
together when I realized subtitles were missing (and after I gave up
on digging around ffmpeg internals). I hope it won't be needed for
long.


Installation
------------

1. install [pipx][]
2. `pipx install git+https://github.com/pekman/yle-subtitle-dl.git`
3. you probably also want to install [yle-dl][]


Usage
-----

`yle-subtitle-dl [options] URL OUTPUT_BASENAME`

Run `yle-subtitle-dl --help` for full list of options.


### How to use with yle-dl ###

The right start time is needed to minimize timing mismatch between
video and subtitles. Unfortunately ffmpeg, and thus yle-dl, doesn't
support an absolute start time like our `--start-time`, which makes
synchronization difficult. Here are some ways to minimize the timing
mismatch:

Start both yle-dl and yle-subtitle-dl at the same time:

```sh
> yle-dl --showurl https://areena.yle.fi/tv/suorat/yle-tv1
https://example.net/hls/live/notarealurl/yletv1fin/index.m3u8

> yle-dl -o yle1.mkv --duration 1800 \
    https://areena.yle.fi/tv/suorat/yle-tv1 & \
  yle-subtitle-dl -o yle1 --duration 1800 \
    https://example.net/hls/live/notarealurl/yletv1fin/index.m3u8
```

Or with tmux:

```sh
> tmux new-session \
    'yle-dl -o yle1.mkv --duration 1800 https://areena.yle.fi/tv/suorat/yle-tv1' \
    ';' \
    new-window \
    "yle-subtitle-dl -o yle1 --duration 1800 $(yle-dl --showurl https://areena.yle.fi/tv/suorat/yle-tv1)"
```

Run yle-dl first, then time travel to the past (this seems to work for
several hours):

```sh
> start=$(date -Ins); \
    yle-dl -o yle1.mkv --duration 1800 \
      https://areena.yle.fi/tv/suorat/yle-tv1
...
<time passes>
...

> yle-subtitle-dl -o yle1 --start_time "$start" --duration 1800 \
    $(yle-dl --showurl https://areena.yle.fi/tv/suorat/yle-tv1)
```


Known issues
------------

- There may be some seconds worth of extra subtitles at the end after
  the time given in duration or end time. This should be harmless.

- There may be duplicate subtitles so that the second one starts when
  the first one ends. This should be invisible when playing.


[yle-dl]: https://aajanki.github.io/yle-dl/
[bug]: https://github.com/aajanki/yle-dl/issues/295#issuecomment-1038208395
[pipx]: https://pypa.github.io/pipx/
