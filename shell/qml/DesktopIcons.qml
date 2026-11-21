import QtQuick

// The Desktop folder's files, on the desktop (Settings › Desktop & Dock › Files on the desktop): icons on a grid that
// fills from the top right, downwards, so the widgets' side stays clear. Double-click opens; drag one to another cell
// to move it there (it stays), or out to an app or a folder; files dropped here move into the Desktop folder.
// A right-click asks the shell for its menu (Open, Show in Files, Move to Trash).
Item {
    id: desk
    signal menuWanted(var file, real x, real y)
    readonly property int cell: 104
    readonly property int topRoom: 44                   // under the top bar
    readonly property int bottomRoom: 116               // over the dock
    readonly property int columns: Math.max(1, Math.floor((width - 40) / cell))
    readonly property int rows: Math.max(1, Math.floor((height - topRoom - bottomRoom) / cell))
    property string picked: ""                          // the one clicked on
    function cellX(c) { return width - 20 - (c + 1) * cell }
    function cellY(r) { return topRoom + r * cell }
    function cellAt(x, y) {
        return { c: Math.max(0, Math.min(columns - 1, Math.floor((width - 20 - x) / cell))), r: Math.max(0, Math.min(rows - 1, Math.floor((y - topRoom) / cell))) }
    }
    // each file's cell: where it was put if that's on this screen's grid and free, else the next free one
    readonly property var laid: {
        var files = Stacks.desktop || [], places = Stacks.desktopPlaces || {}, taken = {}, out = [], waiting = []
        for (var i = 0; i < files.length; i++) {
            var p = places[files[i].name]
            if (p && p[0] < columns && p[1] < rows && !taken[p[0] + ":" + p[1]]) { taken[p[0] + ":" + p[1]] = true; out.push({ file: files[i], c: p[0], r: p[1] }) }
            else waiting.push(files[i])
        }
        var c = 0, r = 0
        for (var k = 0; k < waiting.length; k++) {
            while (c < columns && taken[c + ":" + r]) { r++; if (r >= rows) { r = 0; c++ } }
            if (c >= columns) break                     // more files than the screen holds: the rest are in Files
            taken[c + ":" + r] = true; out.push({ file: waiting[k], c: c, r: r })
        }
        return out
    }

    DropArea {
        anchors.fill: parent
        onDropped: function (d) {
            var at = desk.cellAt(d.x, d.y)
            if (d.source && d.source.deskName) { Stacks.placeOnDesktop(d.source.deskName, at.c, at.r); d.accept(Qt.IgnoreAction) }
            else if (d.hasUrls) { Stacks.dropOnDesktop(d.urls.map(function (u) { return u.toString() }), at.c, at.r); d.accept(Qt.MoveAction) }
        }
    }
    Repeater {
        model: desk.laid
        Item {
            id: icon
            required property var modelData
            readonly property string deskName: modelData.file.name
            readonly property bool on: desk.picked === deskName
            x: desk.cellX(modelData.c); y: desk.cellY(modelData.r); width: desk.cell; height: desk.cell
            Behavior on x { enabled: !drag.active; NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
            Behavior on y { enabled: !drag.active; NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
            Rectangle { anchors.fill: parent; anchors.margins: 4; radius: 14; color: icon.on ? Qt.rgba(1, 1, 1, 0.16) : hit.containsMouse ? Qt.rgba(1, 1, 1, 0.08) : "transparent"
                border.width: icon.on ? 1 : 0; border.color: Qt.rgba(1, 1, 1, 0.25) }
            FileArt { file: icon.modelData.file; size: 52; anchors.horizontalCenter: parent.horizontalCenter; y: 10 }
            Text { x: 6; y: 66; width: parent.width - 12; height: 32; text: icon.deskName; color: "#FFFFFF"; style: Text.Raised; styleColor: "#B0000000"
                font.pixelSize: 12; font.family: Theme.t.font; font.weight: Font.Medium; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WrapAnywhere
                maximumLineCount: 2; elide: Text.ElideRight; lineHeight: 0.95 }
            MouseArea { id: hit; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton
                onClicked: function (m) {
                    desk.picked = icon.deskName
                    if (m.button === Qt.RightButton) { var p = mapToItem(desk, m.x, m.y); desk.menuWanted(icon.modelData.file, p.x, p.y) }
                }
                onDoubleClicked: function (m) { if (m.button === Qt.LeftButton) Stacks.open(icon.modelData.file.path) } }
            DragHandler { id: drag; target: null }
            Drag.active: drag.active
            Drag.dragType: Drag.Automatic
            Drag.supportedActions: Qt.CopyAction | Qt.MoveAction
            Drag.mimeData: ({ "text/uri-list": icon.modelData.file.url })
        }
    }
}
