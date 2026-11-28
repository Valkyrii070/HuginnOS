import QtQuick
import QtQuick.Window

// Huginn's pinentry (huginn_pinentry.py): GnuPG asking for a passphrase or a PIN, or for a yes. The same glass card
// as the administrator's password prompt, the realm's glow along its top, a key instead of a lock.
Window {
    id: win
    visible: Pin.active
    width: 480; height: card.height + 24
    flags: Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    color: "transparent"
    title: Pin.title
    onVisibleChanged: if (visible) { pass.text = ""; again.text = ""; Qt.callLater(function () { if (Pin.kindName === "pin") pass.focusIn(); win.requestActivate() }) }
    Component.onCompleted: if (visible) Qt.callLater(function () { pass.focusIn(); win.requestActivate() })
    readonly property string err: Pin.error
    onErrChanged: if (err !== "") { shake.restart(); again.text = "" }
    function go() { if (Pin.kindName !== "pin" || pass.text !== "" ) Pin.give(pass.text, again.text) }

    Rectangle {
        id: card
        objectName: "card"
        x: 12; y: 12; width: parent.width - 24; height: col.height + 44; radius: 20
        color: Theme.t.dark ? Qt.rgba(0.11, 0.13, 0.15, 0.97) : Qt.rgba(0.98, 0.98, 0.99, 0.98)
        border.width: 1; border.color: Theme.t.islandLine
        transform: Translate { id: nudge }
        SequentialAnimation { id: shake
            NumberAnimation { target: nudge; property: "x"; to: 12; duration: 50 } NumberAnimation { target: nudge; property: "x"; to: -10; duration: 60 }
            NumberAnimation { target: nudge; property: "x"; to: 6; duration: 60 } NumberAnimation { target: nudge; property: "x"; to: 0; duration: 50 } }
        Rectangle { anchors { left: parent.left; right: parent.right; top: parent.top; margins: 1 } height: 70; radius: 20
            gradient: Gradient { GradientStop { position: 0; color: Qt.alpha(Theme.t.accent, 0.16) } GradientStop { position: 1; color: "transparent" } } }
        MouseArea { anchors.fill: parent; property point p0
            onPressed: function (m) { p0 = Qt.point(m.x, m.y) }
            onPositionChanged: function (m) { win.x += m.x - p0.x; win.y += m.y - p0.y } }

        Column { id: col; x: 22; y: 22; width: parent.width - 44; spacing: 12
            Row { spacing: 14; width: parent.width
                Rectangle { width: 46; height: 46; radius: 15; color: Qt.alpha(Theme.t.accent, 0.18)
                    Glyph { anchors.centerIn: parent; name: "key"; size: 24; ink: Theme.t.accent } }
                Column { width: parent.width - 60; spacing: 3; anchors.verticalCenter: parent.verticalCenter
                    Label { objectName: "title"; width: parent.width; wrapMode: Text.WordWrap; text: Pin.title; font.pixelSize: 15; font.weight: Font.DemiBold }
                    Label { objectName: "desc"; visible: Pin.desc !== ""; width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12; text: Pin.desc } } }
            TextBox { id: pass; objectName: "passphrase"; visible: Pin.kindName === "pin"; width: parent.width; height: 40; secret: true; placeholder: Pin.prompt
                onAccepted: if (again.visible) again.focusIn(); else win.go() }
            TextBox { id: again; objectName: "again"; visible: Pin.kindName === "pin" && Pin.repeat !== ""; width: parent.width; height: 40; secret: true; placeholder: Pin.repeat.replace(/:$/, "")
                onAccepted: win.go() }
            Label { objectName: "error"; visible: Pin.error !== ""; width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 12; color: Theme.t.danger; text: Pin.error }
            Row { anchors.right: parent.right; spacing: 8
                Btn { objectName: "cancel"; visible: Pin.kindName !== "message"; text: Pin.cancelText; onClicked: Pin.refuse() }
                Btn { objectName: "ok"; text: Pin.okText; primary: true; opacity: Pin.kindName !== "pin" || pass.text !== "" ? 1 : 0.5; onClicked: win.go() } } } }
    Shortcut { sequence: "Escape"; onActivated: Pin.refuse() }
}
