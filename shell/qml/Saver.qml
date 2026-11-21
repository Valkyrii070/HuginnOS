import QtQuick

// The screen saver on one screen (Settings › Appearance › Screen saver): the time, your photos, or the realm's scene
// moving, shown by the shell when the session daemon says the computer was left alone. Any key or movement ends it.
Item {
    id: sv
    property string mode: "clock"
    property var photos: []
    property bool main: true
    signal done()
    property date now: new Date()
    Timer { interval: 1000; running: sv.visible; repeat: true; triggeredOnStart: true; onTriggered: sv.now = new Date() }

    Rectangle { anchors.fill: parent; color: "black" }

    // the realm's scene, moving (or behind the photos when there are none)
    Loader { anchors.fill: parent; active: sv.mode === "wallpaper" || (sv.mode === "photos" && sv.photos.length === 0)
        sourceComponent: Component { Wallpaper { forceMoving: true } } }
    Rectangle { anchors.fill: parent; visible: sv.mode === "wallpaper"; color: "#40000000" }

    // photos: one after another, slowly drifting, crossfading
    property int shown: 0
    property var order: []
    function shuffle() { var a = photos.slice(); for (var i = a.length - 1; i > 0; i--) { var j = Math.floor(Math.random() * (i + 1)); var t = a[i]; a[i] = a[j]; a[j] = t } order = a }
    onPhotosChanged: { shuffle(); shown = 0 }
    Timer { interval: 9000; running: sv.visible && sv.mode === "photos" && sv.order.length > 1; repeat: true
        onTriggered: { sv.shown = (sv.shown + 1) % sv.order.length; (sv.shown % 2 ? sv.b : sv.a).source = sv.order[sv.shown] } }
    Repeater { model: 2
        Image { id: img; required property int index
            anchors.centerIn: parent; width: parent.width * 1.08; height: parent.height * 1.08
            fillMode: Image.PreserveAspectCrop; asynchronous: true; cache: false; sourceSize.width: 2560
            visible: sv.mode === "photos"
            opacity: (sv.shown % 2) === index && status === Image.Ready ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 1800; easing.type: Easing.InOutQuad } }
            Component.onCompleted: { if (index === 0) sv.a = img; else sv.b = img; if (index === 0 && sv.order.length) source = sv.order[0] }
            NumberAnimation on scale { running: sv.visible && sv.mode === "photos"; from: 1.0; to: 1.06; duration: 18000; loops: Animation.Infinite; easing.type: Easing.InOutSine } } }
    property Image a: null
    property Image b: null
    onOrderChanged: if (a && order.length) a.source = order[0]

    // the time: large, and moving a little every minute so nothing stays put on the screen
    property real driftX: 0.5
    property real driftY: 0.46
    Timer { interval: 60000; running: sv.visible; repeat: true; onTriggered: { sv.driftX = 0.3 + Math.random() * 0.4; sv.driftY = 0.3 + Math.random() * 0.4 } }
    Column {
        visible: sv.main || sv.mode === "clock"
        readonly property bool big: sv.mode === "clock"
        x: big ? sv.width * sv.driftX - width / 2 : 48; y: big ? sv.height * sv.driftY - height / 2 : sv.height - height - 48
        Behavior on x { NumberAnimation { duration: 4000; easing.type: Easing.InOutSine } }
        Behavior on y { NumberAnimation { duration: 4000; easing.type: Easing.InOutSine } }
        spacing: 4
        Text { anchors.horizontalCenter: parent.big ? parent.horizontalCenter : undefined
            text: Qt.formatTime(sv.now, Settings.clock24 ? "HH:mm" : "h:mm"); color: "white"; opacity: 0.92
            font.family: Theme.t.font; font.pixelSize: parent.big ? Math.min(sv.height * 0.22, 220) : 64; font.weight: Font.Light
            style: Text.Raised; styleColor: "#40000000" }
        Text { anchors.horizontalCenter: parent.big ? parent.horizontalCenter : undefined
            text: Qt.formatDate(sv.now, "dddd d MMMM"); color: "white"; opacity: 0.7
            font.family: Theme.t.font; font.pixelSize: parent.big ? 26 : 18 }
    }
}
