import QtQuick

// A box to type in: one line, or several with `lines` above 1. `secret` hides what is typed, and gives the box an
// eye at its right end: click it to see what you've typed (and again to hide it).
Rectangle {
    id: box
    property alias text: one.text
    property alias input: one
    property string placeholder: ""
    property bool secret: false
    property bool shown: false                  // a secret, shown for the moment (the eye)
    onVisibleChanged: if (!visible) shown = false
    property bool mono: false
    property int lines: 1
    property string many: ""                    // the text, when lines > 1
    signal accepted()
    signal edited()
    function focusIn() { (lines > 1 ? area : one).forceActiveFocus() }
    width: 280; height: lines > 1 ? 16 + lines * 18 : 36; radius: 10; color: Theme.t.group
    border.width: 1; border.color: one.activeFocus || area.activeFocus ? Theme.t.accent : Theme.t.islandLine
    TextInput { id: one; visible: box.lines === 1; activeFocusOnTab: true; anchors { fill: parent; leftMargin: 12; rightMargin: box.secret ? 38 : 12 } verticalAlignment: TextInput.AlignVCenter; clip: true
        echoMode: box.secret && !box.shown ? TextInput.Password : TextInput.Normal; color: Theme.t.text; font.family: box.mono ? Theme.t.fontMono : Theme.t.font; font.pixelSize: 14
        selectionColor: Theme.t.accent; selectedTextColor: Theme.t.onAccent; selectByMouse: true; onAccepted: box.accepted(); onTextEdited: box.edited() }
    Flickable { visible: box.lines > 1; anchors { fill: parent; margins: 8 } clip: true; contentHeight: area.height
        TextEdit { id: area; width: parent.width; text: box.many; onTextChanged: if (box.many !== text) { box.many = text; box.edited() } wrapMode: TextEdit.Wrap; color: Theme.t.text
            font.family: Theme.t.font; font.pixelSize: 13; selectionColor: Theme.t.accent; selectedTextColor: Theme.t.onAccent; selectByMouse: true } }
    Item { visible: box.secret && box.lines === 1; objectName: "eye"; anchors { right: parent.right; rightMargin: 5; verticalCenter: parent.verticalCenter } width: 28; height: 28
        Accessible.role: Accessible.Button; Accessible.name: box.shown ? "Hide what's typed" : "Show what's typed"
        Rectangle { anchors.fill: parent; radius: 8; color: eyeArea.containsMouse ? Theme.t.hover : "transparent" }
        Glyph { anchors.centerIn: parent; name: "eye"; size: 17; ink: box.shown ? Theme.t.accent : Theme.t.text_secondary }
        Rectangle { visible: !box.shown; anchors.centerIn: parent; width: 20; height: 1.7; radius: 1; rotation: -40; color: Theme.t.text_secondary }   // hidden: the eye is struck through
        MouseArea { id: eyeArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { box.shown = !box.shown; one.forceActiveFocus() } } }
    Label { visible: box.lines === 1 ? !one.text : !box.many; x: 12; y: box.lines > 1 ? 9 : (parent.height - height) / 2; secondary: true; text: box.placeholder }
}
