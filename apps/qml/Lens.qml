import QtQuick
import QtQuick.Window

// Look Up (Super+A; huginn_lens.py): the screen freezes; circle or drag over anything, and its words are read here.
// Then copy them, translate them, search for them, ask Huginn AI, or keep the picture. Esc closes.
Window {
    id: win
    title: "Look Up"
    color: "black"
    flags: Qt.Window | Qt.FramelessWindowHint
    visibility: Window.FullScreen
    width: 1280; height: 800
    property var stroke: []              // the line being drawn, in window coordinates
    property real fx: 0; property real fy: 0; property real fw: 0; property real fh: 0   // what's marked, as shares
    readonly property bool marked: fw > 0 && fh > 0
    property string notice: ""
    property bool noticeBad: false
    Component.onCompleted: { showFullScreen(); keys.forceActiveFocus(); tellScreen() }
    onScreenChanged: tellScreen()
    function tellScreen() { if (Screen.width > 0) Backend.useScreen(Screen.virtualX, Screen.virtualY, Screen.width, Screen.height) }
    Connections { target: Backend; function onSaid(text, bad) { win.notice = text; win.noticeBad = bad; noticeTimer.restart() } }
    Timer { id: noticeTimer; interval: 3500; onTriggered: win.notice = "" }

    Item { id: keys; anchors.fill: parent; focus: true
        Keys.onEscapePressed: { if (win.marked) { win.fw = 0; win.fh = 0; win.stroke = []; Backend.again() } else Qt.quit() }
        Keys.onPressed: function (e) {
            if ((e.modifiers & Qt.ControlModifier) && e.key === Qt.Key_C && Backend.text) { Backend.copyText(Backend.text); e.accepted = true } } }

    Image { id: shot; anchors.fill: parent; source: Backend.image; fillMode: Image.Stretch; cache: false; smooth: true }

    // everything outside what's marked is dimmed (all of it before anything is)
    Rectangle { anchors.fill: parent; color: "#8C000000"; visible: !win.marked }
    Repeater { model: win.marked ? 4 : 0
        Rectangle { required property int index; color: "#8C000000"
            readonly property real sx: win.fx * win.width; readonly property real sy: win.fy * win.height
            readonly property real sw: win.fw * win.width; readonly property real sh: win.fh * win.height
            x: index === 3 ? sx + sw : 0; y: index === 1 ? sy + sh : index === 0 ? 0 : sy
            width: index < 2 ? win.width : index === 2 ? sx : win.width - sx - sw
            height: index === 0 ? sy : index === 1 ? win.height - sy - sh : sh } }
    Rectangle { visible: win.marked; x: win.fx * win.width - 3; y: win.fy * win.height - 3; width: win.fw * win.width + 6; height: win.fh * win.height + 6
        radius: 12; color: "transparent"; border.width: 2; border.color: Theme.t.accent }

    // the line you draw, glowing as it goes
    Canvas { id: ink; anchors.fill: parent; visible: win.stroke.length > 1
        onPaint: { var c = getContext("2d"); c.reset(); var s = win.stroke; if (s.length < 2) return
            c.lineCap = "round"; c.lineJoin = "round"
            for (var pass = 0; pass < 2; pass++) {
                c.strokeStyle = pass === 0 ? Qt.rgba(0.4, 0.75, 1, 0.35) : "#FFFFFF"; c.lineWidth = pass === 0 ? 14 : 4
                c.beginPath(); c.moveTo(s[0].x, s[0].y); for (var i = 1; i < s.length; i++) c.lineTo(s[i].x, s[i].y); c.stroke() } } }
    MouseArea { anchors.fill: parent; cursorShape: Qt.CrossCursor; enabled: Backend.have
        property real sx: 0; property real sy: 0
        onPressed: function (m) { sx = m.x; sy = m.y; win.stroke = [Qt.point(m.x, m.y)]; win.fw = 0; win.fh = 0; Backend.again() }
        onPositionChanged: function (m) { var s = win.stroke; s.push(Qt.point(m.x, m.y)); win.stroke = s; ink.requestPaint() }
        onReleased: function (m) {
            var s = win.stroke, x0 = width, y0 = height, x1 = 0, y1 = 0
            for (var i = 0; i < s.length; i++) { x0 = Math.min(x0, s[i].x); y0 = Math.min(y0, s[i].y); x1 = Math.max(x1, s[i].x); y1 = Math.max(y1, s[i].y) }
            if (x1 - x0 < 12 && y1 - y0 < 12) { x0 = m.x - 220; x1 = m.x + 220; y0 = m.y - 60; y1 = m.y + 60 }      // a click: the words around it
            x0 = Math.max(0, x0 - 8); y0 = Math.max(0, y0 - 8); x1 = Math.min(width, x1 + 8); y1 = Math.min(height, y1 + 8)
            win.fx = x0 / width; win.fy = y0 / height; win.fw = (x1 - x0) / width; win.fh = (y1 - y0) / height
            win.stroke = []; ink.requestPaint()
            Backend.look(win.fx, win.fy, win.fw, win.fh); keys.forceActiveFocus() } }

    // what to do: before anything is marked, how; after, the words and what to do with them
    Rectangle { id: hint; visible: !win.marked; anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 40 }
        width: hintText.width + 44; height: 46; radius: 23; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        Row { anchors.centerIn: parent; spacing: 10
            Glyph { name: "search"; size: 17; ink: Theme.t.accent; anchors.verticalCenter: parent.verticalCenter }
            Label { id: hintText; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 14
                text: Backend.have ? "Circle or drag over anything  ·  click on words  ·  Esc to close" : "Look Up needs Huginn's own session to see the screen.  Esc to close" } } }

    Rectangle {
        id: card; visible: win.marked
        // below what's marked, else above it, else beside it (right, then left), else over its foot
        readonly property real sx: win.fx * win.width
        readonly property real sy: win.fy * win.height
        readonly property real sw: win.fw * win.width
        readonly property real sh: win.fh * win.height
        readonly property string side: sy + sh + 14 + height < win.height - 20 ? "below" : sy - 14 - height > 20 ? "above"
                                       : sx + sw + 14 + width < win.width - 20 ? "right" : sx - 14 - width > 20 ? "left" : "over"
        width: Math.min(560, win.width - 40); height: col.height + 32; radius: 18; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        x: side === "right" ? sx + sw + 14 : side === "left" ? sx - 14 - width : Math.max(20, Math.min(win.width - width - 20, sx + sw / 2 - width / 2))
        y: side === "below" ? sy + sh + 14 : side === "above" ? sy - 14 - height
           : side === "over" ? win.height - height - 20 : Math.max(20, Math.min(win.height - height - 20, sy + sh / 2 - height / 2))
        MouseArea { anchors.fill: parent }                  // (clicks here don't start a new mark)
        Column { id: col; x: 16; y: 16; width: parent.width - 32; spacing: 12
            Row { spacing: 8
                Glyph { name: "doc"; size: 15; ink: Theme.t.text_secondary; anchors.verticalCenter: parent.verticalCenter }
                Label { anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; font.weight: Font.DemiBold; secondary: true
                    text: Backend.reading ? "Reading…" : Backend.text ? "Text" : "No words here" } }
            Rectangle { visible: !!Backend.text; width: parent.width; height: Math.min(150, words.contentHeight + 20); radius: 10; color: Theme.t.group; clip: true
                Flickable { anchors { fill: parent; margins: 10 } contentHeight: words.contentHeight; clip: true; boundsBehavior: Flickable.StopAtBounds
                    TextEdit { id: words; width: parent.width; text: Backend.text; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap
                        color: Theme.t.text; font.family: Theme.t.font; font.pixelSize: 13; selectionColor: Theme.t.accent; selectedTextColor: Theme.t.onAccent } } }
            Flow { width: parent.width; spacing: 8
                Btn { visible: !!Backend.text; primary: true; text: "Copy Text"; onClicked: Backend.copyText(words.selectedText || Backend.text) }
                Btn { visible: !!Backend.text; text: "Translate"; onClicked: { Backend.translate(words.selectedText || Backend.text); Qt.quit() } }
                Btn { visible: !!Backend.text; text: "Search the Web"; onClicked: { Backend.search(words.selectedText || Backend.text); Qt.quit() } }
                Btn { text: "Copy Picture"; onClicked: Backend.copyPicture() }
                Btn { text: "Save Picture"; onClicked: Backend.savePicture() } }
            Item { visible: Backend.aiReady; width: parent.width; height: 36
                Rectangle { anchors { left: parent.left; right: askBtn.left; rightMargin: 8 } height: 36; radius: 10; color: Theme.t.group
                    border.width: 1; border.color: question.activeFocus ? Theme.t.accent : Theme.t.islandLine
                    TextInput { id: question; anchors { fill: parent; leftMargin: 12; rightMargin: 12 } verticalAlignment: TextInput.AlignVCenter; clip: true
                        color: Theme.t.text; font.family: Theme.t.font; font.pixelSize: 13; selectionColor: Theme.t.accent; selectedTextColor: Theme.t.onAccent
                        onAccepted: Backend.ask(Backend.text, text); Keys.onEscapePressed: keys.forceActiveFocus()
                        Label { visible: !question.text; anchors.verticalCenter: parent.verticalCenter; secondary: true; font.pixelSize: 13; text: "Ask Huginn AI about this…" } } }
                Btn { id: askBtn; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; text: Backend.asking ? "Asking…" : "Ask"
                    enabled: !Backend.asking && !Backend.reading; onClicked: Backend.ask(Backend.text, question.text) } }
            Label { visible: !!Backend.answer; width: parent.width; wrapMode: Text.Wrap; font.pixelSize: 13; text: Backend.answer }
        }
    }

    Rectangle { visible: win.notice !== ""; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 40 }
        width: nt.width + 36; height: 40; radius: 20; color: win.noticeBad ? Theme.t.danger : Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        Label { id: nt; anchors.centerIn: parent; text: win.notice; color: win.noticeBad ? "white" : Theme.t.text } }
}
