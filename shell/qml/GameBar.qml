import QtQuick

// The game bar (Super+G, again or Escape to close): over the game, at the top of its screen. The game's frame rate
// (its window's own frames, counted by the compositor) and the graphics card's and processor's readings, read once a
// second while it shows; and what's wanted mid-game without leaving it: Do Not Disturb, the microphone, the sound's
// volume, a screenshot of the screen, the stats kept in the corner (the overlay, Super+Alt+G), GameMode's state.
Item {
    id: root
    signal done()
    property bool shown: false
    property var stats: ({})                  // Status.gameStats(): {windows: [{screen, app, fps, frameMs, worstMs, full}], gpu, cpu}
    property string screenName: ""
    readonly property var win: (stats.windows || []).filter(function (r) { return r.screen === root.screenName })[0] || null
    readonly property var gpu: stats.gpu || ({})
    readonly property var cpu: stats.cpu || ({})
    readonly property real presence: card.opacity
    property bool micMuted: false
    visible: shown || card.opacity > 0.01

    onShownChanged: if (shown) { micMuted = Status.micMuted(); Qt.callLater(function () { keys.forceActiveFocus() }) }
    function hot(t) { return t >= 90 ? "#E5484D" : t >= 80 ? "#E0A33A" : Theme.t.text }

    MouseArea { anchors.fill: parent; onClicked: root.done() }
    Glass {
        id: card; popup: true; dense: true
        width: Math.min(parent.width - 40, 760); height: body.height + 36
        anchors.horizontalCenter: parent.horizontalCenter; y: root.shown ? 28 : 8
        opacity: root.shown ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.t.openMs; easing.type: Easing.OutCubic } }
        Behavior on y { NumberAnimation { duration: Theme.t.openMs; easing.type: Easing.OutCubic } }
        MouseArea { anchors.fill: parent }
        Item { id: keys; focus: true
            Keys.onPressed: function (e) { if (e.key === Qt.Key_Escape || (e.key === Qt.Key_G && (e.modifiers & Qt.MetaModifier))) { root.done(); e.accepted = true } } }

        Column {
            id: body; x: 18; y: 18; width: parent.width - 36; spacing: 16
            // the readings
            Row {
                spacing: 12; width: parent.width
                Tile { objectName: "gbFps"; width: (parent.width - 36) / 4
                    big: root.win && root.win.fps > 0 ? String(root.win.fps) : "–"; small: "frames a second"
                    line: root.win && root.win.fps > 1 ? root.win.frameMs.toFixed(1) + " ms, longest " + root.win.worstMs.toFixed(1) : (root.win && root.win.app ? root.win.app : "No game in front")
                    warn: !!root.win && root.win.worstMs > 3 * Math.max(1, root.win.frameMs) }
                Tile { width: (parent.width - 36) / 4
                    big: root.gpu.load !== undefined ? root.gpu.load + "%" : "–"; small: "graphics card"
                    line: [root.gpu.temp !== undefined ? root.gpu.temp + "°C" : "", root.gpu.watts ? root.gpu.watts + " W" : "", root.gpu.ghz ? root.gpu.ghz.toFixed(2) + " GHz" : ""].filter(Boolean).join(" · ")
                    tint: root.gpu.temp !== undefined ? root.hot(root.gpu.hot || root.gpu.temp) : Theme.t.text }
                Tile { width: (parent.width - 36) / 4
                    big: root.gpu.memTotal !== undefined ? root.gpu.memUsed + " GB" : "–"; small: "video memory"
                    line: root.gpu.memTotal !== undefined ? "of " + root.gpu.memTotal + " GB" + (root.gpu.fan !== undefined ? " · fan " + root.gpu.fan + " rpm" : "") : "" }
                Tile { width: (parent.width - 36) / 4
                    big: root.cpu.load !== undefined ? root.cpu.load + "%" : "–"; small: "processor"
                    line: [root.cpu.temp !== undefined ? root.cpu.temp + "°C" : "", root.cpu.memTotal ? "RAM " + root.cpu.memUsed + " of " + root.cpu.memTotal + " GB" : ""].filter(Boolean).join(" · ")
                    tint: root.cpu.temp !== undefined ? root.hot(root.cpu.temp) : Theme.t.text }
            }
            // what's wanted mid-game
            Row {
                spacing: 10
                Switch { objectName: "gbDnd"; glyph: "moon"; label: "Do Not Disturb"; on: Status.dnd; onFlip: Status.setDnd(!Status.dnd) }
                Switch { objectName: "gbMic"; glyph: root.micMuted ? "mute" : "mic"; label: root.micMuted ? "Microphone off" : "Microphone on"; on: root.micMuted
                    onFlip: { Status.setMicMuted(!root.micMuted); root.micMuted = !root.micMuted } }
                Switch { objectName: "gbStats"; glyph: "cpu"; label: "Stats in the corner"; on: Settings.gameStats
                    onFlip: Settings.set("gameStats", Settings.gameStats ? "false" : "true") }
                Switch { objectName: "gbShot"; glyph: "camera"; label: "Screenshot"; on: false
                    onFlip: { root.done(); shotLater.restart() } }
                Timer { id: shotLater; interval: 350; onTriggered: Status.screenshot("screen") }     // once the bar has gone
            }
            Row {
                spacing: 12; width: parent.width
                Glyph { name: Status.levels.muted ? "volumeoff" : "volume"; size: 18; anchors.verticalCenter: parent.verticalCenter }
                Item { id: vol; width: parent.width - 180; height: 26; anchors.verticalCenter: parent.verticalCenter
                    readonly property real level: Status.levels.muted ? 0 : Status.levels.volume
                    Rectangle { anchors.verticalCenter: parent.verticalCenter; width: parent.width; height: 6; radius: 3; color: Theme.t.hover }
                    Rectangle { anchors.verticalCenter: parent.verticalCenter; width: parent.width * Math.min(1, vol.level); height: 6; radius: 3; color: Theme.t.accent }
                    Rectangle { x: parent.width * Math.min(1, vol.level) - 9; anchors.verticalCenter: parent.verticalCenter; width: 18; height: 18; radius: 9; color: "#FFFFFF"; border.width: 1; border.color: Theme.t.line }
                    MouseArea { anchors.fill: parent; anchors.margins: -6
                        function set(x) { Status.setVolume(Math.max(0, Math.min(1, x / vol.width))) }
                        onPressed: function (m) { set(m.x) } onPositionChanged: function (m) { if (pressed) set(m.x) } } }
                Label { width: 150; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; color: Theme.t.text_secondary
                    text: Math.round(vol.level * 100) + "%" + (Settings.gameMode ? "  ·  GameMode" + (root.win && root.win.full ? " on" : " ready") : "") }
            }
        }
    }

    component Tile: Rectangle {
        property string big: ""
        property string small: ""
        property string line: ""
        property bool warn: false
        property color tint: Theme.t.text
        height: 84; radius: 14; color: Theme.t.hover
        Column { x: 14; y: 10; width: parent.width - 28; spacing: 1
            Label { text: parent.parent.big; font.pixelSize: 26; font.weight: Font.DemiBold; color: parent.parent.tint }
            Label { text: parent.parent.small; font.pixelSize: 11; color: Theme.t.text_secondary }
            Label { width: parent.width; text: parent.parent.line; font.pixelSize: 11; elide: Text.ElideRight; color: parent.parent.warn ? "#E0A33A" : Theme.t.text_secondary } }
    }
    component Switch: Pressable {
        id: sw
        property string glyph: ""
        property string label: ""
        property bool on: false
        signal flip()
        width: swRow.width + 28; height: 40; radius: 12
        color: on ? Theme.t.accent : (hovered ? Theme.t.hover : Qt.rgba(Theme.t.hover.r, Theme.t.hover.g, Theme.t.hover.b, Theme.t.hover.a * 0.6))
        onClicked: sw.flip()
        Row { id: swRow; anchors.centerIn: parent; spacing: 8
            Glyph { name: sw.glyph; size: 16; ink: sw.on ? Theme.t.onAccent : Theme.t.icon; anchors.verticalCenter: parent.verticalCenter }
            Label { text: sw.label; font.pixelSize: 13; color: sw.on ? Theme.t.onAccent : Theme.t.text; anchors.verticalCenter: parent.verticalCenter } }
    }
}
