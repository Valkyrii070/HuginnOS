import QtQuick
import QtMultimedia

// The real playback engine (Qt Multimedia). Kept in its own file so previews with sample content never load it.
Item {
    property alias player: mp
    property alias audio: out
    property bool hasVideo: mp.hasVideo
    signal ended()
    signal loaded()                         // a new file is ready to play (its length is known: a place to carry on from can be set)
    MediaPlayer { id: mp; videoOutput: screen; audioOutput: AudioOutput { id: out; volume: 0.75 }
        onMediaStatusChanged: { if (mediaStatus === MediaPlayer.EndOfMedia) parent.ended(); else if (mediaStatus === MediaPlayer.LoadedMedia || mediaStatus === MediaPlayer.BufferedMedia) parent.loaded() } }
    VideoOutput { id: screen; anchors.fill: parent }
}
