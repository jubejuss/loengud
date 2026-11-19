# Privacy Policy – Loengud lecture publisher

_Last updated: 19 November 2026_

**Loengud lecture publisher** ("the tool") is a private command-line tool written and operated by Juho Kalberg (contact: jubejuss@gmail.com). The tool runs only on its owner's own computer. It publishes the owner's university lecture recordings to the owner's own YouTube channel and adds Estonian captions to them.

## Who uses the tool
The only user is the owner. The tool does not offer any service to other people. Nobody else signs in to it, and it never accesses another person's YouTube channel or Google account.

## What data the tool accesses
Through YouTube API Services, using OAuth 2.0 with the scopes `youtube.upload` and `youtube.force-ssl`, the tool:
- uploads the owner's lecture videos to the owner's channel and sets their title, description and privacy status;
- uploads and updates caption tracks for those videos;
- adds those videos to the owner's course playlists;
- reads the owner's channel uploads list, so it can find a video the owner uploaded through YouTube Studio.

## What data is stored
The tool keeps the following on the owner's computer only:
- the OAuth access and refresh token, in a file readable only by the owner (permissions 600);
- a local status file containing file names, YouTube video IDs and processing state;
- transcripts and caption files of the owner's own lectures, which are also committed to the owner's course repositories.

The tool does not collect, store, sell or share any personal data of YouTube users or viewers. It uses no analytics, no advertising and no third-party tracking. Speech recognition runs locally on the owner's computer (whisper.cpp with Tallinn University of Technology's open Estonian model); no audio or video is sent to third-party services. The text transcript of the owner's own lecture is sent to Anthropic's Claude (via the owner's own Claude Code account) only to draft the video description, chapters and lecture notes; no YouTube API data is sent there.

## Google and YouTube
The tool uses YouTube API Services. By using it, the owner agrees to the [YouTube Terms of Service](https://www.youtube.com/t/terms). The [Google Privacy Policy](https://policies.google.com/privacy) also applies. You can revoke the tool's access at any time in your [Google Account security settings](https://myaccount.google.com/permissions).

## Deleting data
Revoking access in Google Account settings invalidates the stored token. Deleting `~/.config/loengud/` removes all locally stored data.

## Contact
Juho Kalberg – jubejuss@gmail.com
