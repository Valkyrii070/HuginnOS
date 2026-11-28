import QtQuick

// Terminal, "tab island": near-black with a hint of its colour; the tabs and their actions are the island.
// Ctrl+Shift+T new tab, Ctrl+Shift+W close it, Ctrl+PageUp/PageDown switch.
GlassWindow {
    id: win
    title: "Terminal"; glow: "bottom"; width: 900; height: 580; padTop: 58; padBottom: 60
    baseColor: Theme.t.dark ? Qt.rgba(0.03 + tintColor.r * 0.04, 0.035 + tintColor.g * 0.04, 0.035 + tintColor.b * 0.04, 1) : "#FBFCFA"
    Connections { target: Backend; function onClosed() { win.close() } function onChanged() { stick.restart() } }
    function newTab() { Backend.newTab(); keys.forceActiveFocus() }
    function closeTab() { Backend.closeTab(Backend.current) }
    // What's dragged over with the mouse: from one cell to another (rows as Backend.lines counts them), or null.
    property var sel: null
    readonly property bool hasSel: sel !== null && (sel.r0 !== sel.r1 || sel.c0 !== sel.c1 || sel.word === true)
    function selOrdered() { var s = sel; return (s.r0 < s.r1 || (s.r0 === s.r1 && s.c0 <= s.c1)) ? s : { r0: s.r1, c0: s.c1, r1: s.r0, c1: s.c0 } }
    function copy() { if (hasSel) { var s = selOrdered(); Backend.copyRange(s.r0, s.c0, s.r1, s.c1) } else Backend.copyAll() }
    // the text's size (Ctrl and + or −, Ctrl+0)
    property int fontPx: 13
    function zoom(d) { fontPx = Number(d) === 0 ? 13 : Math.max(8, Math.min(32, fontPx + Number(d))); refit.restart() }
    // Find (Ctrl+Shift+F): the lines with these letters, one at a time
    property bool finding: false
    property var hits: []
    property int hitAt: -1
    function find() { finding = true; findBox.focusIn(); findBox.input.selectAll() }
    function findStep(d) {
        hits = Backend.find(findBox.text)
        if (!hits.length) { hitAt = -1; return }
        hitAt = hitAt < 0 ? hits.length - 1 : (hitAt + d + hits.length) % hits.length
        screen.atEnd = false; screen.positionViewAtIndex(hits[hitAt], ListView.Center)
    }
    function endFind() { finding = false; hits = []; hitAt = -1; keys.forceActiveFocus() }
    function paste() { Backend.paste(); keys.forceActiveFocus() }
    Timer { id: stick; interval: 1; onTriggered: if (screen.atEnd) screen.positionViewAtEnd() }
    islands: [
        Island {
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 14 }
            Repeater { model: Backend.tabs   // the tabs
                Seg { required property string modelData; required property int index; icon: "forward"; text: modelData; on: Backend.current === index
                    onClicked: { Backend.select(index); keys.forceActiveFocus() } } }
            Seg { visible: Backend.tabs.length > 1; icon: "x"; tip: "Close this tab"; onClicked: { Backend.closeTab(Backend.current); keys.forceActiveFocus() } }
            Seg { icon: "plus"; tip: "New tab"; onClicked: { Backend.newTab(); keys.forceActiveFocus() } }
            IslandGap {}
            Label { text: Backend.size; secondary: true; font.pixelSize: 11; font.family: Theme.t.fontMono; leftPadding: 8; rightPadding: 4; anchors.verticalCenter: parent.verticalCenter }
            IslandGap {}
            Seg { icon: "search"; tip: "Find (Ctrl+Shift+F)"; on: win.finding; onClicked: win.finding ? win.endFind() : win.find() }
            Seg { icon: "doc"; text: win.hasSel ? "Copy" : "Copy All"; onClicked: { win.copy(); keys.forceActiveFocus() } }
            Seg { icon: "download"; text: "Paste"; onClicked: { Backend.paste(); keys.forceActiveFocus() } }
        }
    ]
    Label { visible: !Backend.available; anchors.centerIn: parent; width: 380; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true; text: "Terminal needs the “pyte” Python library, which isn't installed on this computer." }
    TextMetrics { id: cell; font: probe.font; text: "MMMMMMMMMM" }
    Text { id: probe; visible: false; font.family: Backend.font; font.pixelSize: win.fontPx; text: "M" }
    readonly property real cellW: cell.advanceWidth / 10
    ListView { id: screen; anchors { fill: parent; leftMargin: 18; rightMargin: 14 } clip: true; model: Backend.lines; boundsBehavior: Flickable.StopAtBounds
        property bool atEnd: true
        onMovementEnded: atEnd = atYEnd
        onWidthChanged: refit.restart(); onHeightChanged: refit.restart()
        delegate: Item { id: row; required property string modelData; required property int index; width: screen.width; height: probe.height
            // the part of this line that's selected, and the line Find is on
            readonly property var s: win.hasSel ? win.selOrdered() : null
            readonly property bool inSel: s !== null && index >= s.r0 && index <= s.r1
            Rectangle { visible: win.hitAt >= 0 && win.hits[win.hitAt] === row.index; width: parent.width; height: parent.height; color: Theme.t.accent; opacity: 0.18 }
            Rectangle { visible: row.inSel; height: parent.height; color: Theme.t.accent; opacity: 0.35
                x: row.inSel && row.index === row.s.r0 ? row.s.c0 * win.cellW : 0
                width: row.inSel ? (row.index === row.s.r1 ? (row.s.c1 + 1) * win.cellW : parent.width) - x : 0 }
            Text { anchors.fill: parent; textFormat: Text.RichText; text: row.modelData; font: probe.font; color: Theme.t.text; renderType: Text.NativeRendering } }
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.MiddleButton | Qt.RightButton; cursorShape: Qt.IBeamCursor
            function cellAt(m) { var r = screen.indexAt(4, screen.contentY + Math.max(0, Math.min(height - 1, m.y)))
                return { r: r < 0 ? screen.count - 1 : r, c: Math.max(0, Math.floor(m.x / win.cellW)) } }
            property var from: null
            onPressed: function (m) { keys.forceActiveFocus(); if (m.button === Qt.LeftButton) { from = cellAt(m); win.sel = null } }
            onPositionChanged: function (m) { if (from && (pressedButtons & Qt.LeftButton)) { var to = cellAt(m); win.sel = { r0: from.r, c0: from.c, r1: to.r, c1: to.c } } }
            onReleased: from = null
            onDoubleClicked: function (m) { var at = cellAt(m), w = Backend.wordAt(at.r, at.c); if (w.length) win.sel = { r0: at.r, c0: w[0], r1: at.r, c1: w[1], word: true } }
            // middle button: paste; right button: copy what's selected, or paste when nothing is
            onClicked: function (m) { if (m.button === Qt.MiddleButton) Backend.paste(); else if (m.button === Qt.RightButton) { if (win.hasSel) { win.copy(); win.sel = null } else Backend.paste() } }
            onWheel: function (w) { screen.contentY = Math.max(screen.originY, Math.min(screen.originY + screen.contentHeight - screen.height, screen.contentY - w.angleDelta.y)); screen.atEnd = screen.atYEnd } } }
    Timer { id: refit; interval: 60; onTriggered: Backend.fit(Math.floor(screen.width / (cell.advanceWidth / 10)), Math.floor(screen.height / probe.height)) }
    Item { id: keys; focus: true
        Keys.onPressed: function (e) {
            if ((e.modifiers & Qt.ControlModifier) && (e.key === Qt.Key_Plus || e.key === Qt.Key_Equal || e.key === Qt.Key_Minus || e.key === Qt.Key_0)) {
                win.zoom(e.key === Qt.Key_0 ? 0 : e.key === Qt.Key_Minus ? -1 : 1); e.accepted = true; return }
            if ((e.modifiers & Qt.ControlModifier) && (e.modifiers & Qt.ShiftModifier)) {
                if (e.key === Qt.Key_V) Backend.paste(); else if (e.key === Qt.Key_C) win.copy(); else if (e.key === Qt.Key_F) win.find()
                else if (e.key === Qt.Key_T) Backend.newTab(); else if (e.key === Qt.Key_W) Backend.closeTab(Backend.current)
                e.accepted = true; return }
            if ((e.modifiers & Qt.ControlModifier) && (e.key === Qt.Key_PageDown || e.key === Qt.Key_PageUp)) { Backend.step(e.key === Qt.Key_PageDown ? 1 : -1); e.accepted = true; return }
            if (e.key !== Qt.Key_Shift && e.key !== Qt.Key_Control && e.key !== Qt.Key_Alt && e.key !== Qt.Key_Meta) win.sel = null
            screen.atEnd = true; Backend.key(e.key, e.modifiers, e.text); e.accepted = true } }
    // Find
    Rectangle { visible: win.finding; z: 5; anchors { right: parent.right; rightMargin: 16; top: parent.top; topMargin: 4 } width: 330; height: 44; radius: 14
        color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        TextBox { id: findBox; x: 6; y: 4; width: 190; placeholder: "Find in what's been printed"; onAccepted: win.findStep(-1); onEdited: { win.hitAt = -1; win.findStep(-1) }
            Keys.onEscapePressed: win.endFind() }
        Label { x: 204; anchors.verticalCenter: parent.verticalCenter; secondary: true; font.pixelSize: 11; text: findBox.text === "" ? "" : win.hits.length ? (win.hitAt + 1) + " of " + win.hits.length : "None" }
        Row { anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter } spacing: 2
            Pressable { width: 26; height: 26; radius: 13; onClicked: win.findStep(-1); Glyph { anchors.centerIn: parent; name: "up"; size: 12 } }
            Pressable { width: 26; height: 26; radius: 13; onClicked: win.findStep(1); Glyph { anchors.centerIn: parent; name: "down"; size: 12 } }
            Pressable { width: 26; height: 26; radius: 13; onClicked: win.endFind(); Glyph { anchors.centerIn: parent; name: "x"; size: 12 } } } }
    Component.onCompleted: { refit.start(); keys.forceActiveFocus() }
}
