import QtQuick

// Media Player, "stage": all picture. The list of videos and the transport float over it.
GlassWindow {
    id: win
    title: "Media Player"; glow: "none"; baseColor: "#050507"
    property int current: demo ? 0 : -1
    property bool showList: !demo
    readonly property var clip: current >= 0 && current < Backend.items.length ? Backend.items[current] : null
    heading: clip ? clip.title : ""
    bare: visibility === Window.FullScreen && !hover.containsMouse
    property real rate: 1.0                     // playback speed
    property bool loop: false                   // play the same video again when it ends
    property var cues: []                       // subtitles from a file beside the video
    property bool subsOn: true
    property string cueText: ""
    property real resumeFrom: 0                 // where this video was stopped last time (asked once it has loaded)
    property string note: ""                    // a word over the picture for a moment: "1.5×", "Volume 80%"
    function flash(text) { note = text; noteGone.restart() }
    function keep() { if (clip && clip.path && player.duration > 0) Backend.remember(clip.path, player.position, player.duration) }
    function play(i) {
        if (i < 0 || i >= Backend.items.length) return
        keep()
        current = i; showList = false; cueText = ""
        var it = Backend.items[i]
        cues = it.path ? Backend.subtitles(it.path) : []
        resumeFrom = it.path ? Backend.resumeAt(it.path) : 0
        if (it.url) { player.source = it.url; player.playbackRate = rate; player.play() }
    }
    function full() { win.visibility === Window.FullScreen ? win.showNormal() : win.showFullScreen() }
    function playPause() { if (current < 0 && Backend.items.length) play(0); else if (player.playing) player.pause(); else player.play() }
    function skip(ms) { player.position = Math.max(0, Math.min(player.duration, player.position + Number(ms))) }
    function toggleList() { showList = !showList }
    function setRate(r) { rate = Math.max(0.25, Math.min(3, Number(r))); player.playbackRate = rate; flash(rate + "×") }
    function stepRate(d) { var all = [0.5, 0.75, 1, 1.25, 1.5, 2], i = all.indexOf(rate); setRate(all[Math.max(0, Math.min(all.length - 1, (i < 0 ? 2 : i) + Number(d)))]) }
    function toggleLoop() { loop = !loop; flash(loop ? "Repeat on" : "Repeat off") }
    function toggleSubs() { subsOn = !subsOn; flash(cues.length ? (subsOn ? "Subtitles on" : "Subtitles off") : "No subtitles beside this video") }
    function volume(d) { out.volume = Math.max(0, Math.min(1, out.volume + Number(d))); flash("Volume " + Math.round(out.volume * 100) + "%") }
    function cueAt(ms) {      // the subtitle showing at this moment (they're in order: a search by halves)
        var lo = 0, hi = cues.length - 1
        while (lo <= hi) { var mid = (lo + hi) >> 1, c = cues[mid]; if (ms < c.a) hi = mid - 1; else if (ms > c.b) lo = mid + 1; else return c.text }
        return ""
    }
    Timer { id: noteGone; interval: 1400; onTriggered: win.note = "" }
    Timer { interval: 200; repeat: true; running: win.cues.length > 0 && win.subsOn && !demo; onTriggered: win.cueText = win.cueAt(win.player.position) }
    Timer { interval: 15000; repeat: true; running: !demo && win.player.playing; onTriggered: win.keep() }
    onClosing: keep()
    Component.onCompleted: if (!demo && Backend.opened) play(0)
    Connections { target: engine.item
        function onEnded() { if (win.loop) { win.player.position = 0; win.player.play() } else if (win.current + 1 < Backend.items.length) win.play(win.current + 1) }
        function onLoaded() { if (win.resumeFrom > 0) { win.player.position = win.resumeFrom; win.flash("Carrying on from " + bar.clock(win.resumeFrom)); win.resumeFrom = 0 } } }
    // Playback: the real engine, or (with sample content) a stand-in that only holds numbers for the preview.
    QtObject { id: stub; property bool playing: true; property real position: 83000; property real duration: 228000; property url source; property real playbackRate: 1; function play() {} function pause() {} }
    QtObject { id: stubAudio; property real volume: 0.7; property bool muted: false }
    readonly property var player: engine.item ? engine.item.player : stub
    readonly property var out: engine.item ? engine.item.audio : stubAudio
    MprisLink { player: win.player; title: win.clip ? win.clip.title : ""
        onNext: win.play(win.current + 1); onPrevious: win.play(win.current - 1); onRaise: { win.raise(); win.requestActivate() } }
    islands: [
        Island { anchors { right: parent.right; rightMargin: win.liftRight } y: win.topY
            Seg { icon: "list"; text: "Videos"; on: win.showList; onClicked: win.showList = !win.showList }
            Seg { text: win.rate + "×"; tip: "Speed (the [ and ] keys)"; on: win.rate !== 1; onClicked: win.stepRate(win.rate >= 2 ? -5 : 1) }
            Seg { icon: "refresh"; tip: "Repeat this video (L)"; on: win.loop; onClicked: win.toggleLoop() }
            Seg { visible: win.cues.length > 0; icon: "captions"; tip: "Subtitles (S)"; on: win.subsOn; onClicked: win.toggleSubs() }
            Seg { icon: "expand"; tip: "Full screen"; onClicked: win.full() } },
        Rail { visible: win.showList; x: 12; y: 64; width: 280; maxHeight: win.height - 64 - 90
            SideTitle { text: "YOUR VIDEOS" }
            Repeater { model: Backend.items
                SideItem { required property var modelData; required property int index; icon: "video"; text: modelData.title; trailing: modelData.length; selected: win.current === index; onClicked: win.play(index) } }
            Label { visible: Backend.items.length === 0; padding: 10; width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12; text: "Videos in " + Backend.folderName + " appear here." } },
        Island {   // the transport: the one wide island
            height: 58; radius: 20; pad: 12; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 14 }
            PlayerBar { id: bar; width: Math.min(900, win.width - 64); anchors.verticalCenter: parent.verticalCenter; player: win.player; audio: win.out
                onNext: win.play(win.current + 1); onPrevious: win.play(win.current - 1) } }
    ]
    Rectangle { anchors.fill: parent; radius: win.r; color: "#000000"
        Loader { id: engine; active: !demo; source: "Engine.qml"; anchors { fill: parent; margins: win.r > 1 ? 6 : 0 } }
        Rectangle { visible: demo; anchors.fill: parent; radius: win.r
            gradient: Gradient { GradientStop { position: 0; color: "#17122B" } GradientStop { position: 0.55; color: "#2A1F55" } GradientStop { position: 1; color: "#0B0A14" } }
            Rectangle { anchors { bottom: parent.bottom; bottomMargin: parent.height * 0.3 } width: parent.width; height: 2; color: Theme.t.accent; opacity: 0.35 } }
        Column { visible: !demo && !(engine.item && engine.item.hasVideo); anchors.centerIn: parent; spacing: 8
            Glyph { name: "video"; size: 44; ink: "#8A9199"; anchors.horizontalCenter: parent.horizontalCenter }
            Label { text: win.clip ? "Loading…" : "Choose a video from the list"; color: "#C4CBD3"; anchors.horizontalCenter: parent.horizontalCenter } }
        MouseArea { id: hover; anchors.fill: parent; hoverEnabled: true; onClicked: { keys.forceActiveFocus(); win.playPause() } onDoubleClicked: win.full()
            onWheel: function (w) { win.volume(w.angleDelta.y > 0 ? 0.05 : -0.05) } }
        // subtitles from a file beside the video
        Rectangle { visible: win.cueText !== "" && win.subsOn; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: win.bare ? 40 : 96 }
            width: Math.min(cue.implicitWidth + 28, parent.width - 80); height: cue.implicitHeight + 14; radius: 10; color: "#B3000000"
            Text { id: cue; anchors.centerIn: parent; width: Math.min(implicitWidth, parent.parent.width - 108); text: win.cueText; color: "#FFFFFF"; wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter; font.pixelSize: Math.max(18, Math.round(win.height / 30)); font.family: Theme.t.font; font.weight: Font.Medium; textFormat: Text.PlainText } }
        // a word about what a key just did
        Rectangle { visible: win.note !== ""; anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 76 } width: noteText.implicitWidth + 28; height: 34; radius: 17; color: "#B3000000"
            Text { id: noteText; anchors.centerIn: parent; text: win.note; color: "#FFFFFF"; font.pixelSize: 14; font.weight: Font.DemiBold; font.family: Theme.t.font } }
        // dropping videos on the window plays them
        DropArea { anchors.fill: parent; onDropped: function (d) { if (d.hasUrls && Backend.addFiles(d.urls.map(function (u) { return u.toString() })) > 0) win.play(0) } }
        Item { id: keys; focus: true; anchors.fill: parent
            Keys.onPressed: function (e) {
                var k = e.key, shift = e.modifiers & Qt.ShiftModifier
                if (e.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)) return
                if (k === Qt.Key_Space || k === Qt.Key_K) win.playPause()
                else if (k === Qt.Key_Left) win.skip(shift ? -60000 : -5000)
                else if (k === Qt.Key_Right) win.skip(shift ? 60000 : 5000)
                else if (k === Qt.Key_Up) win.volume(0.05)
                else if (k === Qt.Key_Down) win.volume(-0.05)
                else if (k === Qt.Key_F || k === Qt.Key_F11) win.full()
                else if (k === Qt.Key_Escape && win.visibility === Window.FullScreen) win.showNormal()
                else if (k === Qt.Key_BracketLeft) win.stepRate(-1)
                else if (k === Qt.Key_BracketRight) win.stepRate(1)
                else if (k === Qt.Key_L) win.toggleLoop()
                else if (k === Qt.Key_S) win.toggleSubs()
                else if (k === Qt.Key_M) { win.out.muted = !win.out.muted; win.flash(win.out.muted ? "Muted" : "Sound on") }
                else if (k === Qt.Key_N || k === Qt.Key_PageDown) win.play(win.current + 1)
                else if (k === Qt.Key_P || k === Qt.Key_PageUp) win.play(win.current - 1)
                else if (k >= Qt.Key_0 && k <= Qt.Key_9) win.player.position = win.player.duration * (k - Qt.Key_0) / 10
                else return
                e.accepted = true
            } } }
}
