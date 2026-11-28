import QtQuick

// The emoji picker (Super+.): type to find one by name, the arrows to move, Enter (or a click) types it into the
// window you were in. Recent ones first; the groups along the top; the skin tone at the bottom right.
Item {
    id: root
    signal done()
    property bool shown: false
    property int current: 0
    property string filter: ""
    readonly property bool have: typeof EmojiPicker !== "undefined" && EmojiPicker !== null
    readonly property var list: have ? EmojiPicker.items : []
    readonly property real presence: card.opacity
    readonly property int cols: 10
    visible: shown || card.opacity > 0.01

    onShownChanged: if (shown) { filter = ""; field.text = ""; current = 0; if (have) EmojiPicker.open(); Qt.callLater(function () { keys.forceActiveFocus() }) }
    function pick(i) { var r = list[i]; if (!r) return; done(); EmojiPicker.insert(r.c) }
    function find(t) { filter = t; field.text = t; current = 0; EmojiPicker.search(t) }

    MouseArea { anchors.fill: parent; onClicked: root.done() }
    Glass {
        id: card; popup: true; dense: true
        width: 24 + root.cols * 46 + 12; height: 470
        anchors.centerIn: parent; anchors.verticalCenterOffset: -40
        opacity: root.shown ? 1 : 0; scale: root.shown ? 1 : 0.97
        Behavior on opacity { NumberAnimation { duration: Theme.t.openMs; easing.type: Easing.OutCubic } }
        Behavior on scale { NumberAnimation { duration: Theme.t.openMs; easing.type: Easing.OutCubic } }
        MouseArea { anchors.fill: parent }

        Item { id: keys; focus: true
            Keys.onPressed: function (e) {
                var n = root.list.length
                if (e.key === Qt.Key_Escape) { if (root.filter) root.find(""); else root.done() }
                else if (e.key === Qt.Key_Right) root.current = Math.min(n - 1, root.current + 1)
                else if (e.key === Qt.Key_Left) root.current = Math.max(0, root.current - 1)
                else if (e.key === Qt.Key_Down) root.current = Math.min(n - 1, root.current + root.cols)
                else if (e.key === Qt.Key_Up) root.current = Math.max(0, root.current - root.cols)
                else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) root.pick(root.current)
                else if (e.key === Qt.Key_Backspace) root.find(field.text.slice(0, -1))
                else if (e.text && e.text >= " " && !(e.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))) root.find(field.text + e.text)
                else return
                e.accepted = true
            } }

        Item { id: head; x: 18; y: 14; width: parent.width - 36; height: 34
            Rectangle { width: parent.width; height: 32; radius: 10; color: Theme.t.hover; anchors.verticalCenter: parent.verticalCenter
                TextInput { id: field; anchors { fill: parent; leftMargin: 12; rightMargin: 12 } verticalAlignment: TextInput.AlignVCenter; color: Theme.t.text
                    font.family: Theme.t.font; font.pixelSize: 13; clip: true; activeFocusOnPress: false; readOnly: true }
                Label { visible: field.text === ""; x: 12; anchors.verticalCenter: parent.verticalCenter; text: "Type to find an emoji or a symbol: heart, arrow, euro…"; secondary: true; font.pixelSize: 12 } } }

        // the groups (hidden while searching)
        Row { id: tabs; x: 14; y: head.y + head.height + 8; spacing: 2; visible: root.filter === ""
            Repeater { model: root.have ? EmojiPicker.groups.slice(0, 11).filter(function (g) { return g.id !== "starred" }) : []
                Pressable { required property var modelData; width: 40; height: 32; radius: 9
                    color: root.have && EmojiPicker.group === modelData.id ? Theme.t.hover : "transparent"
                    onClicked: { EmojiPicker.setGroup(modelData.id); root.current = 0; keys.forceActiveFocus() }
                    Text { anchors.centerIn: parent; text: modelData.mark; font.pixelSize: 17; color: Theme.t.text } } } }

        GridView {
            id: grid
            x: 12; y: (root.filter === "" ? tabs.y + tabs.height : head.y + head.height) + 8; width: root.cols * 46; height: parent.height - y - 46
            cellWidth: 46; cellHeight: 46; clip: true; model: root.list; currentIndex: root.current; boundsBehavior: Flickable.StopAtBounds
            onCurrentIndexChanged: positionViewAtIndex(currentIndex, GridView.Contain)
            delegate: Pressable {
                required property var modelData
                required property int index
                width: 42; height: 42; radius: 10
                color: index === root.current ? Theme.t.hover : "transparent"
                onClicked: root.pick(index)
                onHoveredChanged: if (hovered) root.current = index
                Text { anchors.centerIn: parent; text: parent.modelData.c; font.pixelSize: 24; color: Theme.t.text } }
        }
        Label { visible: root.have && EmojiPicker.ready && root.list.length === 0; anchors.centerIn: grid; secondary: true
            text: root.filter ? "Nothing by that name." : "The ones you use show here." }

        // the one under the pointer or the keys, by name; the skin tone
        Item { x: 18; width: parent.width - 36; height: 30; anchors { bottom: parent.bottom; bottomMargin: 10 }
            Label { anchors.verticalCenter: parent.verticalCenter; width: parent.width - toneRow.width - 12; elide: Text.ElideRight; secondary: true; font.pixelSize: 12
                text: root.list[root.current] ? root.list[root.current].name : "" }
            Row { id: toneRow; anchors { right: parent.right; verticalCenter: parent.verticalCenter } spacing: 2
                Repeater { model: ["✋", "✋🏻", "✋🏼", "✋🏽", "✋🏾", "✋🏿"]
                    Pressable { required property string modelData; required property int index; width: 28; height: 28; radius: 8
                        color: root.have && EmojiPicker.tone === index ? Theme.t.hover : "transparent"
                        onClicked: { EmojiPicker.setTone(index); keys.forceActiveFocus() }
                        Text { anchors.centerIn: parent; text: parent.modelData; font.pixelSize: 15 } } } } }
    }
}
