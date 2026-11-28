import QtQuick

// Hold Super: every shortcut, grouped, as Settings › Keyboard shortcuts has them now. The compositor says when Super
// has been held on its own for a moment and when it's let go (Shell.qml: "keys-show", "keys-hide"); it takes no
// clicks and no keys, so a shortcut pressed while it shows still works (and the sheet goes).
Item {
    id: sheet
    property bool shown: false
    property var groups: []
    readonly property int colW: 350
    readonly property int gap: 26
    readonly property int cols: Math.max(2, Math.min(4, Math.floor((width - 120 + gap) / (colW + gap))))
    visible: shown || card.opacity > 0.01

    onShownChanged: if (shown) groups = Status.shortcutSheet()

    // the groups into columns, in order (they read down, then across), cut where the tallest column is shortest
    readonly property var columns: {
        var n = groups.length, c = Math.min(cols, n), best = null, bestTall = 1e9
        if (!n) return []
        function size(g) { return g.rows.length + 2 }
        function tryCuts(start, left, acc, tall) {
            if (left === 1) {
                var h = 0
                for (var i = start; i < n; i++) h += size(groups[i])
                var t = Math.max(tall, h)
                if (t < bestTall) { bestTall = t; best = acc.concat([groups.slice(start)]) }
                return
            }
            var run = 0
            for (var end = start + 1; end <= n - left + 1; end++) {
                run += size(groups[end - 1])
                if (Math.max(tall, run) >= bestTall) break
                tryCuts(end, left - 1, acc.concat([groups.slice(start, end)]), Math.max(tall, run))
            }
        }
        tryCuts(0, c, [], 0)
        return best || [groups]
    }

    component Cap: Rectangle {
        property string key: ""
        height: 22; width: Math.max(22, capText.implicitWidth + 12); radius: 6
        color: Theme.t.dark ? Qt.rgba(1, 1, 1, 0.09) : Qt.rgba(0, 0, 0, 0.05)
        border.width: 1; border.color: Theme.t.line
        Rectangle { anchors.bottom: parent.bottom; anchors.horizontalCenter: parent.horizontalCenter; width: parent.width - 4; height: 2; radius: 1
                    color: Theme.t.dark ? Qt.rgba(0, 0, 0, 0.25) : Qt.rgba(0, 0, 0, 0.08) }
        Label { id: capText; anchors.centerIn: parent; anchors.verticalCenterOffset: -1; text: parent.key; font.pixelSize: 12; font.weight: Font.DemiBold }
    }

    Glass {
        id: card; popup: true; dense: true
        width: body.width + 56; height: head.height + body.height + 70
        anchors.centerIn: parent; anchors.verticalCenterOffset: -20
        opacity: sheet.shown ? 1 : 0; scale: sheet.shown ? 1 : 0.97
        Behavior on opacity { NumberAnimation { duration: Theme.t.openMs; easing.type: Easing.OutCubic } }
        Behavior on scale { NumberAnimation { duration: Theme.t.openMs; easing.type: Easing.OutCubic } }

        Row {
            id: head; x: 28; y: 22; spacing: 12
            Rectangle { width: 34; height: 34; radius: 10; color: Theme.t.accent; anchors.verticalCenter: parent.verticalCenter
                Glyph { anchors.centerIn: parent; name: "keyboard"; size: 18; ink: Theme.t.onAccent } }
            Column { anchors.verticalCenter: parent.verticalCenter; spacing: 1
                Label { text: "Shortcuts"; font.pixelSize: 18; font.weight: Font.DemiBold }
                Label { secondary: true; font.pixelSize: 12; text: "Let go of Super to close  ·  change them in Settings › Keyboard" } }
        }
        Row {
            id: body; x: 28; y: head.y + head.height + 20; spacing: sheet.gap
            Repeater {
                model: sheet.columns
                Column {
                    required property var modelData
                    width: sheet.colW; spacing: 16
                    Repeater {
                        model: modelData
                        Column {
                            required property var modelData
                            width: sheet.colW; spacing: 2
                            Label { text: modelData.title; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 0.4; bottomPadding: 4 }
                            Repeater {
                                model: modelData.rows
                                Item {
                                    required property var modelData
                                    width: sheet.colW; height: 28
                                    Label { anchors.left: parent.left; anchors.right: caps.left; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter
                                            text: modelData.label; elide: Text.ElideRight; font.pixelSize: 13 }
                                    Row { id: caps; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 4
                                        Repeater { model: modelData.keys; Cap { required property var modelData; key: modelData } } }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
