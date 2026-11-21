import QtQuick

// Layouts (Super+Z): the window that was in front, into a part of any screen; and window sets, the windows on screen
// kept under a name (Gaming, Writing) and put back later, apps started where they aren't running. The parts are
// the compositor's own (wm.rs: Snap), so a window put in one keeps it when its screen comes and goes.
Item {
    id: lay
    signal done()
    property bool shown: false
    property string forId: ""                   // the window it's for: the one in front when it opened
    property string screen: ""                  // the screen picked (the window's own at first)
    property string why: ""
    readonly property var win: { var a = Status.windows || []; for (var i = 0; i < a.length; i++) if (a[i].id === forId) return a[i]; return null }
    readonly property var screens: Status.screenList || []
    readonly property real presence: card.opacity
    visible: shown || card.opacity > 0.01

    onShownChanged: if (shown) {
        why = ""; field.text = ""
        screen = win && win.screen ? win.screen : (screens.length ? screens[0].name : "")
        Qt.callLater(function () { keys.forceActiveFocus() })
    }
    function snapTo(part) {
        if (!win) return
        Status.windowDo(win.id, "snap:" + part + (lay.screen && lay.screens.length > 1 ? "@" + lay.screen : ""))
        done()
    }
    function keep() {
        var w = Status.saveWindowSet(field.text)
        if (w) why = w
        else { field.text = ""; why = "" }
    }
    function putBack(name) {
        var start = Status.putBackWindowSet(name)
        var apps = Apps.all || []
        for (var i = 0; i < start.length; i++)
            for (var k = 0; k < apps.length; k++) if (apps[k].name === start[i]) { Apps.launch(apps[k].exec); break }
        done()
    }

    MouseArea { anchors.fill: parent; onClicked: lay.done() }
    Glass {
        id: card; popup: true; dense: true
        width: 620; height: col.height + 36
        anchors.horizontalCenter: parent.horizontalCenter; y: Math.max(48, (parent.height - height) / 2 - 60)
        opacity: lay.shown ? 1 : 0; scale: lay.shown ? 1 : 0.97
        Behavior on opacity { NumberAnimation { duration: Theme.t.openMs; easing.type: Easing.OutCubic } }
        Behavior on scale { NumberAnimation { duration: Theme.t.openMs; easing.type: Easing.OutCubic } }
        MouseArea { anchors.fill: parent }

        Item { id: keys; focus: true
            Keys.onPressed: function (e) {
                if (e.key === Qt.Key_Escape) lay.done()
                else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { if (field.text.trim() !== "") lay.keep() }
                else if (e.key === Qt.Key_Backspace) field.text = field.text.slice(0, -1)
                else if (e.text && e.text >= " " && !(e.modifiers & (Qt.ControlModifier | Qt.AltModifier))) field.text += e.text
                else return
                e.accepted = true
            } }

        Column {
            id: col; x: 18; y: 18; width: parent.width - 36; spacing: 14
            Column { width: parent.width; spacing: 2
                Label { text: "Layouts"; font.pixelSize: 17; font.weight: Font.DemiBold }
                Label { width: parent.width; elide: Text.ElideRight; secondary: true; font.pixelSize: 12
                    text: lay.win ? ((lay.win.name || lay.win.appId) + (lay.win.title && lay.win.title !== (lay.win.name || lay.win.appId) ? "  ·  " + lay.win.title : "")) : "No window was in front. Click one, then press Super+Z." } }

            // which screen: the window's own, or another
            Row { visible: lay.screens.length > 1; spacing: 6
                Repeater { model: lay.screens
                    Pressable { required property var modelData; required property int index
                        readonly property bool picked: lay.screen === modelData.name
                        width: scrLabel.width + 26; height: 30; radius: 10; active: picked
                        onClicked: lay.screen = modelData.name
                        Label { id: scrLabel; anchors.centerIn: parent; font.pixelSize: 12; font.weight: parent.picked ? Font.DemiBold : Font.Normal
                            color: parent.picked ? Theme.t.onAccent : Theme.t.text
                            text: "Screen " + (parent.index + 1) + (lay.win && lay.win.screen === parent.modelData.name ? " · it's here" : "") } } } }

            // the parts: each template's pieces are buttons
            Grid {
                columns: 3; spacing: 10; opacity: lay.win ? 1 : 0.45; enabled: !!lay.win
                Repeater {
                    model: [[["left", 0, 0, .5, 1], ["right", .5, 0, .5, 1]],
                            [["left-third", 0, 0, 1 / 3, 1], ["middle-third", 1 / 3, 0, 1 / 3, 1], ["right-third", 2 / 3, 0, 1 / 3, 1]],
                            [["left-two-thirds", 0, 0, 2 / 3, 1], ["right-third", 2 / 3, 0, 1 / 3, 1]],
                            [["left-third", 0, 0, 1 / 3, 1], ["right-two-thirds", 1 / 3, 0, 2 / 3, 1]],
                            [["top-left", 0, 0, .5, .5], ["top-right", .5, 0, .5, .5], ["bottom-left", 0, .5, .5, .5], ["bottom-right", .5, .5, .5, .5]],
                            [["top-half", 0, 0, 1, .5], ["bottom-half", 0, .5, 1, .5]]]
                    Rectangle {
                        id: tpl; required property var modelData
                        width: (col.width - 20) / 3; height: 96; radius: 12; color: Theme.t.hover; border.width: 1; border.color: Theme.t.line
                        Repeater { model: tpl.modelData
                            Rectangle { required property var modelData
                                x: 6 + modelData[1] * (tpl.width - 12) + (modelData[1] > 0 ? 2 : 0)
                                y: 6 + modelData[2] * (tpl.height - 12) + (modelData[2] > 0 ? 2 : 0)
                                width: modelData[3] * (tpl.width - 12) - (modelData[1] > 0 ? 2 : 0) - (modelData[1] + modelData[3] < 0.999 ? 2 : 0)
                                height: modelData[4] * (tpl.height - 12) - (modelData[2] > 0 ? 2 : 0) - (modelData[2] + modelData[4] < 0.999 ? 2 : 0)
                                radius: 7
                                color: partHit.containsMouse ? Theme.t.accent : (Theme.t.dark ? Qt.rgba(1, 1, 1, 0.10) : Qt.rgba(0, 0, 0, 0.07))
                                border.width: 1; border.color: partHit.containsMouse ? Theme.t.accent : Theme.t.line
                                MouseArea { id: partHit; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: lay.snapTo(parent.modelData[0]) } } } } } }
            Pressable { width: parent.width; height: 34; radius: 10; opacity: lay.win ? 1 : 0.45; enabled: !!lay.win; color: hovered ? Theme.t.hover : Theme.t.group
                onClicked: lay.snapTo("max")
                Label { anchors.centerIn: parent; text: "Fill the screen"; font.pixelSize: 13 } }

            Rectangle { width: parent.width; height: 1; color: Theme.t.line }

            // window sets
            Column { width: parent.width; spacing: 4
                Label { text: "Window sets"; font.pixelSize: 15; font.weight: Font.DemiBold }
                Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                    text: "Keep the windows on every screen as they are now, then put them all back in one go. Apps that aren't running are started." } }
            Row { width: parent.width; spacing: 8
                Rectangle { width: parent.width - keepBtn.width - 8; height: 34; radius: 10; color: Theme.t.hover
                    TextInput { id: field; anchors { fill: parent; leftMargin: 12; rightMargin: 12 } verticalAlignment: TextInput.AlignVCenter; color: Theme.t.text
                        font.family: Theme.t.font; font.pixelSize: 13; clip: true; activeFocusOnPress: false; readOnly: true; maximumLength: 40 }
                    Label { visible: field.text === ""; x: 12; anchors.verticalCenter: parent.verticalCenter; secondary: true; font.pixelSize: 12; text: "Type a name, like Gaming or Writing" } }
                Pressable { id: keepBtn; width: keepLabel.width + 26; height: 34; radius: 10; color: field.text.trim() !== "" ? Theme.t.accent : Theme.t.group
                    onClicked: if (field.text.trim() !== "") lay.keep()
                    Label { id: keepLabel; anchors.centerIn: parent; text: "Keep These Windows"; font.pixelSize: 12; font.weight: Font.DemiBold
                        color: field.text.trim() !== "" ? Theme.t.onAccent : Theme.t.text } } }
            Label { visible: lay.why !== ""; width: parent.width; wrapMode: Text.WordWrap; color: Theme.t.danger; font.pixelSize: 12; text: lay.why }
            Column { width: parent.width; spacing: 6
                Repeater { model: Status.windowSets
                    Rectangle { required property var modelData; width: parent.width; height: 50; radius: 12; color: Theme.t.group
                        Column { x: 14; width: parent.width - 14 - putBtn.width - 52; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                            Label { width: parent.width; elide: Text.ElideRight; text: modelData.name; font.pixelSize: 13; font.weight: Font.DemiBold }
                            Label { width: parent.width; elide: Text.ElideRight; secondary: true; font.pixelSize: 11
                                text: modelData.count + (modelData.count === 1 ? " window" : " windows") + (modelData.screens > 1 ? " on " + modelData.screens + " screens" : "") + (modelData.apps ? "  ·  " + modelData.apps : "") } }
                        Pressable { id: putBtn; anchors { right: forget.left; rightMargin: 6; verticalCenter: parent.verticalCenter } width: putLabel.width + 24; height: 30; radius: 9
                            color: hovered ? Qt.alpha(Theme.t.accent, 0.3) : Qt.alpha(Theme.t.accent, 0.18); onClicked: lay.putBack(parent.modelData.name)
                            Label { id: putLabel; anchors.centerIn: parent; text: "Put Back"; font.pixelSize: 12; font.weight: Font.DemiBold } }
                        Pressable { id: forget; anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } width: 30; height: 30; radius: 9
                            onClicked: Status.removeWindowSet(parent.modelData.name)
                            Glyph { anchors.centerIn: parent; name: "x"; size: 12 } } } } }
        }
    }
}
