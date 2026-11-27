import QtQuick

// Arriving on the desktop: the sign-in screen's last picture carries on for a moment where it was (its dock, with
// places for your apps lit either side of your picture) while the desktop's own pieces come in, then it fades away
// and the real dock is there. The wallpaper behind is the same scene, coming to rest. Nothing here takes clicks.
// (shell/qml/GreeterView.qml draws the sign-in screen and its wake; this matches where that ends.)
Item {
    id: arrival
    property bool playing: true
    signal finished()
    signal leaving()                       // the sign-in screen's dock starts to fade: time for the desktop's pieces to come in
    visible: opacity > 0
    opacity: 1
    Timer { running: arrival.playing; interval: 650; onTriggered: { arrival.leaving(); leave.start() } }
    ParallelAnimation { id: leave
        NumberAnimation { target: arrival; property: "opacity"; to: 0; duration: 520; easing.type: Easing.InOutQuad }
        NumberAnimation { target: card; property: "scale"; to: 0.97; duration: 520; easing.type: Easing.InCubic }
        onFinished: arrival.finished() }

    Rectangle {
        id: card
        objectName: "arrivalCard"
        width: Math.min(780, parent.width - 40); height: 80; radius: 28
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 28 }
        color: Qt.rgba(0.08, 0.08, 0.13, 0.62); border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.16)
        Row { anchors.centerIn: parent; spacing: 10
            Repeater { model: 11
                Item { required property int index; readonly property bool mid: index === 5
                    width: mid ? 64 : 52; height: 56; anchors.verticalCenter: parent.verticalCenter
                    Rectangle { visible: !parent.mid; anchors.centerIn: parent; width: 52; height: 52; radius: 14
                        color: Qt.rgba(1, 1, 1, 0.16); border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.24) }
                    Item { visible: parent.mid; anchors.centerIn: parent; width: 56; height: 56
                        Rectangle { anchors.centerIn: parent; width: 76; height: 76; radius: 38; color: Theme.t.accent; opacity: 0.28 }
                        Rectangle { id: disc; anchors.fill: parent; radius: width / 2; color: Qt.darker(Theme.t.accent, 3.2); border.width: 2; border.color: Theme.t.accent
                            Text { anchors.centerIn: parent; visible: Me.face === ""; color: "#F5F7FA"; font.pixelSize: 19; font.weight: Font.DemiBold
                                text: { var n = (Me.name || "?").trim().split(/\s+/); return (n[0][0] + (n.length > 1 ? n[n.length - 1][0] : "")).toUpperCase() } }
                            Canvas { anchors { fill: parent; margins: 3 } visible: Me.face !== ""
                                Component.onCompleted: if (Me.face) loadImage(Me.face)
                                onImageLoaded: requestPaint()
                                onPaint: { var c = getContext("2d"); c.reset(); if (!Me.face || !isImageLoaded(Me.face)) return
                                    c.beginPath(); c.arc(width / 2, height / 2, width / 2, 0, Math.PI * 2); c.clip(); c.drawImage(Me.face, 0, 0, width, height) } } } } } }
        }
    }
}
