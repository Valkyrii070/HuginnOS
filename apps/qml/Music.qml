import QtQuick

// Music, "glow": the cover is the light. Now Playing shows it; Library is the list. The transport is one island.
GlassWindow {
    id: win
    title: "Music"
    property string view: demo ? "playing" : "library"
    glow: view === "playing" ? "centre" : "bottom"; glowY: 0.4
    property string album: ""
    property string filter: ""
    property var shown: Backend.items.filter(function (s) { return (!album || (s.album || "Unknown album") === album) && (s.title + s.artist + s.album).toLowerCase().indexOf(filter.toLowerCase()) >= 0 })
    // What's playing is a song (by its file), not a row: searching or choosing an album doesn't change it. The songs
    // that were listed when it started are the queue Next and Previous move through.
    property string playingPath: demo && Backend.items.length > 1 ? Backend.items[1].path : ""
    property var queue: demo ? Backend.items : []
    property int selected: -1                    // the row clicked on (double-click or Enter plays it)
    property bool shuffle: false
    property string repeat: "off"                // off, all, one
    property var heard: []                       // with shuffle: what's been played this time round
    function indexIn(list, path) { for (var i = 0; i < list.length; i++) if (list[i].path === path) return i; return -1 }
    readonly property int current: playingPath === "" ? -1 : indexIn(shown, playingPath)
    readonly property var song: { var i = playingPath === "" ? -1 : indexIn(Backend.items, playingPath); return i >= 0 ? Backend.items[i] : null }
    readonly property color pick: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.18)
    function start(s) { playingPath = s.path; if (heard.indexOf(s.path) < 0) heard = heard.concat([s.path]); if (s.url) { player.source = s.url; player.play() } }
    function play(i) { if (i < 0 || i >= shown.length) return; queue = shown; heard = []; selected = i; start(shown[i]) }
    // the top bar's Controls menu, and its keys
    function playPause() { if (playingPath === "") play(selected >= 0 ? selected : 0); else if (player.playing) player.pause(); else player.play() }
    function nextSong(ended) {
        var q = queue.length ? queue : shown, at = indexIn(q, playingPath)
        if (!q.length) return
        if (ended === true && repeat === "one" && at >= 0) { player.position = 0; player.play(); return }
        if (shuffle) {
            var left = q.filter(function (s) { return heard.indexOf(s.path) < 0 })
            if (!left.length) { if (repeat !== "all" && ended === true) return; heard = []; left = q.filter(function (s) { return s.path !== playingPath }); if (!left.length) left = q }
            start(left[Math.floor(Math.random() * left.length)]); return
        }
        if (at + 1 < q.length) start(q[at + 1]); else if (repeat === "all" || ended !== true) start(q[0])
    }
    function previousSong() {
        if (player.position > 4000) { player.position = 0; return }             // partway in: back to its start first
        var q = queue.length ? queue : shown, at = indexIn(q, playingPath)
        if (shuffle && heard.length > 1) { var h = heard.slice(0, -1), prev = indexIn(q, h[h.length - 1]); heard = h.slice(0, -1); if (prev >= 0) { start(q[prev]); return } }
        if (q.length) start(q[Math.max(0, at - 1)])
    }
    function toggleShuffle() { shuffle = !shuffle; heard = playingPath ? [playingPath] : [] }
    function cycleRepeat() { repeat = repeat === "off" ? "all" : repeat === "all" ? "one" : "off" }
    function louder() { out.volume = Math.min(1, out.volume + 0.1) }
    function quieter() { out.volume = Math.max(0, out.volume - 0.1) }
    function setView(v) { view = v === "library" ? "library" : "playing" }
    // Playback: the real engine, or (with sample content) a stand-in that only holds numbers for the preview.
    QtObject { id: stub; property bool playing: true; property real position: 83000; property real duration: 228000; property url source; function play() {} function pause() {} }
    QtObject { id: stubAudio; property real volume: 0.7 }
    readonly property var player: engine.item ? engine.item.player : stub
    readonly property var out: engine.item ? engine.item.audio : stubAudio
    Loader { id: engine; active: !demo; source: "Engine.qml"; visible: false }
    Connections { target: engine.item; function onEnded() { win.nextSong(true) } }
    Component.onCompleted: if (!demo && Backend.opened) play(0)
    MprisLink { player: win.player; title: win.song ? win.song.title : ""; artist: win.song ? win.song.artist || "" : ""; album: win.song ? win.song.album || "" : ""
        onNext: win.nextSong(); onPrevious: win.previousSong(); onRaise: { win.raise(); win.requestActivate() } }
    islands: [
        Island {
            anchors { right: parent.right; rightMargin: 12 } y: 12
            IslandField { visible: win.view === "library"; text: win.filter; onTextChanged: win.filter = text; placeholder: "Search your music" }
            Seg { text: "Now Playing"; on: win.view === "playing"; onClicked: win.view = "playing" }
            Seg { text: "Library"; on: win.view === "library"; onClicked: win.view = "library" }
        },
        Island {   // the transport: the main island
            visible: Backend.items.length > 0; height: 58; radius: 20; pad: 12
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 14 }
            Column { visible: win.view === "library"; width: 170; anchors.verticalCenter: parent.verticalCenter
                Label { width: parent.width; text: win.song ? win.song.title : "Nothing playing"; elide: Text.ElideRight; font.weight: Font.DemiBold; font.pixelSize: 12 }
                Label { width: parent.width; text: win.song ? win.song.artist : "Double-click a song"; elide: Text.ElideRight; secondary: true; font.pixelSize: 11 } }
            PlayerBar { width: Math.min(640, win.width - (win.view === "library" ? 360 : 180)); anchors.verticalCenter: parent.verticalCenter
                player: win.player; audio: win.out; onNext: win.nextSong(); onPrevious: win.previousSong() }
            Seg { icon: "shuffle"; tip: "Shuffle"; on: win.shuffle; onClicked: win.toggleShuffle() }
            Seg { icon: "refresh"; tip: win.repeat === "one" ? "Repeating this song" : win.repeat === "all" ? "Repeating them all" : "Repeat"; on: win.repeat !== "off"
                text: win.repeat === "one" ? "1" : ""; onClicked: win.cycleRepeat() }
        }
    ]
    Item { id: listKeys; focus: true
        Keys.onPressed: function (e) {
            if (e.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)) return
            if (e.key === Qt.Key_Space) win.playPause()
            else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { if (win.selected >= 0) win.play(win.selected) }
            else if (e.key === Qt.Key_Down) win.selected = Math.min(win.shown.length - 1, win.selected + 1)
            else if (e.key === Qt.Key_Up) win.selected = Math.max(0, win.selected - 1)
            else return
            e.accepted = true
        } }
    DropArea { anchors.fill: parent; onDropped: function (d) { if (d.hasUrls && Backend.addFiles(d.urls.map(function (u) { return u.toString() })) > 0) { win.album = ""; win.filter = ""; win.play(0) } } }
    Column { visible: Backend.items.length === 0; anchors.centerIn: parent; spacing: 8
        Glyph { name: "music"; size: 44; ink: Theme.t.text_secondary; anchors.horizontalCenter: parent.horizontalCenter }
        Label { text: "No music yet"; font.pixelSize: 17; font.weight: Font.DemiBold; anchors.horizontalCenter: parent.horizontalCenter }
        Label { text: "Songs you put in " + Backend.folderName + " appear here."; secondary: true; anchors.horizontalCenter: parent.horizontalCenter } }

    // ---------------- Now Playing
    Column { visible: win.view === "playing" && Backend.items.length > 0; anchors.horizontalCenter: parent.horizontalCenter; y: Math.max(70, (win.height - 90 - height) / 2); spacing: 6
        Rectangle { width: Math.min(300, win.height - 300); height: width; radius: 22; anchors.horizontalCenter: parent.horizontalCenter
            gradient: Gradient { GradientStop { position: 0; color: Theme.t.accent } GradientStop { position: 1; color: "#7B61FF" } }
            border.width: 1; border.color: "#33FFFFFF"
            Glyph { anchors.centerIn: parent; name: "music"; size: parent.width * 0.3; ink: "#FFFFFF"; opacity: 0.9 } }
        Item { width: 1; height: 14 }
        Label { text: win.song ? win.song.title : "Nothing playing"; font.pixelSize: 22; font.weight: Font.DemiBold; anchors.horizontalCenter: parent.horizontalCenter }
        Label { text: win.song ? win.song.artist + (win.song.album ? "  ·  " + win.song.album : "") : "Pick a song in Library"; secondary: true; anchors.horizontalCenter: parent.horizontalCenter } }

    // ---------------- Library
    Item { visible: win.view === "library" && Backend.items.length > 0; anchors { fill: parent; topMargin: 64 }
        Flickable { id: chips; x: 14; width: parent.width - 28; height: 34; contentWidth: chipRow.width; clip: true
            Row { id: chipRow; height: 34; spacing: 6
                Seg { text: "All Songs"; icon: "music"; on: win.album === ""; onClicked: { win.album = ""; win.selected = -1 } }
                Repeater { model: Backend.albums; Seg { required property var modelData; icon: "disc"; text: modelData.name; on: win.album === modelData.name; onClicked: { win.album = modelData.name; win.selected = -1 } } } } }
        Rectangle { x: 14; y: 44; width: parent.width - 28; height: parent.height - 44 - 86; radius: 12; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine; clip: true
            MouseArea { anchors.fill: parent }
            Row { x: 6; height: 30
                Label { width: 40; text: "#"; secondary: true; font.pixelSize: 11; leftPadding: 12; anchors.verticalCenter: parent.verticalCenter } Label { width: table.width * 0.38; text: "Title"; secondary: true; font.pixelSize: 11; anchors.verticalCenter: parent.verticalCenter }
                Label { width: table.width * 0.24; text: "Artist"; secondary: true; font.pixelSize: 11; anchors.verticalCenter: parent.verticalCenter } Label { width: table.width * 0.24; text: "Album"; secondary: true; font.pixelSize: 11; anchors.verticalCenter: parent.verticalCenter } }
            Flickable { id: table; x: 6; y: 30; width: parent.width - 12; height: parent.height - 36; contentHeight: songs.height; clip: true
                Column { id: songs; width: parent.width
                    Repeater { model: win.shown
                        Pressable { required property var modelData; required property int index; readonly property bool on: win.current === index
                            width: songs.width; height: 38; radius: 9; color: on ? win.pick : (win.selected === index ? Qt.rgba(0.5, 0.5, 0.5, 0.13) : hovered ? Qt.rgba(0.5, 0.5, 0.5, 0.07) : "transparent")
                            MouseArea { anchors.fill: parent; onDoubleClicked: win.play(index); onClicked: { win.selected = index; listKeys.forceActiveFocus() } }
                            Label { visible: !parent.on; x: 12; anchors.verticalCenter: parent.verticalCenter; text: index + 1; secondary: true; font.pixelSize: 12 }
                            Glyph { visible: parent.on; x: 10; anchors.verticalCenter: parent.verticalCenter; name: "volume"; size: 15; ink: Theme.t.accent }
                            Label { x: 40; width: table.width * 0.38 - 12; anchors.verticalCenter: parent.verticalCenter; text: modelData.title; elide: Text.ElideRight; color: parent.on ? Theme.t.accent : Theme.t.text; font.weight: parent.on ? Font.DemiBold : Font.Normal }
                            Label { x: 40 + table.width * 0.38; width: table.width * 0.24 - 12; anchors.verticalCenter: parent.verticalCenter; text: modelData.artist; elide: Text.ElideRight; secondary: true }
                            Label { x: 40 + table.width * 0.62; width: table.width * 0.24 - 12; anchors.verticalCenter: parent.verticalCenter; text: modelData.album; elide: Text.ElideRight; secondary: true }
                            Label { anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter } text: modelData.length; secondary: true; font.pixelSize: 12; font.family: Theme.t.fontMono } } } } } }
    }
}
