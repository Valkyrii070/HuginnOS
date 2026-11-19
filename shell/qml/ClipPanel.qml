import QtQuick

// Clipboard history (Super+V): what you copied lately, newest first. Up and Down to choose, Enter (or a click) pastes
// it into the window you were in; typing narrows the list; Delete forgets one, the pin keeps one for good.
// Off until it's turned on here or in Settings › Privacy & Security; passwords are never kept.
Item {
    id: root
    signal done()
    property bool shown: false
    property int current: 0
    property string filter: ""
    readonly property bool have: typeof ClipHistory !== "undefined" && ClipHistory !== null
    readonly property var all: have ? ClipHistory.items : []
    readonly property var list: { var f = filter.toLowerCase(); return f ? all.filter(function (r) { return r.kind === "text" && (r.preview || "").toLowerCase().indexOf(f) >= 0 }) : all }
    readonly property real presence: card.opacity
    visible: shown || card.opacity > 0.01

    onShownChanged: if (shown) { filter = ""; current = 0; field.text = ""; if (have) ClipHistory.refresh(); Qt.callLater(function () { keys.forceActiveFocus() }) }
    function pick(i) { var r = list[i]; if (!r) return; done(); ClipHistory.pick(r.id) }

    MouseArea { anchors.fill: parent; onClicked: root.done() }
    Glass {
        id: card; popup: true; dense: true
        width: 560; height: Math.min(parent.height - 160, root.have && ClipHistory.on ? Math.max(200, head.height + 24 + Math.min(listView.contentHeight, 470) + 24) : 250)
        anchors.centerIn: parent; anchors.verticalCenterOffset: -40
        opacity: root.shown ? 1 : 0; scale: root.shown ? 1 : 0.97
        Behavior on opacity { NumberAnimation { duration: Theme.t.openMs; easing.type: Easing.OutCubic } }
        Behavior on scale { NumberAnimation { duration: Theme.t.openMs; easing.type: Easing.OutCubic } }
        MouseArea { anchors.fill: parent }

        Item { id: keys; focus: true
            Keys.onPressed: function (e) {
                if (e.key === Qt.Key_Escape) { if (root.filter) { root.filter = ""; field.text = "" } else root.done() }
                else if (e.key === Qt.Key_Down) root.current = Math.min(root.list.length - 1, root.current + 1)
                else if (e.key === Qt.Key_Up) root.current = Math.max(0, root.current - 1)
                else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) root.pick(root.current)
                else if (e.key === Qt.Key_Delete && root.list[root.current]) ClipHistory.remove(root.list[root.current].id)
                else if (e.key === Qt.Key_Backspace) { field.text = field.text.slice(0, -1); root.filter = field.text; root.current = 0 }
                else if (e.text && e.text >= " " && !(e.modifiers & (Qt.ControlModifier | Qt.AltModifier))) { field.text += e.text; root.filter = field.text; root.current = 0 }
                else return
                e.accepted = true
            } }

        Item { id: head; x: 18; y: 14; width: parent.width - 36; height: 34
            Label { text: "Clipboard"; font.pixelSize: 17; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
            Rectangle { visible: root.have && ClipHistory.on; x: 110; width: parent.width - 110 - clearBtn.width - 10; height: 30; radius: 10; color: Theme.t.hover; anchors.verticalCenter: parent.verticalCenter
                TextInput { id: field; anchors { fill: parent; leftMargin: 10; rightMargin: 10 } verticalAlignment: TextInput.AlignVCenter; color: Theme.t.text; font.family: Theme.t.font; font.pixelSize: 13
                    clip: true; activeFocusOnPress: false; readOnly: true }
                Label { visible: field.text === ""; x: 10; anchors.verticalCenter: parent.verticalCenter; text: "Type to find something you copied"; secondary: true; font.pixelSize: 12 } }
            Pressable { id: clearBtn; visible: root.have && ClipHistory.on && root.all.length > 0; anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                width: clearLabel.width + 20; height: 30; radius: 10; onClicked: ClipHistory.clearAll()
                Label { id: clearLabel; anchors.centerIn: parent; text: "Clear"; font.pixelSize: 12 } } }

        // off: what it is, and the switch
        Column { visible: root.have && !ClipHistory.on; x: 24; y: 64; width: parent.width - 48; spacing: 12
            Label { width: parent.width; wrapMode: Text.WordWrap; text: "Turn on clipboard history to keep the last 50 things you copy, text and pictures, and paste any of them again from here."; font.pixelSize: 14 }
            Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                text: "It stays on this computer, only you can read it, and passwords copied from Passwords or other password managers are never kept. Settings › Privacy & Security turns it off again." }
            Pressable { width: onLabel.width + 30; height: 34; radius: 11; color: Theme.t.accent; onClicked: ClipHistory.setOn(true)
                Label { id: onLabel; anchors.centerIn: parent; text: "Turn On"; color: Theme.t.onAccent; font.weight: Font.DemiBold } } }
        Label { visible: root.have && ClipHistory.on && root.list.length === 0; anchors.centerIn: parent; anchors.verticalCenterOffset: 20; secondary: true
            text: root.filter ? "Nothing you copied has that in it." : "Copy something, and it shows here." }

        ListView {
            id: listView; visible: root.have && ClipHistory.on
            x: 12; y: head.y + head.height + 12; width: parent.width - 24; height: parent.height - y - 12; clip: true; spacing: 4
            model: root.list; currentIndex: root.current; boundsBehavior: Flickable.StopAtBounds
            onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
            delegate: Pressable {
                id: row
                required property var modelData
                required property int index
                readonly property bool here: index === root.current
                width: listView.width; height: modelData.kind === "image" ? 96 : Math.min(84, 26 + 18 * Math.min(3, modelData.lines || 1)); radius: 12
                color: here ? Theme.t.hover : "transparent"
                onClicked: root.pick(index)
                Image { visible: row.modelData.kind === "image"; x: 12; y: 8; height: parent.height - 16; width: Math.min(260, height * (row.modelData.w || 4) / Math.max(1, row.modelData.h || 3))
                    source: row.modelData.url || ""; fillMode: Image.PreserveAspectFit; asynchronous: true; sourceSize.height: 160 }
                Label { visible: row.modelData.kind === "text"; x: 14; y: 9; width: parent.width - 120; maximumLineCount: 3; elide: Text.ElideRight; wrapMode: Text.WrapAnywhere
                    text: (row.modelData.preview || "").replace(/\t/g, "  "); font.pixelSize: 13; textFormat: Text.PlainText }
                Label { anchors { right: parent.right; rightMargin: 74; top: parent.top; topMargin: 9 } text: row.modelData.when; secondary: true; font.pixelSize: 11 }
                Row { anchors { right: parent.right; rightMargin: 8; top: parent.top; topMargin: 4 } spacing: 2
                    Pressable { width: 28; height: 28; radius: 9; opacity: row.modelData.pinned || row.hovered || row.here ? 1 : 0
                        onClicked: ClipHistory.pin(row.modelData.id, !row.modelData.pinned)
                        Glyph { anchors.centerIn: parent; name: "pin"; size: 14; ink: row.modelData.pinned ? Theme.t.accent : Theme.t.icon } }
                    Pressable { width: 28; height: 28; radius: 9; opacity: row.hovered || row.here ? 1 : 0; onClicked: ClipHistory.remove(row.modelData.id)
                        Glyph { anchors.centerIn: parent; name: "x"; size: 13; ink: Theme.t.icon } } } }
        }
    }
}
