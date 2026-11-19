import QtQuick

// Sheets, "glass grid": the sheet is a sheet of paper laid on the glass, lit from the formula island at the top.
// Up to four panes (rows and columns frozen at the top and left, and the rest), each a TableView of the same cells.
GlassWindow {
    id: win
    title: "Sheets"; heading: Backend.title || ""; glow: "top"; width: 1280; height: 840; minimumWidth: 860
    // the selection: where it began (the active cell) and where it runs to, in the sheet's own rows and columns
    property int ar: 0
    property int ac: 0
    property int cr: 0
    property int cc: 0
    readonly property int r0: Math.min(ar, cr)
    readonly property int r1: Math.max(ar, cr)
    readonly property int c0: Math.min(ac, cc)
    readonly property int c1: Math.max(ac, cc)
    property bool editing: false
    property bool inBar: false              // the typing is in the formula island, not the cell
    property string notice: ""
    property string exported: ""
    property bool railOpen: true
    property string pop: ""
    property Item popFrom: null
    property var menu: null                 // the right-click menu: {x, y}
    property int fillR: -1                  // where the fill handle is being dragged to
    property int fillC: -1
    property var clip: null                 // what was copied: [r0, c0, r1, c1]
    property bool finding: false
    property string chartSel: ""
    property var filterAt: null             // the filter list that's open: {c, x, y, values}
    property bool ruling: false             // the Highlight cells panel (conditional formatting)
    property string ruleKind: "gt"
    property string ruleStyle: "red"
    property var summing: null              // the Summarise panel: {block: [r0, c0, r1, c1], heads, rows, cols, values, fn}
    property bool checking: false           // the Choices panel (what may go in the cells: data validation)
    property string checkKind: "list"
    property string checkOp: "between"
    property var pickAt: null               // a cell's list of choices that's open: {r, c, x, y, items}
    property var noteHover: null            // a note shown while the pointer rests on its cell: {r, c, x, y, text, by}
    property var noteEdit: null             // a note being written: {r, c}
    property bool refusedNow: false         // what was just typed was turned away by the cell's choices
    property int naming: -1
    property var fz: Backend.frozen
    property int tick: 0                    // a change that cells drawn from Python can't see
    readonly property int railW: 236
    readonly property bool wide: width >= 1100
    onWideChanged: railOpen = wide                  // on a narrow window the list of sheets floats over the grid when it's asked for
    readonly property real gridX: railOpen && wide ? railW + 12 : 12
    readonly property int hdrW: 46
    readonly property int hdrH: 24
    readonly property var fmt: { tick; return Backend.current !== "" ? Backend.fmtAt(ar, ac) : ({}) }

    function say(t) { notice = t; hide.restart() }
    // what may go in cells: a list to pick from, or limits (Data › Choices for cells)
    function choices() { if (Backend.current === "") return; checking = !checking; if (!checking) return
        var x = Backend.checkAt(ar, ac)
        if (x.kind) { checkKind = x.kind; checkOp = x.op; chkItems.text = x.source || x.items; chkA.text = x.a; chkB.text = x.b; chkStop.on = x.stop }
        else { chkItems.text = ""; chkA.text = ""; chkB.text = ""; chkStop.on = true }
        if (checkKind === "list") chkItems.focusIn(); else chkA.focusIn() }
    function setCheck() {
        var why = Backend.setCheck(r0, c0, r1, c1, checkKind, chkItems.text, checkOp, chkA.text, chkB.text, chkStop.on)
        if (why) say(why); else { checking = false; tick++; say(checkKind === "list" ? "These cells offer a list to pick from." : "These cells now check what's typed in.") } }
    function clearChecks() { var n = Backend.clearChecks(r0, c0, r1, c1); checking = false; tick++; say(n ? "These cells take anything again." : "These cells had no choices.") }
    function openPick() {
        var items = Backend.choicesAt(ar, ac); if (!items.length) return
        var b = cellBox(ar, ac); if (!b) return
        var g = gridBox.mapToItem(win.contentItem, b.x + b.w, b.y + b.h)
        pickAt = { r: ar, c: ac, x: g.x, y: g.y + 2, items: items, w: Math.max(150, b.w) } }
    function pick(v) { var p = pickAt; pickAt = null; Backend.put(p.r, p.c, v); tick++; gridKeys.forceActiveFocus() }
    // notes on cells
    function noteCell() { if (Backend.current === "") return; noteHover = null; noteEdit = { r: ar, c: ac }; noteBox.many = Backend.noteAt(ar, ac).text || ""; noteBox.focusIn() }
    function saveNote() { var n = noteEdit; noteEdit = null; Backend.setNote(n.r, n.c, noteBox.many); tick++; gridKeys.forceActiveFocus() }
    function deleteNote() { Backend.setNote(ar, ac, ""); noteHover = null; tick++ }
    function highlightCells() { if (Backend.current === "") return; ruling = !ruling; if (ruling) ruleA.focusIn() }
    function addRule() {
        var why = Backend.addRule(r0, c0, r1, c1, ruleKind, ruleA.text, ruleB.text, parseInt(ruleN.text) || 10, ruleStyle)
        if (why) say(why); else { ruleA.text = ""; ruleB.text = ""; tick++ } }
    function summarise() { if (Backend.current === "") return; if (summing) { summing = null; return }
        var b = Backend.dataBlock(r0, c0, r1, c1), heads = Backend.headings(b[0], b[1], b[2], b[3])
        if (b[2] <= b[0] || heads.length < 2) { say("Select a table with names of its columns along the top, or a cell in it."); return }
        var numeric = heads.length - 1
        summing = { block: b, heads: heads, rows: heads[0].col, cols: -1, values: heads[numeric].col, fn: "sum" } }
    function makeSummary() { var m = summing, why = Backend.makePivot(m.block[0], m.block[1], m.block[2], m.block[3], m.rows, m.cols, m.values, m.fn)
        if (why) say(why); else { summing = null; ar = cr = ac = cc = 0; tick++ } }
    function refreshSummary() { var why = Backend.refreshPivot(); say(why || "The summary is up to date."); tick++ }
    function setSum(k, v) { var m = Object.assign({}, summing); m[k] = v; summing = m }
    function clearRules() { var n = Backend.clearRules(r0, c0, r1, c1); say(n ? n + (n === 1 ? " rule taken off." : " rules taken off.") : "No rules on these cells."); tick++ }
    function name(r, c) { return Backend.name(r, c) }
    function spanText() { return r0 === r1 && c0 === c1 ? name(ar, ac) : name(r0, c0) + ":" + name(r1, c1) }
    property int tabStart: -1               // Tab across a row, then Enter: back to the column it began in, one row down
    function select(r, c, extend) {
        r = Math.max(0, r); c = Math.max(0, Math.min(Backend.colCount - 1, c)); tabStart = -1
        if (editing) endEdit(true)
        if (!extend) { ar = r; ac = c }
        cr = r; cc = c
        Backend.growTo(r); Backend.growCols(c)
        show(cr, cc)
        if (!inBar) gridKeys.forceActiveFocus()
    }
    function show(r, c) {      // scroll the cell into view
        var fr = fz[0], fc = fz[1]
        if (r >= fr && c >= fc) main.positionViewAtCell(Qt.point(c - fc, r - fr), TableView.Contain)
        else if (r >= fr) main.positionViewAtRow(r - fr, TableView.Contain)
        else if (c >= fc) main.positionViewAtColumn(c - fc, TableView.Contain)
    }
    function paneOf(r, c) { return r < fz[0] ? (c < fz[1] ? cornerPane : topPane) : (c < fz[1] ? leftPane : main) }
    function cellBox(r, c) {   // where a cell is on screen, in the grid island's own coordinates, or null
        var v = paneOf(r, c), it = v.itemAtCell(Qt.point(c - v.colOff, r - v.rowOff))
        if (!it) return null
        var p = it.mapToItem(gridBox, 0, 0)
        return { x: p.x, y: p.y, w: it.width, h: it.height }
    }
    // typing into a cell
    property bool enterMode: false          // typing began with a key, as in Excel: the arrows finish the cell and move on
    property int ptR: -1                    // the cell the arrows point at while a formula is typed
    property int ptC: -1
    property int ptR2: -1
    property int ptC2: -1
    function startEdit(text, bar) {
        if (Backend.current === "") return
        show(ar, ac); inBar = !!bar; editing = true; enterMode = text !== undefined && !bar; ptR = -1
        var t = text === undefined ? Backend.raw(ar, ac) : text
        cellEdit.text = t; barEdit.text = t
        var ed = inBar ? barEdit : cellEdit
        ed.forceActiveFocus(); ed.cursorPosition = t.length          // at once: the next keys typed must land in it
        var b = cellBox(ar, ac); if (b) { cellEdit.x = b.x; cellEdit.y = b.y; cellEdit.cellW = b.w; cellEdit.height = b.h }
        else Qt.callLater(function () { var b2 = win.cellBox(win.ar, win.ac); if (b2) { cellEdit.x = b2.x; cellEdit.y = b2.y; cellEdit.cellW = b2.w; cellEdit.height = b2.h } })
    }
    function endEdit(keep, dr, dc) {
        if (!editing) return
        var t = inBar ? barEdit.text : cellEdit.text
        editing = false; inBar = false; suggest = []; ptR = -1
        refusedNow = false
        if (keep) Backend.put(ar, ac, t)
        if (refusedNow) { refusedNow = false; startEdit(t); return }        // turned away: back to typing in the cell
        if (dr || dc) { var r = stepRow(ar, dr || 0), c = ac + (dc || 0); ar = cr = Math.max(0, r); ac = cc = Math.max(0, c); show(ar, ac) }
        barEdit.text = Backend.raw(ar, ac)
        tick++; gridKeys.forceActiveFocus()
    }
    // function names as a formula is typed: the list under the formula island
    property var suggest: []
    function hint(t) {
        var m = /([A-Za-z][A-Za-z0-9.]*)$/.exec(t)
        if (t.charAt(0) !== "=" || !m || m[1].length < 1) { suggest = []; return }
        var w = m[1].toUpperCase(), list = Backend.functionNames.filter(function (n) { return n.indexOf(w) === 0 }).slice(0, 8)
        suggest = list.length === 1 && list[0] === w ? [] : list
    }
    function takeSuggest(name) { var ed = inBar ? barEdit : cellEdit; ed.text = ed.text.replace(/([A-Za-z][A-Za-z0-9.]*)$/, name + "("); barEdit.text = cellEdit.text = ed.text; suggest = []; ed.cursorPosition = ed.text.length; ed.forceActiveFocus() }
    // pointing at cells while typing a formula puts their names in
    function pointing() { var t = inBar ? barEdit.text : cellEdit.text; return editing && t.charAt(0) === "=" && /[=(,+\-*\/^&<>:;]\s*$/.test(t) }
    property string pointBase: ""
    function pointAt(r, c, r2, c2) {
        var ref = r2 === undefined || (r === r2 && c === c2) ? name(r, c) : name(Math.min(r, r2), Math.min(c, c2)) + ":" + name(Math.max(r, r2), Math.max(c, c2))
        var t = pointBase + ref; cellEdit.text = t; barEdit.text = t
    }
    // the clipboard (through a hidden text box: QML has no clipboard of its own)
    function copyCells(cut) { var t = Backend.copy(r0, c0, r1, c1, !!cut); clipHelper.text = t; clipHelper.selectAll(); clipHelper.copy(); clip = [r0, c0, r1, c1] }
    function pasteCells() { clipHelper.text = ""; clipHelper.paste(); var got = Backend.paste(r0, c0, r1, c1, clipHelper.text)
        if (got.length === 4) { ar = got[0]; ac = got[1]; cr = got[2]; cc = got[3] } clip = null; tick++ }
    function fmtSel(key, value) { Backend.setFormat(r0, c0, r1, c1, key, value); tick++ }
    function toggle(key) { fmtSel(key, !fmt[key]) }
    function openPop(kind, from) { if (pop === kind) { pop = ""; return } popFrom = from; pop = kind }
    // the top bar's menus
    function openFile() { Picker.open("Open a spreadsheet", [["Spreadsheets", "*.xlsx *.ods *.xls *.csv *.hsheet"]], function (paths) { if (paths.length) Backend.open(paths[0]) }) }
    function exportPdf() { if (Backend.current === "") return; var p = Backend.export("pdf"); if (p) { exported = p; hide.restart() } }
    function insertRow() { Backend.insert("r", r0, r1 - r0 + 1); tick++ }
    function insertColumn() { Backend.insert("c", c0, c1 - c0 + 1); tick++ }
    function deleteRow() { Backend.remove("r", r0, r1 - r0 + 1); tick++ }
    function deleteColumn() { Backend.remove("c", c0, c1 - c0 + 1); tick++ }
    function insertChart() { if (Backend.current !== "") openPop("chart", chartBtn) }
    function apply(what) {
        var nums = { number: "#,##0.00", currency: "$#,##0.00", percent: "0%", date: "short-date" }
        if (nums[what]) fmtSel("num", nums[what])
        else if (what === "bold" || what === "italic" || what === "underline") toggle(what.charAt(0))
        else if (what === "clear") { Backend.clear(r0, c0, r1, c1, "formats"); tick++ }
        else if (what === "sortUp" || what === "sortDown") sortBy(what === "sortDown")
        else if (what === "freezeTop") Backend.freeze(1, 0)
        else if (what === "freezeLeft") Backend.freeze(0, 1)
        else if (what === "unfreeze") Backend.freeze(0, 0)
    }
    // the menus' Edit items: on the typing when there is some, else on the cells
    function typing() { var f = win.activeFocusItem; return f && f !== gridKeys && typeof f.selectAll === "function" && typeof f.paste === "function" ? f : null }
    function menuUndo() { var t = typing(); if (t) t.undo(); else { Backend.undo(); tick++ } }
    function menuRedo() { var t = typing(); if (t) t.redo(); else { Backend.redo(); tick++ } }
    function menuCut() { var t = typing(); if (t) t.cut(); else copyCells(true) }
    function menuCopy() { var t = typing(); if (t) t.copy(); else copyCells(false) }
    function menuPaste() { var t = typing(); if (t) t.paste(); else pasteCells() }
    function menuSelectAll() { var t = typing(); if (t) t.selectAll(); else { var b = Backend.dataBlock(ar, ac, ar, ac); if (b[0] === r0 && b[1] === c0 && b[2] === r1 && b[3] === c1) b = [0, 0, Backend.rowCount - 1, Backend.colCount - 1]; ar = b[0]; ac = b[1]; cr = b[2]; cc = b[3] } }
    function fillDown() { if (r1 > r0) { Backend.fill(r0, c0, r0, c1, r1, c1); tick++ } }
    function fillRight() { if (c1 > c0) { Backend.fill(r0, c0, r1, c0, r1, c1); tick++ } }
    function today() { Backend.put(ar, ac, Qt.formatDate(new Date(), "yyyy-MM-dd")); tick++ }
    function find() { if (Backend.current !== "") { finding = true; findBox.focusIn() } }
    function sortBy(desc) { var b = Backend.dataBlock(r0, c0, r1, c1); var header = b[0] === r0 && b[0] < b[2] && isNaN(parseFloat(Backend.raw(b[0], ac)))
        Backend.sort(b[0], b[1], b[2], b[3], ac, desc, header); tick++ }
    function filter() { Backend.setFilter(r0, c0, r1, c1); tick++ }

    Connections { target: Backend
        function onFailed(msg) { win.say(msg) }
        function onRefused(msg) { win.say(msg); if (msg.indexOf("Let in") !== 0) win.refusedNow = true }
        function onSheetsChanged() { win.tick++; if (!win.editing) barEdit.text = Backend.raw(win.ar, win.ac) }
        function onGridChanged() { win.fz = Backend.frozen; main.forceLayout(); topPane.forceLayout(); leftPane.forceLayout(); cornerPane.forceLayout()
            colHead.forceLayout(); colHeadF.forceLayout(); rowHead.forceLayout(); rowHeadF.forceLayout() } }
    onArChanged: if (!editing) barEdit.text = Backend.raw(ar, ac)
    onAcChanged: if (!editing) barEdit.text = Backend.raw(ar, ac)
    Timer { id: hide; interval: 7000; onTriggered: { win.notice = ""; win.exported = "" } }
    onClosing: { endEdit(true); Backend.save() }
    Component.onCompleted: gridKeys.forceActiveFocus()
    Shortcut { sequence: "Ctrl+F"; enabled: Backend.current !== ""; onActivated: win.find() }

    islands: [
        // ---- the formula island: where you are, and what's in it
        Island { id: barIsland; visible: Backend.current !== ""; x: Math.max(win.gridX, win.titleEnd + 10); y: 12; width: win.width - x - toolsIsland.width - 24
            Rectangle { width: 92; height: 30; radius: 10; color: Theme.t.accent; anchors.verticalCenter: parent.verticalCenter
                TextInput { id: nameBox; anchors { fill: parent; leftMargin: 8; rightMargin: 8 } verticalAlignment: TextInput.AlignVCenter; horizontalAlignment: TextInput.AlignHCenter
                    color: Theme.t.onAccent; font.family: Theme.t.fontMono; font.pixelSize: 12; font.weight: Font.DemiBold; selectByMouse: true; clip: true
                    text: activeFocus ? text : win.spanText()
                    onAccepted: { var s = Backend.spanOf(text); if (s.length === 4) { win.ar = s[0]; win.ac = s[1]; win.select(s[2], s[3], true) } gridKeys.forceActiveFocus() } } }
            Label { text: "ƒx"; font.italic: true; font.pixelSize: 14; secondary: true; leftPadding: 6; rightPadding: 2; anchors.verticalCenter: parent.verticalCenter }
            Rectangle { width: barIsland.width - 92 - 40 - 16 - (sumLine.visible ? sumLine.width + 4 : 0); height: 30; radius: 10; color: Theme.t.group; anchors.verticalCenter: parent.verticalCenter
                border.width: 1; border.color: barEdit.activeFocus ? Theme.t.accent : Theme.t.islandLine
                TextInput { id: barEdit; anchors { fill: parent; leftMargin: 10; rightMargin: 10 } verticalAlignment: TextInput.AlignVCenter; clip: true; color: Theme.t.text
                    font.family: text.charAt(0) === "=" ? Theme.t.fontMono : Theme.t.font; font.pixelSize: 13; selectByMouse: true; selectionColor: Theme.t.accent
                    onActiveFocusChanged: if (activeFocus && !win.editing) { win.inBar = true; win.editing = true; cellEdit.text = text }
                    onTextEdited: { cellEdit.text = text; win.hint(text); win.ptR = -1 }
                    Keys.onPressed: function (e) { win.editKeys(e, barEdit) }
                    Label { visible: !barEdit.text && !barEdit.activeFocus; anchors.verticalCenter: parent.verticalCenter; secondary: true; font.pixelSize: 12
                        text: "Type a value, or a formula like =SUM(B2:B9)" } } }
            // what the chosen cells add up to
            Label { id: sumLine; visible: text !== "" && !win.editing; anchors.verticalCenter: parent.verticalCenter; leftPadding: 8; rightPadding: 6; font.pixelSize: 12
                width: Math.min(implicitWidth, barIsland.width * 0.4); elide: Text.ElideRight; secondary: true
                text: (win.tick, Backend.current !== "" ? Backend.summary(win.r0, win.c0, win.r1, win.c1) : "") } },
        Island { id: toolsIsland; visible: Backend.current !== ""; anchors { right: parent.right; rightMargin: 12 } y: 12; z: 8
            Seg { icon: "undo"; tip: "Undo (Ctrl+Z)"; opacity: Backend.canUndo ? 1 : 0.4; onClicked: { Backend.undo(); win.tick++ } }
            Seg { icon: "redo"; tip: "Redo (Ctrl+Shift+Z)"; opacity: Backend.canRedo ? 1 : 0.4; onClicked: { Backend.redo(); win.tick++ } }
            Seg { icon: "search"; tip: "Find (Ctrl+F)"; on: win.finding; onClicked: win.finding ? (win.finding = false) : win.find() }
            Seg { icon: "sidebar"; tip: "Your sheets"; on: win.railOpen; onClicked: win.railOpen = !win.railOpen }
            ExportMenu { choices: [["xlsx", "Excel", "An .xlsx file: formulas, formats and charts included"], ["csv", "CSV", "The values of this sheet, for anything"],
                                   ["pdf", "PDF", "This sheet on pages, for printing or sending"]]
                onChosen: function (key) { win.endEdit(true); var p = Backend.export(key); if (p) { win.exported = p; hide.restart() } } } },
        // ---- the left: your sheets
        Rail { id: docRail; visible: win.railOpen || Backend.current === ""; x: 12; y: 64; width: win.railW - 12; maxHeight: win.height - 64 - 70
            DocList { newLabel: "New Sheet"; icon: "table"; empty: "Sheets you make appear here, along with Excel and CSV files in your Documents folder." } },
        // ---- formatting, under the grid
        Island { id: bar; visible: Backend.current !== ""; x: Math.max(tabsIsland.x + tabsIsland.width + 10, Math.min(win.width - width - 12, (win.width - width) / 2))
            anchors { bottom: parent.bottom; bottomMargin: 14 }
            readonly property bool roomy: win.width - win.gridX - tabsIsland.width >= 820
            Tool { icon: "bold"; tip: "Bold (Ctrl+B)"; on: !!win.fmt.b; onClicked: win.toggle("b") }
            Tool { icon: "italic"; tip: "Italic (Ctrl+I)"; on: !!win.fmt.i; onClicked: win.toggle("i") }
            Tool { visible: bar.roomy; icon: "underline"; tip: "Underline (Ctrl+U)"; on: !!win.fmt.u; onClicked: win.toggle("u") }
            Tool { visible: bar.roomy; icon: "strike"; tip: "Strike through"; on: !!win.fmt.s; onClicked: win.toggle("s") }
            Tool { id: inkBtn; tip: "Text colour"; onClicked: win.openPop("ink", inkBtn)
                Label { anchors.centerIn: parent; anchors.verticalCenterOffset: -2; text: "A"; font.pixelSize: 14; font.weight: Font.Bold }
                Rectangle { x: 8; y: 22; width: 14; height: 3; radius: 1.5; color: win.fmt.color || "#15181C" } }
            Tool { id: fillBtn; tip: "Fill"; onClicked: win.openPop("fill", fillBtn)
                Glyph { anchors.centerIn: parent; anchors.verticalCenterOffset: -2; name: "bucket"; size: 14; ink: Theme.t.icon }
                Rectangle { x: 8; y: 22; width: 14; height: 3; radius: 1.5; color: win.fmt.fill || "#FFE58F" } }
            Gap {}
            Tool { icon: "alignleft"; tip: "Left"; on: win.fmt.align === "left"; onClicked: win.fmtSel("align", win.fmt.align === "left" ? "" : "left") }
            Tool { icon: "aligncenter"; tip: "Centre"; on: win.fmt.align === "center"; onClicked: win.fmtSel("align", win.fmt.align === "center" ? "" : "center") }
            Tool { icon: "alignright"; tip: "Right"; on: win.fmt.align === "right"; onClicked: win.fmtSel("align", win.fmt.align === "right" ? "" : "right") }
            Tool { visible: bar.roomy; text: "↵"; tip: "Wrap the text"; on: !!win.fmt.wrap; onClicked: win.toggle("wrap") }
            Gap {}
            Pick { id: numBtn; span: 112; text: (Backend.formats.filter(function (f) { return f.code === (win.fmt.num || "General") })[0] || { name: "Custom" }).name; onClicked: win.openPop("num", numBtn) }
            Tool { text: ".0"; tip: "Fewer decimal places"; onClicked: win.fmtSel("places", -1) }
            Tool { text: ".00"; span: 36; tip: "More decimal places"; onClicked: win.fmtSel("places", 1) }
            Gap {}
            Tool { text: "Σ"; tip: "Add up (Alt+=)"; onClicked: { var at = Backend.autoSum(win.r0, win.c0, win.r1, win.c1); win.ar = win.cr = at[0]; win.ac = win.cc = at[1]; win.tick++ } }
            Tool { text: "A↓"; span: 36; tip: "Sort, smallest first (by this column)"; onClicked: win.sortBy(false) }
            Tool { visible: bar.roomy; text: "Z↓"; span: 36; tip: "Sort, largest first"; onClicked: win.sortBy(true) }
            Tool { icon: "filter"; tip: "Filter"; on: Backend.filterRange.length > 0; onClicked: win.filter() }
            Tool { tip: "Highlight cells by what's in them"; on: win.ruling; onClicked: win.highlightCells()
                Column { anchors.centerIn: parent; spacing: 2
                    Rectangle { width: 14; height: 3; radius: 1.5; color: "#E5484D" } Rectangle { width: 9; height: 3; radius: 1.5; color: "#F5B83D" } Rectangle { width: 12; height: 3; radius: 1.5; color: "#30A46C" } } }
            Tool { id: chartBtn; icon: "shapes"; tip: "Chart"; onClicked: win.openPop("chart", chartBtn) }
            Tool { id: freezeBtn; visible: bar.roomy; text: "❄"; tip: "Freeze rows and columns"; on: win.fz[0] > 0 || win.fz[1] > 0; onClicked: win.openPop("freeze", freezeBtn) }
            Item { width: 2; height: 1 } },
        // ---- the sheets in the file
        Island { id: tabsIsland; visible: Backend.current !== ""; x: win.gridX; anchors { bottom: parent.bottom; bottomMargin: 14 }
            Flickable { width: Math.min(tabs.width, Math.max(90, win.width * 0.25)); height: 30; contentWidth: tabs.width; clip: true; anchors.verticalCenter: parent.verticalCenter; flickableDirection: Flickable.HorizontalFlick
                Row { id: tabs; height: 30; spacing: 4
                    Repeater { model: Backend.sheetNames
                        Seg { required property string modelData; required property int index; text: modelData; on: Backend.sheetIndex === index; tip: "Click again to rename"
                            onClicked: { win.endEdit(true); win.chartSel = ""; if (on) { rename.text = modelData; win.naming = index } else { Backend.selectSheet(index); win.ar = win.cr = win.ac = win.cc = 0; win.tick++ } } } } } }
            Seg { visible: !Backend.oneSheetOnly; icon: "plus"; tip: "Add a sheet"; onClicked: { win.endEdit(true); Backend.addSheet(); win.tick++ } } },
        Island { id: sumIsland; visible: Backend.current !== "" && (win.notice !== "" || win.exported !== ""); anchors { right: parent.right; rightMargin: 12; bottom: parent.bottom; bottomMargin: 64 }
            Label { leftPadding: 10; rightPadding: 10; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter; width: Math.min(implicitWidth, 420); elide: Text.ElideMiddle
                color: win.notice ? Theme.t.danger : Theme.t.text
                text: win.notice || (win.exported ? "Exported to " + win.exported : "") }
            Seg { visible: win.exported !== ""; text: "Show in Files"; onClicked: Backend.reveal(win.exported) } },
        // ---- find
        Island { visible: win.finding && Backend.current !== ""; x: win.gridX + (win.width - win.gridX - width) / 2; y: 60; z: 7
            TextBox { id: findBox; width: 220; height: 30; placeholder: "Find"; anchors.verticalCenter: parent.verticalCenter
                onAccepted: { var h = Backend.find(text, win.ar, win.ac, false, false); if (h.length) win.select(h[0], h[1], false); else win.say("Not found") }
                Keys.onPressed: function (e) { if (e.key === Qt.Key_Escape) { win.finding = false; gridKeys.forceActiveFocus(); e.accepted = true } } }
            Label { anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 11; secondary: true; width: 70; horizontalAlignment: Text.AlignHCenter
                text: findBox.text ? (win.tick, Backend.countFound(findBox.text, false)) + " found" : "" }
            Seg { icon: "up"; onClicked: { var h = Backend.find(findBox.text, win.ar, win.ac, true, false); if (h.length) win.select(h[0], h[1], false) } }
            Seg { icon: "down"; onClicked: findBox.accepted() }
            TextBox { id: replaceBox; width: 160; height: 30; placeholder: "Replace with"; anchors.verticalCenter: parent.verticalCenter }
            Seg { text: "Replace All"; onClicked: { var n = Backend.replaceAll(findBox.text, replaceBox.text, false); win.say(n + " replaced"); win.tick++ } }
            Seg { icon: "x"; onClicked: { win.finding = false; gridKeys.forceActiveFocus() } } },
        // ---- Summarise: a pivot table of the selected table, on a new sheet
        Rectangle { id: sumPanel; visible: win.summing !== null && Backend.current !== ""; z: 18; width: 500; height: sumCol.height + 28; radius: 18
            anchors { right: parent.right; rightMargin: 12; bottom: bar.top; bottomMargin: 10 }
            color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
            MouseArea { anchors.fill: parent }
            Column { id: sumCol; x: 14; y: 14; width: parent.width - 28; spacing: 10
                Item { width: parent.width; height: 24
                    Label { anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 15; font.weight: Font.DemiBold
                        text: "Pivot table  ·  " + (win.summing ? win.name(win.summing.block[0], win.summing.block[1]) + ":" + win.name(win.summing.block[2], win.summing.block[3]) : "") }
                    Seg { anchors { right: parent.right; verticalCenter: parent.verticalCenter } icon: "x"; tip: "Close"; onClicked: win.summing = null } }
                Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11
                    text: "A new sheet with a row for each name in one column (and a column for each name in another, if you like), adding up a third. Its numbers follow the table; new names come in with Refresh." }
                Repeater { model: [["rows", "A row for each"], ["cols", "A column for each"], ["values", "Adding up"]]
                    Row { id: sumRow; required property var modelData; spacing: 6; width: sumCol.width
                        Label { text: modelData[1]; width: 122; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12 }
                        Flow { width: parent.width - 128; spacing: 4
                            Seg { visible: modelData[0] === "cols"; text: "Nothing"; on: !!win.summing && win.summing.cols < 0; onClicked: win.setSum("cols", -1) }
                            Repeater { model: win.summing ? win.summing.heads : []
                                Seg { required property var modelData; property string k: sumRow.modelData[0]
                                    text: modelData.name; on: !!win.summing && win.summing[k] === modelData.col; onClicked: win.setSum(k, modelData.col) } } } } }
                Row { spacing: 6
                    Label { text: "How"; width: 122; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12 }
                    Repeater { model: [["sum", "Sum"], ["count", "Count"], ["average", "Average"], ["min", "Smallest"], ["max", "Largest"]]
                        Seg { required property var modelData; text: modelData[1]; on: !!win.summing && win.summing.fn === modelData[0]; onClicked: win.setSum("fn", modelData[0]) } } }
                Btn { primary: true; text: "Make the Pivot Table"; onClicked: win.makeSummary() } } },
        Island { visible: Backend.current !== "" && Backend.isPivot; x: win.gridX; anchors { bottom: parent.bottom; bottomMargin: 64 } z: 6
            Label { leftPadding: 10; rightPadding: 4; font.pixelSize: 12; secondary: true; anchors.verticalCenter: parent.verticalCenter; text: "A pivot table: its numbers follow the table it sums up" }
            Seg { text: "Refresh"; tip: "Bring in names added to the table since"; onClicked: win.refreshSummary() } },
        // ---- Choices: what may go in the selected cells (Excel's data validation)
        Rectangle { id: checkPanel; visible: win.checking && Backend.current !== ""; z: 18; width: 470; height: chkCol.height + 28; radius: 18
            anchors { right: parent.right; rightMargin: 12; bottom: bar.top; bottomMargin: 10 }
            color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
            MouseArea { anchors.fill: parent }
            Column { id: chkCol; x: 14; y: 14; width: parent.width - 28; spacing: 10
                Item { width: parent.width; height: 24
                    Label { anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 15; font.weight: Font.DemiBold
                        text: "Choices  ·  " + win.name(win.r0, win.c0) + (win.r1 !== win.r0 || win.c1 !== win.c0 ? ":" + win.name(win.r1, win.c1) : "") }
                    Seg { anchors { right: parent.right; verticalCenter: parent.verticalCenter } icon: "x"; tip: "Close"; onClicked: win.checking = false } }
                Flow { width: parent.width; spacing: 4
                    Repeater { model: [["list", "A list to pick from"], ["whole", "Whole numbers"], ["decimal", "Numbers"], ["date", "Dates"], ["length", "Length of text"]]
                        Seg { required property var modelData; text: modelData[1]; on: win.checkKind === modelData[0]
                            onClicked: { win.checkKind = modelData[0]; if (modelData[0] === "list") chkItems.focusIn(); else chkA.focusIn() } } } }
                TextBox { id: chkItems; visible: win.checkKind === "list"; width: parent.width; height: 32; placeholder: "Yes, No, Maybe  —  or the cells that hold them, such as E1:E5"
                    onAccepted: win.setCheck() }
                Flow { visible: win.checkKind !== "list"; width: parent.width; spacing: 4
                    Repeater { model: [["between", "Between"], ["greaterThanOrEqual", "At least"], ["lessThanOrEqual", "At most"], ["equal", "Exactly"], ["notEqual", "Not"]]
                        Seg { required property var modelData; text: modelData[1]; on: win.checkOp === modelData[0]; onClicked: win.checkOp = modelData[0] } } }
                Row { visible: win.checkKind !== "list"; spacing: 8
                    TextBox { id: chkA; width: win.checkOp === "between" ? 150 : 220; height: 32; onAccepted: win.setCheck()
                        placeholder: win.checkKind === "date" ? "2026-01-01" : win.checkKind === "length" ? "Characters" : "A number" }
                    Label { visible: win.checkOp === "between"; text: "and"; anchors.verticalCenter: parent.verticalCenter }
                    TextBox { id: chkB; visible: win.checkOp === "between"; width: 150; height: 32; onAccepted: win.setCheck()
                        placeholder: win.checkKind === "date" ? "2026-12-31" : "A number" } }
                Row { spacing: 10; height: 30
                    Toggle { id: chkStop; on: true; anchors.verticalCenter: parent.verticalCenter }
                    Label { anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; width: chkCol.width - 60; wrapMode: Text.WordWrap
                        text: chkStop.on ? "Turn anything else away" : "Let anything in, with a warning" } }
                Row { spacing: 8
                    Btn { primary: true; text: "Set the Choices"; onClicked: win.setCheck() }
                    Btn { text: "Take Them Off"; onClicked: win.clearChecks() } }
                Label { visible: Backend.checks.length > 0; text: "ON THIS SHEET"; secondary: true; font.pixelSize: 10; font.weight: Font.DemiBold }
                Repeater { model: Backend.checks
                    Label { required property var modelData; width: chkCol.width; elide: Text.ElideRight; font.pixelSize: 12
                        text: modelData.where + "  ·  " + modelData.what } } } },
        // ---- Highlight cells: conditional formatting for the selection, and the sheet's rules
        Rectangle { id: rulesPanel; visible: win.ruling && Backend.current !== ""; z: 18; width: 470; height: Math.min(win.height - 160, rulesCol.height + 28); radius: 18
            anchors { right: parent.right; rightMargin: 12; bottom: bar.top; bottomMargin: 10 }
            color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
            MouseArea { anchors.fill: parent }
            Flickable { anchors { fill: parent; margins: 14 } contentHeight: rulesCol.height; clip: true; interactive: rulesCol.height > height
                Column { id: rulesCol; width: parent.width; spacing: 10
                    Item { width: parent.width; height: 24
                        Label { anchors.verticalCenter: parent.verticalCenter; text: "Highlight cells  ·  " + win.name(win.r0, win.c0) + (win.r1 !== win.r0 || win.c1 !== win.c0 ? ":" + win.name(win.r1, win.c1) : "")
                            font.pixelSize: 15; font.weight: Font.DemiBold }
                        Seg { anchors { right: parent.right; verticalCenter: parent.verticalCenter } icon: "x"; tip: "Close"; onClicked: win.ruling = false } }
                    Flow { width: parent.width; spacing: 4
                        Repeater { model: [["gt", "Greater than"], ["lt", "Less than"], ["between", "Between"], ["eq", "Equal to"], ["text", "Text that contains"], ["dup", "Duplicates"],
                                           ["top", "Top"], ["bottom", "Bottom"], ["above", "Above average"], ["below", "Below average"], ["blank", "Empty"], ["error", "Errors"],
                                           ["scale", "Colour scale"], ["bar", "Data bars"]]
                            Seg { required property var modelData; text: modelData[1]; on: win.ruleKind === modelData[0]
                                onClicked: { win.ruleKind = modelData[0]; if (modelData[0] === "scale") win.ruleStyle = "green"; else if (modelData[0] === "bar") win.ruleStyle = "blue"; else if (["green", "blue", "three"].indexOf(win.ruleStyle) >= 0 && modelData[0] !== "scale" && modelData[0] !== "bar") win.ruleStyle = "red"; ruleA.focusIn() } } } }
                    Row { spacing: 8; visible: ["gt", "lt", "between", "eq", "text", "top", "bottom"].indexOf(win.ruleKind) >= 0
                        TextBox { id: ruleA; visible: win.ruleKind !== "top" && win.ruleKind !== "bottom"; width: win.ruleKind === "between" ? 140 : 220; height: 32
                            placeholder: win.ruleKind === "text" ? "Words" : "A number, a date or words"; onAccepted: win.addRule() }
                        Label { visible: win.ruleKind === "between"; text: "and"; anchors.verticalCenter: parent.verticalCenter }
                        TextBox { id: ruleB; visible: win.ruleKind === "between"; width: 140; height: 32; onAccepted: win.addRule() }
                        TextBox { id: ruleN; visible: win.ruleKind === "top" || win.ruleKind === "bottom"; width: 70; height: 32; text: "10"; onAccepted: win.addRule() }
                        Label { visible: win.ruleKind === "top" || win.ruleKind === "bottom"; text: "values"; anchors.verticalCenter: parent.verticalCenter } }
                    Row { spacing: 6
                        Label { text: win.ruleKind === "scale" ? "Colours" : win.ruleKind === "bar" ? "Bar" : "Look"; width: 52; anchors.verticalCenter: parent.verticalCenter; secondary: true; font.pixelSize: 12 }
                        Repeater { model: win.ruleKind === "scale" ? [["green", "#F8696B", "#63BE7B", "Red to green"], ["three", "#F8696B", "#63BE7B", "Red, yellow, green"], ["blue", "#FFFFFF", "#5A8AC6", "White to blue"]]
                                        : win.ruleKind === "bar" ? [["blue", "#638EC6", "#638EC6", "Blue"], ["green", "#63C384", "#63C384", "Green"], ["red", "#FF555A", "#FF555A", "Red"], ["yellow", "#FFB628", "#FFB628", "Orange"]]
                                        : [["red", "#FFC7CE", "#9C0006", "Light red"], ["yellow", "#FFEB9C", "#9C5700", "Yellow"], ["green", "#C6EFCE", "#006100", "Green"], ["blue", "#DDEBF7", "#1F4E78", "Blue"],
                                           ["redtext", "#FFFFFF", "#C00000", "Red text"], ["bold", "#FFFFFF", "#15181C", "Bold"]]
                            Rectangle { required property var modelData; width: 46; height: 30; radius: 8; border.width: win.ruleStyle === modelData[0] ? 2 : 1
                                border.color: win.ruleStyle === modelData[0] ? Theme.t.accent : Theme.t.islandLine
                                gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: modelData[1] } GradientStop { position: 1; color: win.ruleKind === "scale" ? modelData[2] : modelData[1] } }
                                Label { anchors.centerIn: parent; visible: win.ruleKind !== "scale" && win.ruleKind !== "bar"; text: "12"; color: modelData[2]; font.pixelSize: 12; font.weight: modelData[0] === "bold" ? Font.Bold : Font.Normal }
                                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: win.ruleStyle = parent.modelData[0] } } } }
                    Row { spacing: 8
                        Btn { primary: true; text: "Add the Rule"; onClicked: win.addRule() }
                        Btn { text: "Clear These Cells' Rules"; onClicked: win.clearRules() } }
                    Rectangle { width: parent.width; height: 1; color: Theme.t.islandLine; visible: Backend.rules.length > 0 }
                    Label { visible: Backend.rules.length > 0; text: "ON THIS SHEET (the first that fits a cell colours it)"; secondary: true; font.pixelSize: 10; font.weight: Font.DemiBold }
                    Repeater { model: Backend.rules
                        Item { required property var modelData; required property int index; width: rulesCol.width; height: 34
                            Rectangle { width: 26; height: 20; radius: 5; anchors.verticalCenter: parent.verticalCenter; border.width: 1; border.color: Theme.t.islandLine
                                gradient: Gradient { orientation: Gradient.Horizontal
                                    GradientStop { position: 0; color: modelData.kind === "scale" ? modelData.low : modelData.fill || "#FFFFFF" }
                                    GradientStop { position: 1; color: modelData.kind === "scale" ? modelData.high : modelData.fill || "#FFFFFF" } }
                                Label { anchors.centerIn: parent; visible: !!modelData.color; text: "a"; color: modelData.color || "black"; font.pixelSize: 11 } }
                            Label { x: 36; width: parent.width - 36 - 104; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; text: modelData.what + "  ·  " + modelData.where; font.pixelSize: 12 }
                            Row { anchors { right: parent.right; verticalCenter: parent.verticalCenter } spacing: 0
                                Seg { icon: "up"; tip: "Earlier"; enabled: index > 0; opacity: enabled ? 1 : 0.35; onClicked: { Backend.moveRule(modelData.id, true); win.tick++ } }
                                Seg { icon: "down"; tip: "Later"; enabled: index < Backend.rules.length - 1; opacity: enabled ? 1 : 0.35; onClicked: { Backend.moveRule(modelData.id, false); win.tick++ } }
                                Seg { icon: "trash"; tip: "Take it off"; onClicked: { Backend.removeRule(modelData.id); win.tick++ } } } } } } } },
        // ---- the little menus over the formatting island
        Rectangle { id: popBox; visible: win.pop !== "" && win.popFrom !== null; z: 20; radius: 14; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
            readonly property point at: win.popFrom ? win.popFrom.mapToItem(parent, 0, 0) : Qt.point(0, 0)
            width: win.pop === "ink" || win.pop === "fill" ? 6 * 30 + 20 : 240
            height: popCol.height + 12; x: Math.max(8, Math.min(parent.width - width - 8, at.x)); y: at.y - height - 10
            MouseArea { anchors.fill: parent }
            Column { id: popCol; x: 6; y: 6; width: parent.width - 12; spacing: 1
                Repeater { model: win.pop === "num" ? Backend.formats.map(function (f) { return [f.code, f.name, f.example] })
                                : win.pop === "chart" ? [["column", "Columns", "side by side"], ["bar", "Bars", "across"], ["line", "Lines", "over time"], ["area", "Area", "filled lines"], ["pie", "Pie", "shares of a whole"]]
                                : win.pop === "freeze" ? [["1,0", "The top row", ""], ["0,1", "The first column", ""], ["sel", "Up to the selected cell", ""], ["0,0", "Nothing (unfreeze)", ""]]
                                : []
                    Pressable { required property var modelData; width: popCol.width; height: 32; radius: 9; color: hovered ? Theme.t.hover : "transparent"
                        onClicked: win.popPick(modelData[0])
                        Label { x: 10; anchors.verticalCenter: parent.verticalCenter; text: modelData[1]; font.pixelSize: 13 }
                        Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: modelData[2]; font.pixelSize: 11; secondary: true; font.family: win.pop === "num" ? Theme.t.fontMono : Theme.t.font } } }
                Grid { visible: win.pop === "ink" || win.pop === "fill"; columns: 6; spacing: 6; padding: 4
                    Repeater { model: win.pop === "ink" ? ["#15181C", "#4B5563", "#9AA0A6", "#D93A3F", "#E8590C", "#C46A00", "#2B8A3E", "#0A8071", "#1C7ED6", "#2361AE", "#563AD1", "none"]
                                                       : ["#FFF3BF", "#D3F9D8", "#D0EBFF", "#FFE3E3", "#F3D9FA", "#E9ECEF", "#FFD43B", "#69DB7C", "#74C0FC", "#FF8787", "#B197FC", "none"]
                        Rectangle { required property string modelData; width: 24; height: 24; radius: 12; color: modelData === "none" ? "transparent" : modelData; border.width: 1; border.color: Theme.t.islandLine
                            Label { visible: parent.modelData === "none"; anchors.centerIn: parent; text: "×"; font.pixelSize: 14 }
                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: { var w = win, k = w.pop === "ink" ? "color" : "fill"; w.fmtSel(k, parent.modelData === "none" ? "" : parent.modelData); w.pop = "" } } } } } } }
    ]
    function popPick(key) {
        var kind = pop
        if (kind === "num") fmtSel("num", key)
        else if (kind === "chart") { var b = cellBox(r1, c1) || { x: 100, y: 100 }; var id = Backend.addChart(key, r0, c0, r1, c1, sheetX(c1 + 1) + 20, sheetY(r0)); if (id) chartSel = id; else say("Choose the cells with the numbers first.") }
        else if (kind === "freeze") { if (key === "sel") Backend.freeze(ar, ac); else { var p = key.split(","); Backend.freeze(parseInt(p[0]), parseInt(p[1])) } }
        pop = ""
    }
    function fillDrag() {
        if (fillR >= 0) { Backend.fill(r0, c0, r1, c1, fillR, fillC)
            var rr = fillR, cc2 = fillC; ar = Math.min(r0, rr); ac = Math.min(c0, cc2); cr = Math.max(r1, rr); cc = Math.max(c1, cc2) }
        fillR = -1; fillC = -1; tick++
    }
    function fillToEnd() {          // double-click the handle: down as far as the column beside it goes
        var side = c0 > 0 ? c0 - 1 : c1 + 1, b = Backend.dataBlock(r0, side, r0, side)
        if (b[2] > r1) { Backend.fill(r0, c0, r1, c1, b[2], c1); cr = b[2]; tick++ }
    }
    function sheetX(c) { var x = 0; for (var k = 0; k < c; k++) x += Backend.colWidth(k); return x }
    function sheetY(r) { var y = 0; for (var k = 0; k < r; k++) y += Backend.rowHeight(k); return y }
    // keys while typing in a cell or the formula island
    function editKeys(e, ed) {
        if (suggest.length && (e.key === Qt.Key_Tab || (e.key === Qt.Key_Return && suggest.length === 1))) { takeSuggest(suggest[0]); e.accepted = true; return }
        var arrows = { [Qt.Key_Up]: [-1, 0], [Qt.Key_Down]: [1, 0], [Qt.Key_Left]: [0, -1], [Qt.Key_Right]: [0, 1] }, d = arrows[e.key]
        if (d && !(e.modifiers & Qt.ControlModifier) && (ptR >= 0 || (pointing() && (enterMode || inBar === false && ed.cursorPosition === ed.text.length && e.key !== Qt.Key_Left && e.key !== Qt.Key_Right)))) {
            // the arrows point at cells and put their names in the formula
            if (ptR < 0) { pointBase = ed.text; ptR = ptR2 = ar; ptC = ptC2 = ac }
            if (e.modifiers & Qt.ShiftModifier) { ptR2 = Math.max(0, ptR2 + d[0]); ptC2 = Math.max(0, ptC2 + d[1]) }
            else { ptR = ptR2 = Math.max(0, ptR + d[0]); ptC = ptC2 = Math.max(0, ptC + d[1]) }
            pointAt(ptR, ptC, ptR2, ptC2); show(ptR2, ptC2); e.accepted = true; return
        }
        if (d && enterMode && !(e.modifiers & Qt.ShiftModifier)) { endEdit(true, d[0], d[1]); e.accepted = true; return }
        if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { var back = tabStart >= 0 && !(e.modifiers & Qt.ShiftModifier) ? tabStart - ac : 0; tabStart = -1
            endEdit(true, (e.modifiers & Qt.ShiftModifier) ? -1 : 1, back); e.accepted = true }
        else if (e.key === Qt.Key_Tab) { if (tabStart < 0) tabStart = ac; endEdit(true, 0, 1); e.accepted = true }
        else if (e.key === Qt.Key_Backtab) { endEdit(true, 0, -1); e.accepted = true }
        else if (e.key === Qt.Key_Escape) { endEdit(false); e.accepted = true }
        else if ((e.key === Qt.Key_Up || e.key === Qt.Key_Down) && ed === cellEdit && !pointing()) { endEdit(true, e.key === Qt.Key_Up ? -1 : 1, 0); e.accepted = true }
    }
    component Tool: Pressable { id: t; property string icon: ""; property string text: ""; property bool on: false; property string tip: ""; property int span: 30
        width: span; height: 30; radius: 11; anchors.verticalCenter: parent ? parent.verticalCenter : undefined; color: on ? Theme.t.accent : (hovered ? Theme.t.hover : "transparent")
        Glyph { visible: t.icon !== ""; anchors.centerIn: parent; name: t.icon; size: 16; ink: t.on ? Theme.t.onAccent : Theme.t.icon }
        Label { visible: t.text !== ""; anchors.centerIn: parent; text: t.text; color: t.on ? Theme.t.onAccent : Theme.t.text; font.pixelSize: 13; font.weight: Font.DemiBold }
        Rectangle { visible: t.hovered && t.tip !== "" && win.pop === ""; z: 9; color: Theme.t.tooltip_bg; border.width: 1; border.color: Theme.t.menu_border; radius: 6; width: tt.width + 14; height: 24
            anchors { bottom: parent.top; bottomMargin: 10; horizontalCenter: parent.horizontalCenter }
            Label { id: tt; anchors.centerIn: parent; text: t.tip; font.pixelSize: 11 } } }
    component Pick: Pressable { id: pk; property string text: ""; property int span: 90
        width: span; height: 30; radius: 10; anchors.verticalCenter: parent ? parent.verticalCenter : undefined; color: hovered ? Theme.t.hover : Theme.t.group
        Label { x: 10; width: parent.width - 28; anchors.verticalCenter: parent.verticalCenter; text: pk.text; elide: Text.ElideRight; font.pixelSize: 12 }
        Glyph { anchors { right: parent.right; rightMargin: 7; verticalCenter: parent.verticalCenter } name: "down"; size: 11; ink: Theme.t.text_secondary } }
    component Gap: Item { width: 9; height: 30; anchors.verticalCenter: parent ? parent.verticalCenter : undefined; Rectangle { anchors.centerIn: parent; width: 1; height: 16; color: Theme.t.islandLine } }

    // ---------------------------------------------------------------- the start: a new sheet
    Column { visible: Backend.current === ""; anchors.verticalCenter: parent.verticalCenter; x: win.middleX(width, parent.y + y, height, docRail) - parent.x; spacing: 10
        Item { width: 264; height: 150; anchors.horizontalCenter: parent.horizontalCenter      // a corner of a sheet: one cell chosen, a small chart growing out of it
            Rectangle { anchors.fill: parent; radius: 12; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; clip: true
                Repeater { model: 5; Rectangle { required property int index; x: 0; y: 30 * index; width: 264; height: 1; color: Theme.t.islandLine } }
                Repeater { model: 5; Rectangle { required property int index; x: 44 + 55 * index; y: 0; width: 1; height: 150; color: Theme.t.islandLine } }
                Rectangle { width: 264; height: 30; color: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.14) } Rectangle { width: 44; height: 150; color: Qt.rgba(tintColor.r, tintColor.g, tintColor.b, 0.14) }
                Rectangle { x: 99; y: 90; width: 56; height: 31; color: "transparent"; border.width: 2; border.color: Theme.t.accent; Rectangle { x: 50; y: 25; width: 8; height: 8; radius: 2; color: Theme.t.accent } } }
            Row { x: 176; y: 62; spacing: 5; Repeater { model: [26, 44, 34, 62]; Rectangle { required property int modelData; width: 13; height: modelData; y: 76 - modelData; radius: 3; color: Theme.t.accent } } } }
        Label { text: "Start a sheet"; font.pixelSize: 17; font.weight: Font.DemiBold; anchors.horizontalCenter: parent.horizontalCenter }
        Btn { text: "New Sheet"; primary: true; anchors.horizontalCenter: parent.horizontalCenter; onClicked: Backend.create() } }

    // ---------------------------------------------------------------- the sheet
    Item { visible: Backend.current !== ""; x: win.gridX; y: 54; width: parent.width - x - 12; height: parent.height - y - 64
        ImportNote { id: note; x: 0; y: 0; width: parent.width; file: Backend.importedFile; dropped: Backend.importedDropped; onDismissed: Backend.dismissNote() }
        Rectangle { id: gridBox; y: note.visible ? note.height + 10 : 0; width: parent.width; height: parent.height - y; radius: 14; clip: true; color: "#FFFFFF"
            border.width: 1; border.color: Theme.t.dark ? "#000000" : "#CBD0D6"
            readonly property real fw: { win.tick; var w = 0; for (var k = 0; k < win.fz[1]; k++) w += Backend.colWidth(k); return w }
            readonly property real fh: { win.tick; var h = 0; for (var k = 0; k < win.fz[0]; k++) h += Backend.rowHeight(k); return h }
            // keys on the grid itself
            Item { id: gridKeys; anchors.fill: parent; focus: true
                Keys.onPressed: function (e) { win.gridKey(e) } }
            // the headers: letters across, numbers down, each a TableView kept in step with its pane
            Rectangle { width: parent.width; height: win.hdrH; color: "#F1F3F5" }
            Rectangle { width: win.hdrW; height: parent.height; color: "#F1F3F5" }
            HeadView { id: colHeadF; x: win.hdrW; width: gridBox.fw; height: win.hdrH; model: Backend.colHeadsFrozen; syncView: cornerPane; syncDirection: Qt.Horizontal; axis: "c" }
            HeadView { id: colHead; x: win.hdrW + gridBox.fw; width: parent.width - x; height: win.hdrH; model: Backend.colHeads; syncView: main; syncDirection: Qt.Horizontal; axis: "c" }
            HeadView { id: rowHeadF; y: win.hdrH; width: win.hdrW; height: gridBox.fh; model: Backend.rowHeadsFrozen; syncView: cornerPane; syncDirection: Qt.Vertical; axis: "r" }
            HeadView { id: rowHead; y: win.hdrH + gridBox.fh; width: win.hdrW; height: parent.height - y; model: Backend.rowHeads; syncView: main; syncDirection: Qt.Vertical; axis: "r" }
            Pane { id: cornerPane; x: win.hdrW; y: win.hdrH; width: gridBox.fw; height: gridBox.fh; model: Backend.cornerGrid; rowOff: 0; colOff: 0; interactive: false }
            Pane { id: topPane; x: win.hdrW + gridBox.fw; y: win.hdrH; width: parent.width - x; height: gridBox.fh; model: Backend.topGrid; rowOff: 0; colOff: win.fz[1]
                syncView: main; syncDirection: Qt.Horizontal; interactive: false }
            Pane { id: leftPane; x: win.hdrW; y: win.hdrH + gridBox.fh; width: gridBox.fw; height: parent.height - y; model: Backend.leftGrid; rowOff: win.fz[0]; colOff: 0
                syncView: main; syncDirection: Qt.Vertical; interactive: false }
            Pane { id: main; x: win.hdrW + gridBox.fw; y: win.hdrH + gridBox.fh; width: parent.width - x; height: parent.height - y; model: Backend.mainGrid; rowOff: win.fz[0]; colOff: win.fz[1]
                onBottomRowChanged: Backend.growTo(bottomRow + win.fz[0] + 40); onRightColumnChanged: Backend.growCols(rightColumn + win.fz[1] + 3) }
            // the charts float over all the cells and scroll with the main pane
            Item { x: win.hdrW; y: win.hdrH; width: parent.width - x; height: parent.height - y; clip: true; z: 5
                Repeater { model: Backend.charts
                    ChartView { required property var modelData; chart: modelData; x: modelData.x - main.contentX + main.originX; y: modelData.y - main.contentY + main.originY; width: modelData.w; height: modelData.h } } }
            // the lines where the panes meet
            Rectangle { visible: win.fz[1] > 0; x: win.hdrW + gridBox.fw - 1; y: 0; width: 2; height: parent.height; color: "#ADB5BD" }
            Rectangle { visible: win.fz[0] > 0; x: 0; y: win.hdrH + gridBox.fh - 1; width: parent.width; height: 2; color: "#ADB5BD" }
            Rectangle { x: 0; y: win.hdrH - 1; width: parent.width; height: 1; color: "#CED4DA" }
            Rectangle { x: win.hdrW - 1; y: 0; width: 1; height: parent.height; color: "#CED4DA" }
            Pressable { width: win.hdrW; height: win.hdrH; radius: 0; color: hovered ? "#E9ECEF" : "#F1F3F5"; onClicked: { win.ar = 0; win.ac = 0; win.cr = Backend.rowCount - 1; win.cc = Backend.colCount - 1 } }
            // typing in the cell
            TextInput { id: cellEdit; visible: win.editing && !win.inBar; z: 30; leftPadding: 5; rightPadding: 5; verticalAlignment: TextInput.AlignVCenter; clip: true
                property real cellW: 100; width: Math.max(cellW, Math.min(Math.max(cellW, gridBox.width - x - 8), contentWidth + 16))
                color: "#15181C"; font.family: text.charAt(0) === "=" ? Theme.t.fontMono : "Inter"; font.pixelSize: 13; selectByMouse: true; selectionColor: Theme.t.accent
                onTextEdited: { barEdit.text = text; win.hint(text); win.ptR = -1 }
                Keys.onPressed: function (e) { win.editKeys(e, cellEdit) }
                Rectangle { anchors.fill: parent; z: -1; color: "#FFFFFF"; border.width: 2; border.color: Theme.t.accent } }
            // functions to pick while typing a formula
            Rectangle { visible: win.editing && win.suggest.length > 0; z: 31; x: win.inBar ? barIsland.x - gridBox.mapToItem(win.contentItem, 0, 0).x + 140 : cellEdit.x; y: win.inBar ? 0 : cellEdit.y + cellEdit.height + 4
                width: 320; height: sugCol.height + 10; radius: 12; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                Column { id: sugCol; x: 5; y: 5; width: parent.width - 10
                    Repeater { model: win.suggest
                        Pressable { required property string modelData; required property int index; width: sugCol.width; height: 30; radius: 8; color: index === 0 || hovered ? Theme.t.hover : "transparent"
                            onClicked: win.takeSuggest(modelData)
                            Label { x: 8; anchors.verticalCenter: parent.verticalCenter; text: modelData; font.family: Theme.t.fontMono; font.pixelSize: 12; font.weight: Font.DemiBold; width: 100 }
                            Label { x: 110; width: parent.width - 116; anchors.verticalCenter: parent.verticalCenter; text: Backend.functionHelp(modelData); elide: Text.ElideRight; font.pixelSize: 11; secondary: true } } } } }
        }
    }

    // ---------------------------------------------------------------- a pane of cells
    component Pane: TableView {
        id: pane
        property int rowOff: 0
        property int colOff: 0
        clip: true; boundsBehavior: Flickable.StopAtBounds; reuseItems: true
        columnWidthProvider: function (c) { win.tick; return Backend.colWidth(c + pane.colOff) }
        rowHeightProvider: function (r) { win.tick; return Backend.rowHeight(r + pane.rowOff) }
        delegate: Cell {}
        // pressing and dragging chooses cells; double-click types; the right button gives the menu
        MouseArea { parent: pane.contentItem; anchors.fill: parent; z: 10; acceptedButtons: Qt.LeftButton | Qt.RightButton; preventStealing: true; hoverEnabled: true
            property bool dragging: false
            property bool filling: false
            function at(m) { var p = pane.cellAtPosition(Qt.point(m.x, m.y), true); return [p.y + pane.rowOff, p.x + pane.colOff] }
            function nearHandle(m) {        // the small square at the selection's bottom right corner
                if (win.editing) return false
                var it = pane.itemAtCell(Qt.point(win.c1 - pane.colOff, win.r1 - pane.rowOff))
                return !!it && Math.abs(m.x - (it.x + it.width)) <= 8 && Math.abs(m.y - (it.y + it.height)) <= 8
            }
            cursorShape: filling || containsMouse && hoverHandle ? Qt.CrossCursor : Qt.ArrowCursor
            property bool hoverHandle: false
            onDoubleClicked: function (m) {
                if (nearHandle(m)) { win.fillToEnd(); return }
                if (m.button === Qt.LeftButton && !win.editing) win.startEdit() }
            onPressed: function (m) {
                if (m.button === Qt.LeftButton && nearHandle(m)) { filling = true; return }
                var rc = at(m); if (rc[0] < pane.rowOff || rc[1] < pane.colOff) return
                var flt = Backend.filterRange, cellIt = pane.itemAtCell(Qt.point(rc[1] - pane.colOff, rc[0] - pane.rowOff))
                if (m.button === Qt.LeftButton && flt.length && rc[0] === flt[0] && rc[1] >= flt[1] && rc[1] <= flt[3] && cellIt && m.x >= cellIt.x + cellIt.width - 22) {
                    var g = mapToItem(win.contentItem, cellIt.x + cellIt.width, cellIt.y + cellIt.height)       // the filter's arrow
                    win.filterAt = { c: rc[1], x: g.x, y: g.y + 4, values: Backend.filterValues(rc[1]) }; return }
                if (m.button === Qt.LeftButton && rc[0] === win.ar && rc[1] === win.ac && !win.editing && cellIt && m.x >= cellIt.x + cellIt.width - 22 && cellIt.cell.pick) {
                    win.openPick(); return }      // the list's arrow
                win.noteHover = null
                if (m.button === Qt.RightButton) { if (rc[0] < win.r0 || rc[0] > win.r1 || rc[1] < win.c0 || rc[1] > win.c1) win.select(rc[0], rc[1], false)
                    var g = mapToItem(win.contentItem, m.x, m.y); win.menu = { x: g.x, y: g.y }; return }
                win.menu = null; win.pop = ""; win.chartSel = ""
                if (win.pointing()) { win.pointBase = (win.inBar ? barEdit : cellEdit).text; win.pointAt(rc[0], rc[1]); pointFrom = rc; dragging = true; return }
                pointFrom = null
                win.select(rc[0], rc[1], !!(m.modifiers & Qt.ShiftModifier)); dragging = true }
            property var pointFrom: null
            onExited: { noteWait.stop(); win.noteHover = null }
            Timer { id: noteWait; interval: 350; property var at: [0, 0]; property point pos
                onTriggered: { if (win.menu || win.editing || win.noteEdit) return
                    var n = Backend.noteAt(at[0], at[1]); win.noteHover = n.text ? { r: at[0], c: at[1], x: pos.x + 14, y: pos.y + 10, text: n.text, by: n.by } : null } }
            onPositionChanged: function (m) {
                if (!pressed) { hoverHandle = nearHandle(m); noteWait.at = at(m); noteWait.pos = mapToItem(win.contentItem, m.x, m.y)
                    if (win.noteHover && (win.noteHover.r !== noteWait.at[0] || win.noteHover.c !== noteWait.at[1])) win.noteHover = null
                    noteWait.restart(); return }
                if (filling) { var f = at(m)
                    if (f[0] > win.r1 || f[0] < win.r0) { win.fillR = f[0]; win.fillC = win.c1 } else { win.fillR = win.r1; win.fillC = f[1] }
                    return }
                if (!dragging) return; var rc = at(m)
                if (pointFrom) { win.pointAt(pointFrom[0], pointFrom[1], rc[0], rc[1]); return }
                if (rc[0] !== win.cr || rc[1] !== win.cc) { win.cr = rc[0]; win.cc = rc[1] } }
            onReleased: { dragging = false
                if (filling) { filling = false; win.fillDrag() }
                if (pointFrom) { pointFrom = null; (win.inBar ? barEdit : cellEdit).forceActiveFocus() } } }
    }
    component Cell: Rectangle {
        id: cellItem
        required property var cell
        required property int row
        required property int column
        readonly property int r: row + TableView.view.rowOff
        readonly property int c: column + TableView.view.colOff
        readonly property bool inSel: r >= win.r0 && r <= win.r1 && c >= win.c0 && c <= win.c1
        readonly property bool active: r === win.ar && c === win.ac
        readonly property var flt: Backend.filterRange
        implicitWidth: 100; implicitHeight: 26
        color: cell.fill ? cell.fill : "#FFFFFF"
        Rectangle { anchors.fill: parent; visible: cellItem.inSel && !cellItem.active; color: Qt.alpha(Theme.t.accent, 0.13) }
        Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: "#E3E6EA" }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: "#E3E6EA" }
        Rectangle { visible: cellItem.cell.bar !== undefined; x: 2; y: 3; height: parent.height - 7; radius: 2; width: Math.max(0, (parent.width - 5) * (cellItem.cell.bar || 0))   // a data bar
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0; color: Qt.alpha(cellItem.cell.barColor || "#638EC6", 0.85) } GradientStop { position: 1; color: Qt.alpha(cellItem.cell.barColor || "#638EC6", 0.25) } } }
        Text { anchors { fill: parent; leftMargin: 5; rightMargin: cellItem.flt.length && cellItem.r === cellItem.flt[0] && cellItem.c >= cellItem.flt[1] && cellItem.c <= cellItem.flt[3] ? 22 : 5 }
            text: cellItem.cell.t; textFormat: Text.PlainText; verticalAlignment: cellItem.cell.wrap ? Text.AlignTop : Text.AlignVCenter; topPadding: cellItem.cell.wrap ? 4 : 0
            horizontalAlignment: cellItem.cell.align === "right" ? Text.AlignRight : cellItem.cell.align === "center" ? Text.AlignHCenter : Text.AlignLeft
            wrapMode: cellItem.cell.wrap ? Text.Wrap : Text.NoWrap; elide: cellItem.cell.wrap || !cellItem.cell.n ? Text.ElideNone : Text.ElideNone; clip: !!cellItem.cell.n || !!cellItem.cell.wrap
            color: cellItem.cell.color ? cellItem.cell.color : cellItem.cell.e ? "#C92A2A" : "#15181C"
            font.family: cellItem.cell.font || "Inter"; font.pixelSize: cellItem.cell.size ? Math.round(cellItem.cell.size * 4 / 3) : 13
            font.bold: !!cellItem.cell.b; font.italic: !!cellItem.cell.i; font.underline: !!cellItem.cell.u; font.strikeout: !!cellItem.cell.s }
        // the selection's outline, drawn by the cells on its edges
        Rectangle { visible: cellItem.inSel && cellItem.r === win.r0; width: parent.width; height: 2; color: Theme.t.accent; z: 3 }
        Rectangle { visible: cellItem.inSel && cellItem.r === win.r1; anchors.bottom: parent.bottom; width: parent.width; height: 2; color: Theme.t.accent; z: 3 }
        Rectangle { visible: cellItem.inSel && cellItem.c === win.c0; width: 2; height: parent.height; color: Theme.t.accent; z: 3 }
        Rectangle { visible: cellItem.inSel && cellItem.c === win.c1; anchors.right: parent.right; width: 2; height: parent.height; color: Theme.t.accent; z: 3 }
        // a reference in the formula being typed
        Item { readonly property var f: win.refs.length ? win.refAt(cellItem.r, cellItem.c) : null; visible: f !== null; anchors.fill: parent; z: 4
            Rectangle { anchors.fill: parent; color: parent.f ? Qt.alpha(parent.f.colour, 0.08) : "transparent" }
            Rectangle { visible: !!parent.f && cellItem.r === parent.f.r0; width: parent.width; height: 2; color: parent.f ? parent.f.colour : "transparent" }
            Rectangle { visible: !!parent.f && cellItem.r === parent.f.r1; anchors.bottom: parent.bottom; width: parent.width; height: 2; color: parent.f ? parent.f.colour : "transparent" }
            Rectangle { visible: !!parent.f && cellItem.c === parent.f.c0; width: 2; height: parent.height; color: parent.f ? parent.f.colour : "transparent" }
            Rectangle { visible: !!parent.f && cellItem.c === parent.f.c1; anchors.right: parent.right; width: 2; height: parent.height; color: parent.f ? parent.f.colour : "transparent" } }
        // what was copied: a dashed outline
        Rectangle { readonly property var k: win.clip; visible: !!k && cellItem.r >= k[0] && cellItem.r <= k[2] && cellItem.c >= k[1] && cellItem.c <= k[3]
            anchors.fill: parent; color: "transparent"; border.width: 0; z: 2
            Rectangle { visible: parent.k && cellItem.r === parent.k[0]; width: parent.width; height: 1; color: Theme.t.accent; opacity: 0.8 }
            Rectangle { visible: parent.k && cellItem.r === parent.k[2]; anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.t.accent; opacity: 0.8 } }
        // where a fill drag will reach
        Item { readonly property int fr0: Math.min(win.r0, win.fillR); readonly property int fr1: Math.max(win.r1, win.fillR)
            readonly property int fc0: Math.min(win.c0, win.fillC); readonly property int fc1: Math.max(win.c1, win.fillC)
            visible: win.fillR >= 0 && cellItem.r >= fr0 && cellItem.r <= fr1 && cellItem.c >= fc0 && cellItem.c <= fc1; anchors.fill: parent; z: 3
            Rectangle { visible: cellItem.r === parent.fr0; width: parent.width; height: 1; color: "#868E96" }
            Rectangle { visible: cellItem.r === parent.fr1; anchors.bottom: parent.bottom; width: parent.width; height: 1; color: "#868E96" }
            Rectangle { visible: cellItem.c === parent.fc0; width: 1; height: parent.height; color: "#868E96" }
            Rectangle { visible: cellItem.c === parent.fc1; anchors.right: parent.right; width: 1; height: parent.height; color: "#868E96" } }
        // the fill handle, at the selection's bottom right
        Rectangle { visible: cellItem.r === win.r1 && cellItem.c === win.c1 && !win.editing; z: 12; width: 9; height: 9; radius: 2; color: Theme.t.accent; border.width: 1; border.color: "#FFFFFF"
            x: parent.width - 5; y: parent.height - 5 }
        // a note: a small red corner
        Canvas { visible: !!cellItem.cell.note; z: 11; width: 7; height: 7; anchors { right: parent.right; top: parent.top }
            onPaint: { var c = getContext("2d"); c.reset(); c.fillStyle = "#E03131"; c.beginPath(); c.moveTo(0, 0); c.lineTo(7, 0); c.lineTo(7, 7); c.closePath(); c.fill() } }
        // a list to pick from: its arrow, on the cell that's chosen
        Rectangle { visible: !!cellItem.cell.pick && cellItem.active && !win.editing; z: 13
            anchors { right: parent.right; rightMargin: 2; verticalCenter: parent.verticalCenter } width: 18; height: Math.min(20, parent.height - 4); radius: 5
            color: "#E9ECEF"; border.width: 1; border.color: "#CED4DA"
            Glyph { anchors.centerIn: parent; name: "down"; size: 10; ink: "#495057" } }
        // a filter's arrow on the filter's first row
        Rectangle { visible: cellItem.flt.length > 0 && cellItem.r === cellItem.flt[0] && cellItem.c >= cellItem.flt[1] && cellItem.c <= cellItem.flt[3]; z: 13
            readonly property bool used: Backend.filterCols.indexOf(cellItem.c) >= 0       // some of this column's values are hidden
            anchors { right: parent.right; rightMargin: 3; verticalCenter: parent.verticalCenter } width: 18; height: 18; radius: 5
            color: used ? Theme.t.accent : "#E9ECEF"; border.width: 1; border.color: used ? Theme.t.accent : "#CED4DA"
            Glyph { anchors.centerIn: parent; name: parent.used ? "filter" : "down"; size: parent.used ? 11 : 10; ink: parent.used ? Theme.t.onAccent : "#495057" } }
    }
    component HeadView: TableView {
        id: hv
        property string axis: "c"
        interactive: false; clip: true; reuseItems: true
        delegate: Rectangle {
            required property string display
            required property int at
            readonly property bool lit: hv.axis === "c" ? (at >= win.c0 && at <= win.c1) : (at >= win.r0 && at <= win.r1)
            implicitWidth: hv.axis === "c" ? 100 : win.hdrW; implicitHeight: win.hdrH
            color: lit ? Qt.alpha(Theme.t.accent, 0.22) : "#F1F3F5"
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: "#DEE2E6" }
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: "#DEE2E6" }
            Text { anchors.centerIn: parent; text: display; font.family: "Inter"; font.pixelSize: 11; font.weight: parent.lit ? Font.DemiBold : Font.Normal; color: parent.lit ? "#15181C" : "#6C757D" }
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton
                onPressed: function (m) { win.endEdit(true)
                    if (hv.axis === "c") { if (!(m.modifiers & Qt.ShiftModifier)) { win.ar = 0; win.ac = at } win.cr = Backend.rowCount - 1; win.cc = at; if (!(m.modifiers & Qt.ShiftModifier)) win.ar = 0 }
                    else { if (!(m.modifiers & Qt.ShiftModifier)) { win.ar = at; win.ac = 0 } win.cr = at; win.cc = Backend.colCount - 1 }
                    gridKeys.forceActiveFocus()
                    if (m.button === Qt.RightButton) { var g = mapToItem(win.contentItem, m.x, m.y); win.menu = { x: g.x, y: g.y, head: hv.axis } } } }
            // drag the edge to resize; double-click it to fit
            MouseArea { visible: hv.axis === "c"; anchors { right: parent.right; top: parent.top; bottom: parent.bottom } width: 7; cursorShape: Qt.SplitHCursor; preventStealing: true
                property real fromX: 0; property real w0: 0
                onPressed: function (m) { fromX = mapToItem(win.contentItem, m.x, 0).x; w0 = Backend.colWidth(at) }
                onPositionChanged: function (m) { Backend.setColWidth(at, w0 + mapToItem(win.contentItem, m.x, 0).x - fromX); win.tick++ }
                onDoubleClicked: { Backend.fitColumn(at); win.tick++ } }
            MouseArea { visible: hv.axis === "r"; anchors { left: parent.left; right: parent.right; bottom: parent.bottom } height: 6; cursorShape: Qt.SplitVCursor; preventStealing: true
                property real fromY: 0; property real h0: 0
                onPressed: function (m) { fromY = mapToItem(win.contentItem, 0, m.y).y; h0 = Backend.rowHeight(at) }
                onPositionChanged: function (m) { Backend.setRowHeight(at, h0 + mapToItem(win.contentItem, 0, m.y).y - fromY); win.tick++ } }
        }
    }
    // ---------------------------------------------------------------- a chart over the cells
    component ChartView: Rectangle {
        id: cv
        property var chart: ({})
        readonly property var cd: { win.tick; return Backend.chartData(chart.id || "") }
        readonly property bool chosen: win.chartSel === chart.id
        radius: 10; color: "#FFFFFF"; border.width: chosen ? 2 : 1; border.color: chosen ? Theme.t.accent : "#CED4DA"
        Text { x: 12; y: 8; width: parent.width - 24; text: cv.cd.title || ""; font.family: "Inter"; font.pixelSize: 14; font.weight: Font.DemiBold; color: "#15181C"; elide: Text.ElideRight; horizontalAlignment: Text.AlignHCenter }
        Canvas { id: plot; anchors { fill: parent; topMargin: cv.cd.title ? 32 : 12; bottomMargin: cv.cd.legend && (cv.cd.series || []).length > 0 ? 34 : 10; leftMargin: 10; rightMargin: 12 }
            property var d: cv.cd
            onDChanged: requestPaint(); onWidthChanged: requestPaint(); onHeightChanged: requestPaint()
            onPaint: win.drawChart(getContext("2d"), width, height, d) }
        Row { visible: !!cv.cd.legend; anchors { bottom: parent.bottom; bottomMargin: 10; horizontalCenter: parent.horizontalCenter } spacing: 12
            Repeater { model: cv.cd.kind === "pie" ? (cv.cd.labels || []).slice(0, 8) : (cv.cd.series || [])
                Row { required property var modelData; required property int index; spacing: 5
                    Rectangle { width: 10; height: 10; radius: 3; anchors.verticalCenter: parent.verticalCenter; color: cv.cd.kind === "pie" ? win.palette[index % win.palette.length] : modelData.colour }
                    Text { text: cv.cd.kind === "pie" ? modelData : modelData.name; font.family: "Inter"; font.pixelSize: 11; color: "#495057" } } } }
        MouseArea { anchors.fill: parent; cursorShape: cv.chosen ? Qt.SizeAllCursor : Qt.PointingHandCursor; preventStealing: true
            property point from; property point at0
            onPressed: function (m) { win.chartSel = cv.chart.id; from = mapToItem(win.contentItem, m.x, m.y); at0 = Qt.point(cv.chart.x, cv.chart.y); gridKeys.forceActiveFocus() }
            onPositionChanged: function (m) { var p = mapToItem(win.contentItem, m.x, m.y); Backend.setChart(cv.chart.id, "x", at0.x + p.x - from.x); Backend.setChart(cv.chart.id, "y", at0.y + p.y - from.y) } }
        Rectangle { visible: cv.chosen; anchors { right: parent.right; bottom: parent.bottom; margins: -5 } width: 12; height: 12; radius: 3; color: Theme.t.accent
            MouseArea { anchors.fill: parent; anchors.margins: -4; cursorShape: Qt.SizeFDiagCursor; preventStealing: true
                property point from; property size s0
                onPressed: function (m) { from = mapToItem(win.contentItem, m.x, m.y); s0 = Qt.size(cv.chart.w, cv.chart.h) }
                onPositionChanged: function (m) { var p = mapToItem(win.contentItem, m.x, m.y); Backend.setChart(cv.chart.id, "w", s0.width + p.x - from.x); Backend.setChart(cv.chart.id, "h", s0.height + p.y - from.y) } } }
        // its own island, above it, when it's chosen
        Rectangle { visible: cv.chosen; width: chRow.width + 12; height: 38; radius: 14; z: 3
            x: Math.max(4 - cv.x, Math.min(cv.parent.width - cv.x - width - 4, (cv.width - width) / 2)); y: cv.y > 52 ? -height - 8 : cv.height + 8
            color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
            Row { id: chRow; x: 6; anchors.verticalCenter: parent.verticalCenter; spacing: 3
                Repeater { model: [["column", "Columns"], ["bar", "Bars"], ["line", "Lines"], ["area", "Area"], ["pie", "Pie"]]
                    Seg { required property var modelData; text: modelData[1]; on: cv.chart.kind === modelData[0]; onClicked: Backend.setChart(cv.chart.id, "kind", modelData[0]) } }
                Rectangle { width: 150; height: 28; radius: 9; color: Theme.t.group; anchors.verticalCenter: parent.verticalCenter
                    TextInput { anchors { fill: parent; leftMargin: 8; rightMargin: 8 } verticalAlignment: TextInput.AlignVCenter; clip: true; color: Theme.t.text; font.pixelSize: 12; text: cv.chart.title || ""
                        onEditingFinished: Backend.setChart(cv.chart.id, "title", text)
                        Label { visible: !parent.text; anchors.verticalCenter: parent.verticalCenter; secondary: true; font.pixelSize: 12; text: "Title" } } }
                Seg { text: "Legend"; on: !!cv.chart.legend; onClicked: Backend.setChart(cv.chart.id, "legend", !cv.chart.legend) }
                Seg { text: cv.chart.range; tip: "Its cells: choose others, then click"; onClicked: Backend.setChart(cv.chart.id, "range", win.spanText()) }
                Seg { icon: "trash"; tip: "Delete the chart"; onClicked: { var id = cv.chart.id; win.chartSel = ""; Backend.removeChart(id) } } } }
    }
    readonly property var palette: ["#4C6EF5", "#F59F00", "#12B886", "#E64980", "#7950F2", "#15AABF", "#FA5252", "#82C91E"]
    function drawChart(g, w, h, d) {
        g.reset()
        if (!d || !d.series || !d.series.length) return
        g.font = "11px Inter"
        var labels = d.labels || [], n = labels.length, series = d.series
        if (d.kind === "pie") {
            var vals = series[0].values.map(function (v) { return Math.max(0, v) }), total = vals.reduce(function (a, b) { return a + b }, 0)
            if (total <= 0) return
            var cx = w / 2, cy = h / 2, rad = Math.max(10, Math.min(w, h) / 2 - 6), a0 = -Math.PI / 2
            for (var k = 0; k < vals.length; k++) {
                var a1 = a0 + vals[k] / total * Math.PI * 2
                g.beginPath(); g.moveTo(cx, cy); g.arc(cx, cy, rad, a0, a1); g.closePath(); g.fillStyle = palette[k % palette.length]; g.fill()
                g.strokeStyle = "#FFFFFF"; g.lineWidth = 1.5; g.stroke()
                var mid = (a0 + a1) / 2, share = Math.round(vals[k] / total * 100)
                if (share >= 6) { g.fillStyle = "#FFFFFF"; g.textAlign = "center"; g.fillText(share + "%", cx + Math.cos(mid) * rad * 0.62, cy + Math.sin(mid) * rad * 0.62 + 4) }
                a0 = a1
            }
            return
        }
        var lo = Math.min(0, d.low), hi = Math.max(0, d.high); if (hi === lo) hi = lo + 1
        var step = niceStep((hi - lo) / 5); hi = Math.ceil(hi / step) * step; lo = Math.floor(lo / step) * step
        var across = d.kind === "bar", left = across ? 70 : 46, bottom = 22, pw = w - left - 6, ph = h - bottom - 6
        g.strokeStyle = "#E9ECEF"; g.lineWidth = 1; g.fillStyle = "#868E96"; g.textAlign = across ? "center" : "right"
        for (var v = lo; v <= hi + step / 2; v += step) {      // the scale and its lines
            if (across) { var gx = left + (v - lo) / (hi - lo) * pw; g.beginPath(); g.moveTo(gx, 6); g.lineTo(gx, 6 + ph); g.stroke(); g.fillText(fmtNum(v), gx, h - 6) }
            else { var gy = 6 + ph - (v - lo) / (hi - lo) * ph; g.beginPath(); g.moveTo(left, gy); g.lineTo(left + pw, gy); g.stroke(); g.fillText(fmtNum(v), left - 6, gy + 4) }
        }
        var slot = (across ? ph : pw) / Math.max(1, n)
        g.textAlign = across ? "right" : "center"; g.fillStyle = "#495057"
        for (var i = 0; i < n; i++) {
            var lab = String(labels[i]); if (lab.length > 12) lab = lab.slice(0, 11) + "…"
            if (across) g.fillText(lab, left - 6, 6 + slot * (i + 0.5) + 4)
            else if (n <= 24 || i % Math.ceil(n / 24) === 0) g.fillText(lab, left + slot * (i + 0.5), h - 6)
        }
        var zero = across ? left + (0 - lo) / (hi - lo) * pw : 6 + ph - (0 - lo) / (hi - lo) * ph
        for (var s = 0; s < series.length; s++) {
            var col = series[s].colour, vs = series[s].values
            if (d.kind === "column" || d.kind === "bar") {
                var bw = slot * 0.78 / series.length
                g.fillStyle = col
                for (var j = 0; j < vs.length; j++) {
                    var pos = slot * j + slot * 0.11 + bw * s, len = (vs[j] - 0) / (hi - lo) * (across ? pw : ph)
                    if (across) g.fillRect(Math.min(zero, zero + len), 6 + pos, Math.abs(len), bw - 1)
                    else g.fillRect(left + pos, Math.min(zero, zero - len), bw - 1, Math.abs(len))
                }
            } else {
                g.beginPath()
                for (var q = 0; q < vs.length; q++) { var px = left + slot * (q + 0.5), py = 6 + ph - (vs[q] - lo) / (hi - lo) * ph; if (q === 0) g.moveTo(px, py); else g.lineTo(px, py) }
                if (d.kind === "area") { g.lineTo(left + slot * (vs.length - 0.5), zero); g.lineTo(left + slot * 0.5, zero); g.closePath(); g.fillStyle = Qt.alpha(col, 0.35); g.fill() }
                else { g.strokeStyle = col; g.lineWidth = 2.5; g.stroke() }
            }
        }
    }
    function niceStep(x) { var p = Math.pow(10, Math.floor(Math.log(Math.max(x, 1e-9)) / Math.LN10)), f = x / p; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p }
    function fmtNum(v) { var a = Math.abs(v); return a >= 1e6 ? (v / 1e6).toFixed(a >= 1e7 ? 0 : 1) + "M" : a >= 1e4 ? (v / 1e3).toFixed(0) + "k" : String(Math.round(v * 100) / 100) }

    function stepRow(r, d) {        // the next row that shows (a filter hides some)
        if (!d) return r
        var n = r + d
        for (var k = 0; k < 100000 && n > 0 && Backend.rowHeight(n) === 0; k++) n += d
        return n < 0 ? r : n
    }
    // ---------------------------------------------------------------- keys on the grid
    function gridKey(e) {
        var ctrl = e.modifiers & Qt.ControlModifier, shift = e.modifiers & Qt.ShiftModifier, alt = e.modifiers & Qt.AltModifier
        var moves = { [Qt.Key_Up]: [-1, 0], [Qt.Key_Down]: [1, 0], [Qt.Key_Left]: [0, -1], [Qt.Key_Right]: [0, 1] }
        if (chartSel && (e.key === Qt.Key_Delete || e.key === Qt.Key_Backspace)) { var id = chartSel; chartSel = ""; Backend.removeChart(id); e.accepted = true; return }
        if (alt && e.key === Qt.Key_Down) { openPick(); e.accepted = true; return }
        if (moves[e.key]) { var d = moves[e.key], r = shift ? cr : ar, c = shift ? cc : ac
            if (ctrl) { var to = Backend.edge(r, c, d[0], d[1]); select(to[0], to[1], shift) } else select(stepRow(r, d[0]), c + d[1], shift)
            e.accepted = true; return }
        if (e.key === Qt.Key_PageDown || e.key === Qt.Key_PageUp) { var n = Math.max(1, main.bottomRow - main.topRow - 1) * (e.key === Qt.Key_PageDown ? 1 : -1); select((shift ? cr : ar) + n, shift ? cc : ac, shift); e.accepted = true; return }
        if (e.key === Qt.Key_Home) { select(ctrl ? 0 : (shift ? cr : ar), 0, shift); e.accepted = true; return }
        if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { var back = tabStart >= 0 && !shift ? tabStart : ac; select(stepRow(ar, shift ? -1 : 1), back, false); e.accepted = true; return }
        if (e.key === Qt.Key_Tab || e.key === Qt.Key_Backtab) { var from = tabStart >= 0 ? tabStart : ac; select(ar, ac + (e.key === Qt.Key_Backtab ? -1 : 1), false)
            if (e.key === Qt.Key_Tab) tabStart = from; e.accepted = true; return }
        if (e.key === Qt.Key_Delete || e.key === Qt.Key_Backspace) { Backend.clear(r0, c0, r1, c1, "contents"); tick++; e.accepted = true; return }
        if (e.key === Qt.Key_F2) { startEdit(); e.accepted = true; return }
        if (e.key === Qt.Key_Escape) { clip = null; menu = null; filterAt = null; pickAt = null; noteHover = null; e.accepted = true; return }
        if (alt && e.key === Qt.Key_Equal) { var at = Backend.autoSum(r0, c0, r1, c1); ar = cr = at[0]; ac = cc = at[1]; tick++; e.accepted = true; return }
        if (ctrl) {
            var k = e.key
            if (k === Qt.Key_C) copyCells(false)
            else if (k === Qt.Key_X) copyCells(true)
            else if (k === Qt.Key_V) pasteCells()
            else if (k === Qt.Key_Z && !shift) { Backend.undo(); tick++ }
            else if (k === Qt.Key_Y || (k === Qt.Key_Z && shift)) { Backend.redo(); tick++ }
            else if (k === Qt.Key_B) toggle("b")
            else if (k === Qt.Key_I) toggle("i")
            else if (k === Qt.Key_U) toggle("u")
            else if (k === Qt.Key_A) { var b = Backend.dataBlock(ar, ac, ar, ac); if (b[0] === r0 && b[1] === c0 && b[2] === r1 && b[3] === c1) b = [0, 0, Backend.rowCount - 1, Backend.colCount - 1]; ar = b[0]; ac = b[1]; cr = b[2]; cc = b[3] }
            else if (k === Qt.Key_D && r1 > r0) { Backend.fill(r0, c0, r0, c1, r1, c1); tick++ }
            else if (k === Qt.Key_R && c1 > c0) { Backend.fill(r0, c0, r1, c0, r1, c1); tick++ }
            else if (k === Qt.Key_Semicolon) { Backend.put(ar, ac, shift ? Qt.formatTime(new Date(), "hh:mm") : Qt.formatDate(new Date(), "yyyy-MM-dd")); tick++ }
            else if (k === Qt.Key_Space) { ar = 0; cr = Backend.rowCount - 1 }
            else if (k === Qt.Key_Minus) { if (r0 === 0 && r1 >= Backend.rowCount - 1) deleteColumn(); else deleteRow() }
            else if (k === Qt.Key_Plus || (k === Qt.Key_Equal && shift)) { if (r0 === 0 && r1 >= Backend.rowCount - 1) insertColumn(); else insertRow() }
            else if (k === Qt.Key_Home) select(0, 0, shift)
            else if (k === Qt.Key_End) { var u = Backend.lastCell(); select(u[0], u[1], shift) }
            else return
            e.accepted = true; return
        }
        if (shift && e.key === Qt.Key_Space) { ac = 0; cc = Backend.colCount - 1; e.accepted = true; return }
        if (e.text && e.text.length === 1 && e.text >= " ") {
            if (editing) { var ed = inBar ? barEdit : cellEdit; ed.insert(ed.cursorPosition, e.text); ed.forceActiveFocus() }   // typed before the box had the keys
            else startEdit(e.text)
            e.accepted = true }
    }

    // ---------------------------------------------------------------- the right-click menu
    Rectangle { visible: win.menu !== null; z: 50; x: Math.min(parent.width - width - 8, win.menu ? win.menu.x : 0); y: Math.min(parent.height - height - 8, win.menu ? win.menu.y : 0)
        width: 230; height: menuCol.height + 12; radius: 14; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        Column { id: menuCol; x: 6; y: 6; width: parent.width - 12; spacing: 1
            MenuItem { label: "Cut"; keys: "Ctrl+X"; onClicked: { win.menu = null; win.copyCells(true) } }
            MenuItem { label: "Copy"; keys: "Ctrl+C"; onClicked: { win.menu = null; win.copyCells(false) } }
            MenuItem { label: "Paste"; keys: "Ctrl+V"; onClicked: { win.menu = null; win.pasteCells() } }
            Rectangle { width: parent.width; height: 1; color: Theme.t.islandLine }
            MenuItem { label: "Rows Above"; onClicked: { win.menu = null; win.insertRow() } }
            MenuItem { label: "Columns to the Left"; onClicked: { win.menu = null; win.insertColumn() } }
            MenuItem { label: "Delete the Rows"; onClicked: { win.menu = null; win.deleteRow() } }
            MenuItem { label: "Delete the Columns"; onClicked: { win.menu = null; win.deleteColumn() } }
            Rectangle { width: parent.width; height: 1; color: Theme.t.islandLine }
            MenuItem { label: "Sort Smallest First"; onClicked: { win.menu = null; win.sortBy(false) } }
            MenuItem { label: "Sort Largest First"; onClicked: { win.menu = null; win.sortBy(true) } }
            MenuItem { label: "Clear"; keys: "Delete"; onClicked: { win.menu = null; Backend.clear(win.r0, win.c0, win.r1, win.c1, "contents"); win.tick++ } }
            MenuItem { label: "Clear the Formatting"; onClicked: { win.menu = null; Backend.clear(win.r0, win.c0, win.r1, win.c1, "formats"); win.tick++ } }
            Rectangle { width: parent.width; height: 1; color: Theme.t.islandLine }
            MenuItem { label: (win.tick, Backend.noteAt(win.ar, win.ac).text) ? "Edit the Note…" : "Add a Note…"; onClicked: { win.menu = null; win.noteCell() } }
            MenuItem { visible: (win.tick, !!Backend.noteAt(win.ar, win.ac).text); label: "Delete the Note"; onClicked: { win.menu = null; win.deleteNote() } }
            MenuItem { label: "Choices for These Cells…"; onClicked: { win.menu = null; win.choices() } } } }
    component MenuItem: Pressable { property string label: ""; property string keys: ""; width: parent ? parent.width : 200; height: 30; radius: 9; color: hovered ? Theme.t.hover : "transparent"
        Label { x: 10; anchors.verticalCenter: parent.verticalCenter; text: parent.label; font.pixelSize: 13 }
        Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: parent.keys; font.pixelSize: 11; secondary: true } }

    // ---------------------------------------------------------------- a filter's list
    Rectangle { id: filterBox; visible: win.filterAt !== null; z: 50; x: Math.min(parent.width - width - 8, win.filterAt ? win.filterAt.x - width + 20 : 0); y: Math.min(parent.height - height - 8, win.filterAt ? win.filterAt.y : 0)
        width: 250; height: Math.min(420, fCol.height + 96); radius: 14; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        property var hidden: []
        onVisibleChanged: if (visible) hidden = win.filterAt.values.filter(function (v) { return !v.shown }).map(function (v) { return v.value })
        MouseArea { anchors.fill: parent }
        Row { x: 8; y: 8; spacing: 4
            Seg { text: "A→Z"; onClicked: { var f = Backend.filterRange; Backend.sort(f[0], f[1], f[2], f[3], win.filterAt.c, false, true); win.filterAt = null; win.tick++ } }
            Seg { text: "Z→A"; onClicked: { var f = Backend.filterRange; Backend.sort(f[0], f[1], f[2], f[3], win.filterAt.c, true, true); win.filterAt = null; win.tick++ } }
            Seg { text: "All"; onClicked: filterBox.hidden = [] } }
        Flickable { x: 6; y: 44; width: parent.width - 12; height: parent.height - 96; contentHeight: fCol.height; clip: true; boundsBehavior: Flickable.StopAtBounds
            Column { id: fCol; width: parent.width
                Repeater { model: win.filterAt ? win.filterAt.values : []
                    Pressable { required property var modelData; readonly property bool shown: filterBox.hidden.indexOf(modelData.value) < 0; width: fCol.width; height: 28; radius: 8; color: hovered ? Theme.t.hover : "transparent"
                        onClicked: { var h = filterBox.hidden.slice(), i = h.indexOf(modelData.value); if (i >= 0) h.splice(i, 1); else h.push(modelData.value); filterBox.hidden = h }
                        Rectangle { x: 8; anchors.verticalCenter: parent.verticalCenter; width: 16; height: 16; radius: 4; color: parent.shown ? Theme.t.accent : "transparent"; border.width: 1; border.color: parent.shown ? Theme.t.accent : Theme.t.islandLine
                            Glyph { visible: parent.parent.shown; anchors.centerIn: parent; name: "check"; size: 11; ink: Theme.t.onAccent } }
                        Label { x: 32; width: parent.width - 40; anchors.verticalCenter: parent.verticalCenter; text: modelData.label; elide: Text.ElideRight; font.pixelSize: 12 } } } } }
        Row { anchors { right: parent.right; rightMargin: 8; bottom: parent.bottom; bottomMargin: 8 } spacing: 6
            Btn { text: "Cancel"; onClicked: win.filterAt = null }
            Btn { text: "Show"; primary: true; onClicked: { Backend.setFilterHidden(win.filterAt.c, filterBox.hidden); win.filterAt = null; win.tick++ } } } }
    MouseArea { anchors.fill: parent; z: 49; visible: win.menu !== null || win.filterAt !== null || win.pop !== "" || win.pickAt !== null; acceptedButtons: Qt.AllButtons
        onPressed: { win.menu = null; win.filterAt = null; win.pop = ""; win.pickAt = null } }

    // ---------------------------------------------------------------- a cell's list of choices
    Rectangle { visible: win.pickAt !== null; z: 50; x: Math.max(8, Math.min(parent.width - width - 8, win.pickAt ? win.pickAt.x - width : 0)); y: Math.min(parent.height - height - 8, win.pickAt ? win.pickAt.y : 0)
        width: win.pickAt ? Math.min(320, win.pickAt.w + 30) : 160; height: Math.min(300, pickCol.height + 12); radius: 12; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        Flickable { anchors { fill: parent; margins: 6 } contentHeight: pickCol.height; clip: true; interactive: pickCol.height > height
            Column { id: pickCol; width: parent.width; spacing: 1
                Repeater { model: win.pickAt ? win.pickAt.items : []
                    Pressable { required property string modelData; width: pickCol.width; height: 28; radius: 8
                        readonly property bool now: win.pickAt && (win.tick, Backend.raw(win.pickAt.r, win.pickAt.c)) === modelData
                        color: hovered ? Theme.t.hover : now ? Qt.alpha(Theme.t.accent, 0.16) : "transparent"; onClicked: win.pick(modelData)
                        Label { x: 10; width: parent.width - 20; anchors.verticalCenter: parent.verticalCenter; text: modelData; elide: Text.ElideRight; font.pixelSize: 13 } } } } } }

    // ---------------------------------------------------------------- a note, while the pointer rests on its cell
    Rectangle { visible: win.noteHover !== null && !win.noteEdit; z: 48; x: Math.min(parent.width - width - 8, win.noteHover ? win.noteHover.x : 0); y: Math.min(parent.height - height - 8, win.noteHover ? win.noteHover.y : 0)
        width: Math.min(280, Math.max(140, noteText.implicitWidth + 24)); height: noteText.height + noteBy.height + 22; radius: 10
        color: "#FFF9DB"; border.width: 1; border.color: "#E9D8A6"
        Label { id: noteBy; x: 12; y: 8; visible: text !== ""; text: win.noteHover ? win.noteHover.by : ""; color: "#5C4813"; font.pixelSize: 11; font.weight: Font.DemiBold }
        Label { id: noteText; x: 12; y: noteBy.visible ? noteBy.y + noteBy.height + 3 : 8; width: Math.min(256, implicitWidth); wrapMode: Text.Wrap; text: win.noteHover ? win.noteHover.text : ""; color: "#2B2F33"; font.pixelSize: 12 } }

    // ---------------------------------------------------------------- writing a note
    Item { anchors.fill: parent; z: 60; visible: win.noteEdit !== null
        Rectangle { anchors.fill: parent; color: "#55000000"; MouseArea { anchors.fill: parent; onClicked: win.noteEdit = null } }
        Rectangle { anchors.centerIn: parent; width: 440; height: noteCol.height + 36; radius: 18; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
            MouseArea { anchors.fill: parent }
            Column { id: noteCol; x: 18; y: 18; width: parent.width - 36; spacing: 12
                Label { text: "Note on " + (win.noteEdit ? win.name(win.noteEdit.r, win.noteEdit.c) : ""); font.pixelSize: 16; font.weight: Font.DemiBold }
                TextBox { id: noteBox; width: parent.width; lines: 5; placeholder: "A few words about this cell" }
                Row { anchors.right: parent.right; spacing: 8
                    Btn { text: "Cancel"; onClicked: { win.noteEdit = null; gridKeys.forceActiveFocus() } }
                    Btn { primary: true; text: "Save the Note"; onClicked: win.saveNote() } } } } }

    // ---------------------------------------------------------------- rename or delete a sheet: click the tab that's in front
    MouseArea { visible: win.naming >= 0; anchors.fill: parent; z: 59; onClicked: win.naming = -1 }
    Rectangle { visible: win.naming >= 0; z: 60; x: win.gridX; anchors { bottom: parent.bottom; bottomMargin: 60 } width: 340; height: 112; radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        MouseArea { anchors.fill: parent }
        function done() { Backend.renameSheet(win.naming, rename.text); win.naming = -1 }
        Label { x: 16; y: 12; text: "SHEET NAME"; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold }
        Field { id: rename; x: 14; y: 32; width: parent.width - 28; icon: "edit"; placeholder: "Name"; onAccepted: parent.done() }
        Row { anchors { right: parent.right; rightMargin: 14; bottom: parent.bottom; bottomMargin: 10 } spacing: 8
            Btn { text: "Duplicate"; onClicked: { Backend.duplicateSheet(win.naming); win.naming = -1 } }
            Btn { visible: Backend.sheetNames.length > 1; text: "Delete Sheet"; danger: true; onClicked: { Backend.removeSheet(win.naming); win.naming = -1 } }
            Btn { text: "Rename"; primary: true; onClicked: parent.parent.done() } } }
    TextEdit { id: clipHelper; visible: false; textFormat: TextEdit.PlainText }
    // the cells a formula being typed refers to, each outlined in its own colour, as in Excel
    readonly property var refColours: ["#1C7ED6", "#E03131", "#7048E8", "#2F9E44", "#F08C00", "#C2255C"]
    readonly property var refs: {
        if (!editing) return []
        var t = cellEdit.text; if (t.charAt(0) !== "=") return []
        var out = [], re = /(^|[^A-Za-z0-9_.!'"])(\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?)(?![A-Za-z0-9_(!])/g, m
        while ((m = re.exec(t)) !== null) {
            var sp = Backend.spanOf(m[2].replace(/\$/g, "")); if (sp.length === 4) out.push({ r0: sp[0], c0: sp[1], r1: sp[2], c1: sp[3], colour: refColours[out.length % refColours.length] })
        }
        return out
    }
    function refAt(r, c) { for (var k = 0; k < refs.length; k++) { var f = refs[k]; if (r >= f.r0 && r <= f.r1 && c >= f.c0 && c <= f.c1) return f } return null }
}
