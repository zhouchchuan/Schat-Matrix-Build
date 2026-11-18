"""Configure the pinned MatrixRTC and LiveKit sources for Schat calls."""

import argparse
import hashlib
import re
import tarfile
import urllib.request
from pathlib import Path


def replace(path, old, new):
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise ValueError(f"Expected one match in {path}: {old}")
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


def prepare_livekit(root, archive):
    manifest = root / "Cargo.toml"
    lockfile = root / "Cargo.lock"
    lock_entry = re.search(
        r'(?m)^name = "livekit"\nversion = "0\.9\.7"\nsource = "[^"]+"\nchecksum = "([0-9a-f]{64})"\n',
        lockfile.read_text(encoding="utf-8"),
    )
    if not lock_entry:
        raise ValueError("Expected the pinned LiveKit 0.9.7 crate")
    if archive is None:
        archive = root / "livekit-0.9.7.crate"
        with urllib.request.urlopen("https://static.crates.io/crates/livekit/livekit-0.9.7.crate", timeout=120) as response:
            archive.write_bytes(response.read())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != lock_entry[1]:
        raise ValueError("LiveKit package checksum mismatch")
    with tarfile.open(archive) as tar:
        tar.extractall(root / "vendor", filter="data")
    replace(manifest, "[patch.crates-io]\n",
            '[patch.crates-io]\nlivekit = { path = "vendor/livekit-0.9.7" }\n')
    replace(lockfile, lock_entry[0], 'name = "livekit"\nversion = "0.9.7"\n')

    sdk = root / "vendor/livekit-0.9.7/src"
    replace(
        sdk / "room/options.rs",
        "    pub dtx: bool,",
        "    pub stereo: bool,\n    pub dtx: bool,",
    )
    replace(sdk / "room/options.rs", "            dtx: true,", "            stereo: false,\n            dtx: true,")
    replace(
        sdk / "room/participant/local_participant.rs",
        "        req.packet_trailer_features =",
        """        if options.stereo && track.kind() == TrackKind::Audio {
            req.audio_features.push(proto::AudioTrackFeature::TfStereo as i32);
        }

        req.packet_trailer_features =""",
    )
    # A sender capability check lets the transport use VP8 if H.264 is unavailable.
    replace(
        sdk / "room/options.rs",
        "impl VideoCodec {\n",
        """impl VideoCodec {
    pub fn can_encode(&self) -> bool {
        let mime = format!("video/{}", self.as_str());
        crate::rtc_engine::lk_runtime::LkRuntime::instance()
            .pc_factory()
            .get_rtp_sender_capabilities(MediaType::Video)
            .codecs
            .iter()
            .any(|codec| codec.mime_type.eq_ignore_ascii_case(&mime))
    }

""",
    )


def prepare_rtc(root):
    crates = root / "crates"
    transport = crates / "matrix-rtc-livekit/src/transport_impl.rs"
    replace(
        transport,
        "use livekit::options::TrackPublishOptions;",
        "use livekit::options::{AudioEncoding, TrackPublishOptions, VideoCodec, VideoEncoding, VideoPreset};",
    )
    replace(
        transport,
        "const AUDIO_CHANNELS: i32 = 1;",
        "const AUDIO_CHANNELS: i32 = 2;\nconst STEREO_OPUS_BITRATE_BPS: u64 = 112_000;",
    )
    replace(
        transport,
        """                LocalSource::Audio(NativeAudioSource::new(
                    AudioSourceOptions::default(),
                    config.sample_rate,
                    config.num_channels,
                    1000,
                ))""",
        """                LocalSource::Audio {
                    source: NativeAudioSource::new(
                        AudioSourceOptions::default(),
                        config.sample_rate,
                        config.num_channels,
                        1000,
                    ),
                    stereo: config.num_channels == 2,
                }""",
    )
    replace(
        transport,
        "    Audio(NativeAudioSource),",
        "    Audio { source: NativeAudioSource, stereo: bool },",
    )
    replace(transport, "LocalSource::Audio(source) => {", "LocalSource::Audio { source, stereo } => {")
    replace(
        transport,
        "let LocalSource::Audio(source) = &self.source else {",
        "let LocalSource::Audio { source, .. } = &self.source else {",
    )
    replace(
        transport,
        """                    LocalTrack::Audio(track),
                    TrackPublishOptions {
                        source: source_kind,
                        ..Default::default()
                    },""",
        """                    LocalTrack::Audio(track),
                    TrackPublishOptions {
                        source: source_kind,
                        stereo: *stereo,
                        dtx: !stereo,
                        audio_encoding: stereo.then_some(AudioEncoding {
                            max_bitrate: STEREO_OPUS_BITRATE_BPS,
                        }),
                        ..Default::default()
                    },""",
    )
    replace(
        transport,
        """        session
            .room()
            .local_participant()
            .publish_track(track.clone(), options)""",
        """        let mut options = options;
        if let LocalTrack::Video(video) = &track
            && self.kind == MediaStreamKind::Camera
        {
            let size = video.rtc_source().video_resolution();
            configure_camera_encoding(&mut options, size.width, size.height);
        }
        session
            .room()
            .local_participant()
            .publish_track(track.clone(), options)""",
    )
    replace(
        transport,
        "/// The native source behind a local publication, which outlives every room",
        """/// Caps for the three simulcast layers. WebRTC handles congestion control
/// and the SFU can select a lower layer without reconnecting the call.
fn configure_camera_encoding(options: &mut TrackPublishOptions, width: u32, height: u32) {
    let short_edge = width.min(height).max(1);
    let preset = |edge: u32, bitrate, fps| {
        let edge = edge.min(short_edge);
        let scale = |dimension: u32| (dimension * edge / short_edge).max(2) & !1;
        VideoPreset::new(scale(width), scale(height), bitrate, fps)
    };
    options.video_codec = if VideoCodec::H264.can_encode() {
        VideoCodec::H264
    } else {
        log::warn!("Camera H.264 encoder unavailable; using VP8");
        VideoCodec::VP8
    };
    options.video_encoding = Some(VideoEncoding {
        max_bitrate: if short_edge >= 900 { 3_200_000 } else { 1_600_000 },
        max_framerate: 30.0,
    });
    options.simulcast_layers = Some(vec![
        preset(360.min(short_edge / 2).max(2), 400_000, 18.0),
        preset(720.min(short_edge * 2 / 3).max(2), 1_400_000, 24.0),
    ]);
}

/// The native source behind a local publication, which outlives every room""",
    )

    room_state = crates / "matrix-rtc-call/src/room_state.rs"
    if "let CallJoinParams { rtc, kind, .. } = params;" in room_state.read_text(encoding="utf-8"):
        replace(
            room_state,
            """        let CallJoinParams { rtc, kind, .. } = params;
        let slot_id = rtc.slot_id.clone();""",
            """        let CallJoinParams { mut rtc, kind, .. } = params;
        let slot_id = rtc.slot_id.clone();
        let intent = match &kind {
            CallKind::Direct { ring: Some(ring) } => ring.intent.as_deref(),
            CallKind::Group { notify: Some(notify) } => notify.intent.as_deref(),
            _ => None,
        };
        if let Some(intent @ ("audio" | "video")) = intent {
            rtc.application = rtc.application.with_extra("m.call.intent", intent.into());
        }""",
        )
    elif ".with_extra(CALL_INTENT_KEY, intent.as_str().into())" not in room_state.read_text(encoding="utf-8"):
        raise ValueError("Pinned RTC source did not propagate the call intent")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--livekit-crate", type=Path)
    args = parser.parse_args()
    prepare_livekit(args.root, args.livekit_crate)
    prepare_rtc(args.root)

