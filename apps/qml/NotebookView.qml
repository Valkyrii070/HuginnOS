import QtQuick

// A notebook (.ipynb) as cells, over the tab's own text: Python to run with what it gave under it, and text between.
// Shift+Enter runs a cell and goes to the next; Ctrl+Enter runs it and stays. The file itself is still Jupyter's.
Rectangle {
    id: nbv
    objectName: "notebookView"
    property int tab: -1
    property var host: null                      // Code's window: its colours and its monospace font
    property bool readOnly: false
    signal wantsRaw()
    property var book: ({ ok: false, why: "", cells: [] })
    property string active: ""                   // the id of the cell the cursor is in
    color: host ? host.slab : Theme.t.bg
    readonly property color ink: host ? host.codeInk : Theme.t.text
    function load() {
        book = Backend.notebook(tab)
        var cs = book.cells || [], k = 0
        while (k < cs.length && k < cells.count && cells.get(k).cid === cs[k].id) {
            var row = cells.get(k), outs = JSON.stringify(cs[k].outputs)
            if (row.kind !== cs[k].kind) cells.setProperty(k, "kind", cs[k].kind)
            if (row.count !== cs[k].count) cells.setProperty(k, "count", cs[k].count)
            if (row.state !== cs[k].state) cells.setProperty(k, "state", cs[k].state)
            if (row.outs !== outs) cells.setProperty(k, "outs", outs)
            if (row.source !== cs[k].source && cs[k].id !== active) cells.setProperty(k, "source", cs[k].source)     // (never under the cursor: what is being typed is the newer)
            k++ }
        while (cells.count > k) cells.remove(cells.count - 1)
        for (; k < cs.length; k++) cells.append({ cid: cs[k].id, kind: cs[k].kind, source: cs[k].source, count: cs[k].count, state: cs[k].state, outs: JSON.stringify(cs[k].outputs) })
    }
    function indexOf(cid) { for (var k = 0; k < cells.count; k++) if (cells.get(k).cid === cid) return k; return -1 }
    function focusCell(k) { var it = rep.itemAt(Math.max(0, Math.min(cells.count - 1, k))); if (it) it.takeFocus() }
    function add(at, kind) { var cid = Backend.nbAdd(tab, at, kind); load(); Qt.callLater(function () { nbv.focusCell(nbv.indexOf(cid)) }) }
    function runAndOn(k, stay) {
        var row = cells.get(k)
        if (row.kind === "code") Backend.nbRun(tab, row.cid)
        if (stay) return
        if (k === cells.count - 1) add(cells.count, "code"); else focusCell(k + 1) }
    onTabChanged: { cells.clear(); load() }
    Component.onCompleted: load()
    Connections { target: Backend
        function onNbChanged(i) { if (i === nbv.tab) nbv.load() }
        function onTextLoaded(i) { if (i === nbv.tab) { nbv.active = ""; cells.clear(); nbv.load() } } }
    ListModel { id: cells }
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: function (w) { w.accepted = false } }      // (clicks don't fall through to the text underneath)

    // ---- the bar: run everything, stop, start afresh
    Row { id: bar; x: 14; y: 8; height: 30; spacing: 4; z: 2
        Seg { objectName: "nbRunAll"; icon: "play"; text: "Run All"; visible: nbv.book.ok; onClicked: Backend.nbRunAll(nbv.tab) }
        Seg { icon: "stop"; text: "Stop"; visible: !!nbv.book.busy; onClicked: Backend.nbInterrupt(nbv.tab) }
        Seg { icon: "refresh"; text: "Restart"; tip: "End its Python: every name is forgotten"; visible: !!nbv.book.alive; onClicked: Backend.nbRestart(nbv.tab) }
        Seg { text: "Clear Outputs"; visible: nbv.book.ok && !nbv.readOnly; onClicked: Backend.nbClear(nbv.tab) }
        Seg { icon: "plus"; text: "Code"; visible: nbv.book.ok && !nbv.readOnly; onClicked: nbv.add(nbv.indexOf(nbv.active) < 0 ? cells.count : nbv.indexOf(nbv.active) + 1, "code") }
        Seg { icon: "plus"; text: "Text"; visible: nbv.book.ok && !nbv.readOnly; onClicked: nbv.add(nbv.indexOf(nbv.active) < 0 ? cells.count : nbv.indexOf(nbv.active) + 1, "markdown") } }
    Row { anchors { right: parent.right; rightMargin: 14 } y: 8; height: 30; spacing: 8; z: 2
        Label { anchors.verticalCenter: parent.verticalCenter; secondary: true; font.pixelSize: 11
            text: nbv.book.busy ? "Running…" : nbv.book.alive ? "Python " + (nbv.book.python || "") : nbv.book.ok ? "Python starts at the first run" : "" }
        Seg { objectName: "nbRaw"; text: "As JSON"; tip: "The file's own text"; onClicked: nbv.wantsRaw() } }

    Label { visible: !nbv.book.ok; anchors.centerIn: parent; width: Math.min(parent.width - 80, 460); wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true
        text: (nbv.book.why || "This isn't a notebook.") + "\n\nIts text is still here: As JSON shows it." }

    Flickable { id: flick; visible: nbv.book.ok; anchors { fill: parent; topMargin: 46 } clip: true; contentHeight: col.height + 120; boundsBehavior: Flickable.StopAtBounds
        function reveal(item) {                    // keep the cell with the cursor on screen
            var top = item.mapToItem(col, 0, 0).y, bottom = top + item.height
            if (top < contentY) contentY = Math.max(0, top - 8)
            else if (bottom > contentY + height) contentY = Math.min(Math.max(0, contentHeight - height), top - Math.max(8, height - item.height - 8)) }
        Column { id: col; x: 14; width: flick.width - 28; spacing: 10
            Repeater { id: rep; model: cells
                delegate: Item { id: cell; objectName: "nbCell"
                    required property int index; required property string cid; required property string kind; required property string source
                    required property int count; required property string state; required property string outs
                    readonly property var outputs: { try { return JSON.parse(outs) } catch (e) { return [] } }
                    readonly property bool isCode: kind === "code"
                    readonly property bool here: nbv.active === cid
                    property bool wantsEdit: false
                    readonly property bool editing: isCode || source === "" || wantsEdit          // text cells show as they read until you double-click
                    width: col.width; height: body.height
                    function takeFocus() { wantsEdit = true; input.forceActiveFocus(); flick.reveal(cell) }
                    onKindChanged: restyle()
                    function restyle() { if (isCode && nbv.host) Backend.styleCell({ doc: input.textDocument, lang: "Python", colours: nbv.host.colours() }) }
                    HoverHandler { id: over }
                    // the gutter: run, and the cell's number
                    Item { width: 46; height: Math.max(50, box.height)
                        Item { x: 4; y: 2; width: 30; height: 30
                          Seg { objectName: "nbRun"; visible: cell.isCode; icon: cell.state === "" ? "play" : "stop"; tip: cell.state === "running" ? "Stop" : cell.state === "queued" ? "Waiting its turn" : "Run (Shift+Enter)"
                            onClicked: cell.state === "running" ? Backend.nbInterrupt(nbv.tab) : Backend.nbRun(nbv.tab, cell.cid) } }
                        Label { visible: cell.isCode; x: 0; y: 34; width: 40; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 10; secondary: true
                            text: cell.state === "running" ? "[*]" : cell.state === "queued" ? "[…]" : cell.count > 0 ? "[" + cell.count + "]" : "" } }
                    Column { id: body; x: 46; width: parent.width - 46; spacing: 4; height: Math.max(implicitHeight, cell.isCode ? 50 : 0)
                        Rectangle { id: box; width: parent.width; height: (cell.editing ? input.contentHeight : shown.contentHeight) + 18; radius: 9
                            color: cell.isCode ? Qt.alpha(nbv.ink, 0.05) : "transparent"
                            border.width: cell.here ? 1.5 : cell.isCode ? 1 : 0; border.color: cell.here ? Theme.t.accent : Qt.alpha(nbv.ink, 0.12)
                            TextEdit { id: input; objectName: "nbInput"; visible: cell.editing; x: 10; y: 9; width: parent.width - 20; readOnly: nbv.readOnly
                                text: cell.source; color: nbv.ink; selectionColor: Qt.alpha(Theme.t.accent, 0.35); selectedTextColor: nbv.ink; selectByMouse: true; wrapMode: TextEdit.Wrap; tabStopDistance: 4 * spaceW.advanceWidth
                                font.family: cell.isCode && nbv.host ? nbv.host.mono : Theme.t.font; font.pixelSize: cell.isCode ? Backend.size : Backend.size + 1
                                TextMetrics { id: spaceW; font: input.font; text: " " }
                                Component.onCompleted: cell.restyle()
                                onTextChanged: if (text !== cell.source) { cells.setProperty(cell.index, "source", text); Backend.nbSetSource(nbv.tab, cell.cid, text) }
                                onActiveFocusChanged: { if (activeFocus) nbv.active = cell.cid; else cell.wantsEdit = false }
                                onCursorRectangleChanged: if (activeFocus) { var top = mapToItem(col, 0, cursorRectangle.y).y
                                    if (top < flick.contentY) flick.contentY = Math.max(0, top - 8); else if (top + cursorRectangle.height > flick.contentY + flick.height) flick.contentY = top + cursorRectangle.height - flick.height + 8 }
                                Keys.onPressed: function (e) {
                                    var enter = e.key === Qt.Key_Return || e.key === Qt.Key_Enter
                                    if (enter && (e.modifiers & Qt.ShiftModifier)) { e.accepted = true; cell.wantsEdit = false; nbv.runAndOn(cell.index, false) }
                                    else if (enter && (e.modifiers & Qt.ControlModifier)) { e.accepted = true; cell.wantsEdit = false; if (!cell.isCode) focus = false; nbv.runAndOn(cell.index, true) }
                                    else if (e.key === Qt.Key_Tab && cell.isCode && !readOnly) { e.accepted = true; insert(cursorPosition, "    ") }
                                    else if (enter && cell.isCode && !readOnly && e.modifiers === Qt.NoModifier) {          // a new line keeps the indentation, and goes in one after a colon
                                        e.accepted = true
                                        var before = getText(0, cursorPosition), line = before.substring(before.lastIndexOf("\n") + 1), pad = line.match(/^[ \t]*/)[0]
                                        insert(cursorPosition, "\n" + pad + (/:\s*$/.test(line) ? "    " : "")) }
                                    else if (e.key === Qt.Key_Up && cursorPosition === 0 && cell.index > 0) { e.accepted = true; nbv.focusCell(cell.index - 1) }
                                    else if (e.key === Qt.Key_Down && cursorPosition === length && cell.index < cells.count - 1) { e.accepted = true; nbv.focusCell(cell.index + 1) }
                                    else if (e.key === Qt.Key_Escape) { e.accepted = true; focus = false } } }
                            Text { id: shown; visible: !cell.editing; x: 10; y: 9; width: parent.width - 20; wrapMode: Text.Wrap; textFormat: cell.kind === "markdown" ? Text.MarkdownText : Text.PlainText
                                text: cell.source; color: nbv.ink; font.pixelSize: Backend.size + 1; linkColor: Theme.t.accent; onLinkActivated: function (l) { Qt.openUrlExternally(l) }
                                TapHandler { onDoubleTapped: if (!nbv.readOnly) cell.takeFocus(); onTapped: nbv.active = cell.cid } }
                            // what can be done to this cell, when the pointer or the cursor is on it
                            Rectangle { visible: tools.visible; z: 2; anchors { fill: tools; margins: -2 } radius: 9; color: nbv.color; border.width: 1; border.color: Qt.alpha(nbv.ink, 0.14) }
                            Row { id: tools; visible: (over.hovered || cell.here) && !nbv.readOnly; anchors { right: parent.right; rightMargin: 10 } y: -15; height: 24; spacing: 0; z: 3
                                Seg { height: 24; text: cell.isCode ? "Code" : cell.kind === "markdown" ? "Text" : "Raw"; tip: "Change between code and text"; onClicked: Backend.nbKind(nbv.tab, cell.cid, cell.isCode ? "markdown" : "code") }
                                Seg { height: 24; icon: "up"; tip: "Move up"; onClicked: Backend.nbMove(nbv.tab, cell.cid, -1) }
                                Seg { height: 24; icon: "down"; tip: "Move down"; onClicked: Backend.nbMove(nbv.tab, cell.cid, 1) }
                                Seg { height: 24; icon: "plus"; tip: "A new cell below"; onClicked: nbv.add(cell.index + 1, "code") }
                                Seg { height: 24; icon: "trash"; tip: "Remove this cell"; onClicked: Backend.nbRemove(nbv.tab, cell.cid) } } }
                        // ---- what the cell gave
                        Repeater { model: cell.outputs
                            delegate: Item { id: out; required property var modelData; width: body.width; height: (modelData.kind === "image" ? pic.height : words.contentHeight) + 8
                                Rectangle { visible: out.modelData.kind === "error"; anchors.fill: parent; radius: 7; color: Qt.alpha(nbv.host ? nbv.host.delInk : "#F85149", 0.10) }
                                TextEdit { id: words; objectName: "nbOutput"; visible: out.modelData.kind !== "image"; x: 10; y: 4; width: parent.width - 20; readOnly: true; selectByMouse: true; wrapMode: TextEdit.WrapAnywhere
                                    textFormat: out.modelData.kind === "html" ? TextEdit.RichText : out.modelData.kind === "markdown" ? TextEdit.MarkdownText : TextEdit.PlainText
                                    text: out.modelData.text.length > 60000 && out.modelData.kind !== "html" ? "… (" + (out.modelData.text.length - 60000) + " characters before this aren't shown; they are in the file)\n" + out.modelData.text.slice(-60000) : out.modelData.text
                                    color: nbv.ink; selectionColor: Qt.alpha(Theme.t.accent, 0.35); selectedTextColor: nbv.ink
                                    font.family: out.modelData.kind === "text" || out.modelData.kind === "error" ? (nbv.host ? nbv.host.mono : "monospace") : Theme.t.font; font.pixelSize: Math.max(10, Backend.size - 1) }
                                Image { id: pic; objectName: "nbImage"; visible: out.modelData.kind === "image"; x: 10; y: 4; source: out.modelData.kind === "image" ? out.modelData.src : ""; asynchronous: false; cache: false
                                    fillMode: Image.PreserveAspectFit; width: Math.min(implicitWidth, body.width - 20); height: implicitWidth > 0 ? implicitHeight * width / implicitWidth : 0; smooth: true; mipmap: true } } } } } } } }
}
