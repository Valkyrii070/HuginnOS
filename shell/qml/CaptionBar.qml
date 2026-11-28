import QtQuick

// Live captions (Super+Ctrl+L, the Control Centre, Settings › Accessibility): what's playing, written out on this
// computer (huginn_livecaptions.py runs apps/huginn_captions.py), in a dark bar that can be dragged anywhere on its
// screen and stays where it was left. Only the bar takes the pointer (Status.setInputRegion); it sits over everything,
// full-screen videos and games too. The newest words are at the bottom; older lines go up and out of it.
Item {
    id: bar
    property var host: null                                  // its Window (the input region is set on it)
    readonly property int fontPx: Settings.captionsSize === "large" ? 34 : Settings.captionsSize === "small" ? 20 : 26
    readonly property real lineH: Math.ceil(fm.height * 1.12)
    property real fx: 0.5
    property real fy: 0.84
    property bool quiet: false                                // nothing new for a while: the words fade, the bar stays
    readonly property string words: Captions.text
    readonly property string message: {
        var s = Captions.state
        if (s === "no-model") return "Live captions need a speech model, the same one dictation uses."
        if (s === "no-engine") return "Live captions need the speech engine, which needs a processor with AVX2."
        if (s === "no-sound") return "Can't hear what's playing" + (Captions.why ? ": " + Captions.why : ".")
        if (s === "starting") return "Starting live captions…"
        if (Captions.error && !words) return "A moment couldn't be written out: " + Captions.error
        return "Live captions are on. Play something with speech in it."
    }

    function readPos() {
        var p = (Settings.captionsPos || "").split(",")
        if (p.length === 2 && !isNaN(+p[0]) && !isNaN(+p[1])) { fx = +p[0]; fy = +p[1] } else { fx = 0.5; fy = 0.84 }
    }
    function region() {
        if (host && host.visible) Status.setInputRegion(host, Math.round(box.x), Math.round(box.y), Math.round(box.width), Math.round(box.height))
    }
    Component.onCompleted: readPos()
    Connections { target: Settings; function onChanged() { if (!mover.pressed) bar.readPos() } }
    Connections { target: Captions; function onCountChanged() { bar.quiet = false; hush.restart() } }
    Timer { id: hush; interval: 9000; onTriggered: bar.quiet = true }
    FontMetrics { id: fm; font.pixelSize: bar.fontPx; font.family: Theme.t.font; font.weight: Font.Medium }

    Rectangle {
        id: box
        width: Math.min(bar.width - 24, Math.max(560, Math.round(bar.width * 0.55)))
        height: wordsArea.height + 28 + (help.visible ? help.height + 10 : 0)
        x: Math.max(8, Math.min(bar.width - width - 8, bar.fx * bar.width - width / 2))
        y: Math.max(8, Math.min(bar.height - height - 8, bar.fy * bar.height - height / 2))
        radius: 16
        color: Qt.rgba(0.02, 0.02, 0.03, Settings.contrast ? 0.95 : 0.82)
        border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.10)
        onXChanged: bar.region(); onYChanged: bar.region(); onWidthChanged: bar.region(); onHeightChanged: bar.region()
        opacity: 0; Component.onCompleted: { opacity = 1; bar.region() }
        Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

        // the words: the last two lines of what was said, newest at the bottom
        Item {
            id: wordsArea; x: 22; y: 14; width: box.width - 22 - 50; height: bar.words ? bar.lineH * 2 : Math.min(bar.lineH * 2, said.implicitHeight); clip: true
            Text {
                id: said
                width: parent.width; anchors.bottom: parent.bottom
                text: bar.words || bar.message
                wrapMode: Text.WordWrap; lineHeight: 1.12
                color: bar.words ? "#FFFFFF" : "#B9C2CC"
                font.pixelSize: bar.words ? bar.fontPx : Math.round(bar.fontPx * 0.72); font.family: Theme.t.font; font.weight: Font.Medium
                opacity: bar.quiet && bar.words ? 0.38 : 1
                Behavior on opacity { NumberAnimation { duration: 600 } }
            }
        }
        // dragging it anywhere; its place is kept when it's let go
        MouseArea {
            id: mover
            anchors.fill: parent; hoverEnabled: true; cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
            property point grab
            onPressed: function (m) { grab = Qt.point(m.x, m.y) }
            onPositionChanged: function (m) {
                if (!pressed) return
                var p = mapToItem(bar, m.x, m.y)
                bar.fx = Math.max(0, Math.min(1, (p.x - grab.x + box.width / 2) / bar.width))
                bar.fy = Math.max(0, Math.min(1, (p.y - grab.y + box.height / 2) / bar.height))
            }
            onReleased: Settings.set("captionsPos", bar.fx.toFixed(4) + "," + bar.fy.toFixed(4))
        }
        // what to do about it, when it can't
        Row {
            id: help; x: 22; y: wordsArea.y + wordsArea.height + 6; spacing: 8
            visible: Captions.state === "no-model" || Captions.state === "no-sound"
            Pill { text: Captions.state === "no-model" ? "Get a Speech Model…" : "Sound Settings…"
                   onClicked: Captions.openSettings(Captions.state === "no-model" ? "input" : "sound") }
        }

        // on the pointer: its settings, and off
        Row {
            anchors { top: parent.top; right: parent.right; topMargin: 6; rightMargin: 6 }
            spacing: 2; opacity: mover.containsMouse || gearHit.containsMouse || offHit.containsMouse ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 140 } }
            Rectangle { width: 26; height: 26; radius: 13; color: gearHit.containsMouse ? Qt.rgba(1, 1, 1, 0.16) : Qt.rgba(1, 1, 1, 0.07)
                Glyph { anchors.centerIn: parent; name: "gear"; size: 14; ink: "#E8ECF0" }
                MouseArea { id: gearHit; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Captions.openSettings("a11y") } }
            Rectangle { width: 26; height: 26; radius: 13; color: offHit.containsMouse ? Qt.rgba(1, 1, 1, 0.16) : Qt.rgba(1, 1, 1, 0.07)
                Glyph { anchors.centerIn: parent; name: "x"; size: 14; ink: "#E8ECF0" }
                MouseArea { id: offHit; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Settings.set("captions", "false") } }
        }
    }

    component Pill: Rectangle {
        property string text
        signal clicked()
        height: 28; width: pt.implicitWidth + 24; radius: 14
        color: ph.containsMouse ? Qt.lighter(Theme.t.accent, 1.12) : Theme.t.accent
        Text { id: pt; anchors.centerIn: parent; text: parent.text; color: Theme.t.onAccent; font.pixelSize: 12; font.weight: Font.DemiBold; font.family: Theme.t.font }
        MouseArea { id: ph; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: parent.clicked() }
    }
}
