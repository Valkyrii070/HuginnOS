import QtQuick
import QtQuick.Shapes

// Slides, "filmstrip island": the slide on a stage; the filmstrip is the island the light comes from.
// Every slide is a free canvas: text boxes, shapes and pictures anywhere, at any size and angle, with the layout's
// placeholders to start from. Click to choose, drag to move (with guides), handles to size and turn, click again to type.
GlassWindow {
    id: win
    title: "Slides"; heading: browsing ? "" : (Backend.title || ""); width: 1280; height: 820; glow: "bottom"; bare: presenting
    sidebarWidth: browsing ? 232 : 0
    property bool browsing: Backend.current === ""
    property string notice: ""
    property string exported: ""
    property bool notesOpen: true
    property bool finding: false
    // the canvas
    property var sel: []                    // the chosen items' ids
    property string editId: ""              // the item being typed in
    property var preview: ({})              // a drag in progress
    property var guides: []                 // smart guides while dragging: [{v: true, at: x}]
    property var band: null                 // a rubber band: {x, y, w, h}
    property var menu: null                 // the right-click menu: {x, y, slide}
    property string pop: ""
    property Item popFrom: null
    property var fmt: ({})                  // the formatting where the typing is (or of the chosen item)
    property bool bgAll: false
    property bool trAll: false
    property int tick: 0
    readonly property var cur: Backend.count > 0 ? Backend.slides[Math.min(Backend.index, Backend.count - 1)] : ({ items: [], frameItems: [], bg: ({}) })
    readonly property real k: face.k
    // presenting
    property bool presenting: false
    property bool presenterUi: false
    property int showIndex: 0
    property int showStep: 0
    property bool forward: true
    property bool showEnded: false
    property string blank: ""               // "black" or "white" while the screen is blanked
    property int elapsed: 0
    property bool timing: false
    property string typed: ""               // a slide number typed while presenting
    property real notesSize: 18

    function say(t) { notice = t; hide.restart() }
    function item(id) { var a = cur.items; for (var i = 0; i < a.length; i++) if (a[i].id === id) return a[i]; return null }
    function chosen() { var out = []; for (var i = 0; i < sel.length; i++) { var it = item(sel[i]); if (it) out.push(it) } return out }
    function isLine(it) { return it && it.kind === "shape" && (it.shape === "line" || it.shape === "arrowline") }
    function hasText(it) { return it && (it.kind === "text" || (it.kind === "shape" && !isLine(it))) }
    function geo(it) { var p = preview[it.id]; return p ? { x: p.x, y: p.y, w: p.w, h: p.h, rot: p.rot !== undefined ? p.rot : (it.rot || 0) } : { x: it.x, y: it.y, w: it.w, h: it.h, rot: it.rot || 0 } }
    function bounds(list) {
        if (!list.length) return null
        var x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9
        for (var i = 0; i < list.length; i++) { var g = geo(list[i]); x0 = Math.min(x0, g.x); y0 = Math.min(y0, g.y); x1 = Math.max(x1, g.x + g.w); y1 = Math.max(y1, g.y + g.h) }
        return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 }
    }
    Connections { target: Backend
        function onFailed(msg) { win.say(msg) }
        function onDeckChanged() { win.tick++; win.sel = win.sel.filter(function (id) { return win.item(id) !== null }); if (win.editId && !win.item(win.editId)) win.editId = ""; win.refreshFmt() } }
    Timer { id: hide; interval: 7000; onTriggered: { win.notice = ""; win.exported = "" } }
    onClosing: { endEdit(); Backend.save() }
    onSelChanged: refreshFmt()

    // ------------------------------------------------------------------ actions (the menus call these too)
    function openFile() { Picker.open("Open a presentation", [["Presentations", "*.pptx *.odp *.ppt *.hslides"]], function (paths) { if (paths.length) Backend.open(paths[0]) }) }
    function exportPdf() { doExport("pdf") }
    function doExport(kind) { endEdit(); var p = Backend.export(kind); if (p) { exported = p; hide.restart() } }
    function newSlide() { if (Backend.current !== "") { endEdit(); Backend.add(""); sel = [] } }
    function duplicateSlide() { if (Backend.current !== "") { endEdit(); Backend.duplicate() } }
    function deleteSlide() { if (Backend.current !== "" && Backend.count > 1) { endEdit(); Backend.remove() } }
    function toggleHidden() { if (Backend.count) Backend.setHidden(Backend.index, !cur.hidden) }
    function moveSlideUp() { Backend.move(-1) }
    function moveSlideDown() { Backend.move(1) }
    function insertText() { if (Backend.current === "") return; endEdit(); var id = Backend.addItem("text", ""); if (id) { sel = [id]; Qt.callLater(function () { win.startEdit(id) }) } }
    function insertPicture() { if (Backend.current === "") return
        Picker.open("Put in a picture", [["Pictures", "*.png *.jpg *.jpeg *.webp *.gif *.bmp"]], function (paths) { if (paths.length) { var id = Backend.addItem("picture", paths[0]); if (id) win.sel = [id] } }) }
    function insertShape() { openPop("insertShape", fmtBar.visible ? addBtn2 : shapeBtn) }
    function openLayouts() { openPop("layout", layoutBtn) }
    function openBackground() { openPop("bg", bgBtn) }
    function openTransition() { openPop("transition", trBtn) }
    function toggleNotes() { notesOpen = !notesOpen }
    function find() { if (Backend.current !== "") { finding = true; findBox.input.forceActiveFocus() } }
    function present() { start(0, false) }
    function presentHere() { start(Backend.index, false) }
    function presenterView() { start(Backend.index, true) }
    function menuUndo() { if (editId) editor.undo(); else Backend.undo() }
    function menuRedo() { if (editId) editor.redo(); else Backend.redo() }
    function menuCut() { if (editId) editor.cut(); else if (sel.length) { Backend.copyItems(sel); Backend.removeItems(sel); sel = [] } }
    function menuCopy() { if (editId) editor.copy(); else if (sel.length) Backend.copyItems(sel) }
    function menuPaste() { if (editId) editor.paste(); else { var got = Backend.pasteItems(); if (got.length) sel = got } }
    function menuSelectAll() { if (editId) editor.selectAll(); else sel = cur.items.filter(function (it) { return !it.locked }).map(function (it) { return it.id }) }
    function duplicateItems() { if (sel.length) { var got = Backend.duplicateItems(sel); if (got.length) sel = got } else duplicateSlide() }
    function deleteItems() { if (sel.length && !editId) { Backend.removeItems(sel); sel = [] } }
    function arrange(how) { if (sel.length) Backend.order(sel, how) }
    function apply(what) {          // formatting: on the typing's selection, or on all the chosen items' text
        if (editId) {
            var a = editor.selectionStart, b = editor.selectionEnd, back = Backend.style(editId, a, b, what)
            editor.forceActiveFocus(); if (back.length === 2) editor.select(back[0], back[1]); refreshFmt()
        } else if (sel.length) { Backend.styleItems(sel, what); refreshFmt() }
    }
    function refreshFmt() { fmtTimer.restart() }
    Timer { id: fmtTimer; interval: 60; onTriggered: win.fmt = win.editId ? Backend.formatAt(win.editId, editor.cursorPosition) : (win.sel.length ? Backend.itemFormat(win.sel[0]) : ({})) }
    function openPop(kind, from) { if (pop === kind) { pop = ""; return } popFrom = from; pop = kind }

    // ------------------------------------------------------------------ typing in an item
    function startEdit(id, px, py) {
        var it = item(id)
        if (!it || !hasText(it) || it.locked) return
        if (editId && editId !== id) endEdit()
        sel = [id]; editId = id
        Backend.loadEditor(id); commitTimer.stop()
        editor.forceActiveFocus()
        if (px !== undefined) {
            var g = geo(it), cx = g.x + g.w / 2, cy = g.y + g.h / 2, a = -(g.rot || 0) * Math.PI / 180
            var dx = px - cx, dy = py - cy, lx = dx * Math.cos(a) - dy * Math.sin(a) + g.w / 2, ly = dx * Math.sin(a) + dy * Math.cos(a) + g.h / 2
            var f = it.fit || 1
            editor.cursorPosition = editor.positionAt((lx - 14.4) / f, (ly - editor.y) / f)
        } else editor.cursorPosition = editor.length
        refreshFmt()
    }
    function endEdit() {
        if (!editId) return
        commitTimer.stop(); Backend.commitEdit(editId)
        editId = ""; canvasKeys.forceActiveFocus()
    }
    Timer { id: commitTimer; interval: 450; onTriggered: if (win.editId) Backend.commitEdit(win.editId) }

    // ------------------------------------------------------------------ presenting
    function visibleFrom(i, step) { var n = Backend.count; while (i >= 0 && i < n && Backend.slides[i].hidden) i += step; return i }
    function start(from, withPresenter) {
        if (Backend.current === "" || Backend.count === 0) return
        endEdit(); pop = ""; menu = null
        var i = visibleFrom(from, 1); if (i >= Backend.count) i = visibleFrom(from, -1); if (i < 0) return
        showIndex = i; showStep = 0; showEnded = false; blank = ""; elapsed = 0; timing = true; forward = true; typed = ""
        var screens = Qt.application.screens
        presenting = true
        if (screens.length > 1 || withPresenter) {
            presenterUi = true
            if (screens.length > 1) {
                var other = screens[0].name === win.screen.name ? screens[1] : screens[0]
                audience.screen = other; audience.showFullScreen()
            }
        } else presenterUi = false
        showFullScreen()
        Qt.callLater(function () { (win.presenterUi ? presenterKeys : stageKeys).forceActiveFocus() })
    }
    function stop() { presenting = false; presenterUi = false; timing = false; audience.close(); showNormal(); Backend.select(Math.min(showIndex, Backend.count - 1)); canvasKeys.forceActiveFocus() }
    function next() {
        if (showEnded) { stop(); return }
        var steps = Backend.slides[showIndex].steps || 0
        forward = true
        if (showStep < steps) { showStep++; return }
        var n = visibleFrom(showIndex + 1, 1)
        if (n >= Backend.count) { showEnded = true; return }
        showStep = 0; showIndex = n
    }
    function prev() {
        forward = false
        if (showEnded) { showEnded = false; return }
        if (showStep > 0) { showStep--; return }
        var p = visibleFrom(showIndex - 1, -1)
        if (p < 0) return
        showIndex = p; showStep = Backend.slides[p].steps || 0
    }
    function goTo(i) { if (i >= 0 && i < Backend.count) { forward = false; showEnded = false; showIndex = i; showStep = 0 } }
    function showKey(e) {
        var k = e.key
        if (k >= Qt.Key_0 && k <= Qt.Key_9) { typed += String(k - Qt.Key_0); e.accepted = true; return }
        if ((k === Qt.Key_Return || k === Qt.Key_Enter) && typed !== "") { goTo(parseInt(typed) - 1); typed = ""; e.accepted = true; return }
        typed = ""
        if (k === Qt.Key_Escape) stop()
        else if (k === Qt.Key_Right || k === Qt.Key_Down || k === Qt.Key_Space || k === Qt.Key_PageDown || k === Qt.Key_Return || k === Qt.Key_Enter || k === Qt.Key_N) { if (blank) blank = ""; else next() }
        else if (k === Qt.Key_Left || k === Qt.Key_Up || k === Qt.Key_PageUp || k === Qt.Key_Backspace || k === Qt.Key_P) { if (blank) blank = ""; else prev() }
        else if (k === Qt.Key_Home) goTo(visibleFrom(0, 1))
        else if (k === Qt.Key_End) goTo(visibleFrom(Backend.count - 1, -1))
        else if (k === Qt.Key_B || k === Qt.Key_Period) blank = blank === "black" ? "" : "black"
        else if (k === Qt.Key_W || k === Qt.Key_Comma) blank = blank === "white" ? "" : "white"
        else return
        e.accepted = true
    }
    Timer { interval: 1000; repeat: true; running: win.presenting && win.timing; onTriggered: win.elapsed++ }
    function clock(s) { var m = Math.floor(s / 60); return (m < 10 ? "0" : "") + m + ":" + (s % 60 < 10 ? "0" : "") + (s % 60) }

    // ------------------------------------------------------------------ the islands
    sidebar: [ DocList { newLabel: "New Presentation"; icon: "slides"; empty: "Presentations you make appear here, along with PowerPoint files in your Documents folder." } ]
    toolbar: [
        Seg { id: presentBtn; visible: !win.browsing; icon: "play"; text: "Present"; on: true; onClicked: win.openPop("present", presentBtn) },
        ExportMenu { visible: !win.browsing
            choices: [["pdf", "PDF", "One page per slide, text you can select"], ["pptx", "PowerPoint", "A .pptx file with every slide as it is here"]].concat(
                     Backend.converter ? [["odp", "OpenDocument", "An .odp file for LibreOffice Impress"]] : [])
            onChosen: function (key) { win.doExport(key) } },
        Seg { id: themeBtn; visible: !win.browsing; icon: "palette"; tip: "Theme and slide size"; onClicked: win.openPop("theme", themeBtn) },
        Seg { visible: !win.browsing; icon: "edit"; tip: "Speaker notes"; on: win.notesOpen; onClicked: win.notesOpen = !win.notesOpen },
        Seg { visible: !win.browsing; icon: "search"; tip: "Find (Ctrl+F)"; on: win.finding; onClicked: win.finding ? (win.finding = false) : win.find() },
        Seg { visible: !win.browsing; icon: "redo"; tip: "Redo"; opacity: Backend.canRedo ? 1 : 0.4; onClicked: win.menuRedo() },
        Seg { visible: !win.browsing; icon: "undo"; tip: "Undo"; opacity: Backend.canUndo ? 1 : 0.4; onClicked: win.menuUndo() },
        Seg { visible: !win.browsing; icon: "back"; tip: "All presentations"; onClicked: { win.endEdit(); Backend.save(); win.browsing = true } }
    ]
    Connections { target: Backend; function onChanged() { if (Backend.current !== "" && win.browsing && Backend.count > 0 && !win.wasOpen) { win.browsing = false } win.wasOpen = Backend.current !== "" } }
    property bool wasOpen: Backend.current !== ""

    islands: [
        // what goes on a slide: the slide's layout, text, shapes, pictures; its background and transition
        Island { id: insertBar; visible: !win.browsing && !win.presenting && !fmtBar.visible; y: 12; z: 8
            x: Math.max(win.titleEnd + 12, Math.min(win.toolStart - width - 12, (win.width - width) / 2))
            Pick { id: layoutBtn; span: 132; text: "Layout: " + ((Backend.samples.filter(function (s) { return s.key === win.cur.layout })[0] || { name: "" }).name); onClicked: win.openPop("layout", layoutBtn) }
            Gap {}
            Tool { icon: "type"; tip: "Text box"; onClicked: win.insertText() }
            Tool { id: shapeBtn; icon: "shapes"; tip: "Shape"; on: win.pop === "insertShape"; onClicked: win.openPop("insertShape", shapeBtn) }
            Tool { icon: "image"; tip: "Picture"; onClicked: win.insertPicture() }
            Gap {}
            Tool { id: bgBtn; icon: "bucket"; tip: "Background"; on: win.pop === "bg"; onClicked: win.openPop("bg", bgBtn) }
            Tool { id: trBtn; icon: "layers"; tip: "Transition"; on: win.pop === "transition" || (win.cur.transition && win.cur.transition.kind !== "none"); onClicked: win.openPop("transition", trBtn) }
            Tool { icon: win.cur.hidden ? "eyeoff" : "eye"; tip: win.cur.hidden ? "Hidden in the show: show it" : "Hide this slide in the show"; on: !!win.cur.hidden; onClicked: win.toggleHidden() } },
        // the filmstrip
        Island { id: strip; visible: !win.browsing && !win.presenting; height: 86; radius: 20; pad: 8; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 14 }
            Flickable { id: stripFlick; width: Math.min(nav.width, win.width - 330); height: 70; contentWidth: nav.width; clip: true; anchors.verticalCenter: parent.verticalCenter
                flickableDirection: Flickable.HorizontalFlick; interactive: !win.dragSlide
                Row { id: nav; spacing: 8; height: 70
                    Repeater { model: Backend.slides
                        Thumb { required property var modelData; required property int index; view: modelData; at: index } } }
                Rectangle { visible: win.dropAt >= 0; x: win.dropAt * 128 - 5; y: 4; width: 3; height: 62; radius: 1.5; color: Theme.t.accent } }
            Seg { id: addBtn; icon: "plus"; tip: "New slide (Ctrl+M) · hold for a layout"; tipAbove: true; on: win.pop === "addSlide"; onClicked: win.newSlide()
                MouseArea { anchors.fill: parent; acceptedButtons: Qt.RightButton; onClicked: win.openPop("addSlide", addBtn) }
                Rectangle { anchors { right: parent.right; bottom: parent.bottom; margins: -2 } width: 14; height: 14; radius: 7; color: Theme.t.group
                    Glyph { anchors.centerIn: parent; name: "down"; size: 9; ink: Theme.t.text_secondary }
                    MouseArea { anchors.fill: parent; anchors.margins: -2; onClicked: win.openPop("addSlide", addBtn) } } } },
        Island {   // saved or not, and which slide
            visible: !win.browsing && !win.presenting; anchors { left: parent.left; leftMargin: 14; bottom: parent.bottom; bottomMargin: 14 }
            Label { leftPadding: 10; rightPadding: 10; width: Math.min(implicitWidth, Math.max(120, (win.width - strip.width) / 2 - 50)); elide: Text.ElideMiddle; font.pixelSize: 12
                anchors.verticalCenter: parent.verticalCenter; color: win.notice ? Theme.t.danger : Theme.t.text_secondary
                text: win.notice || (win.exported ? "Exported to " + win.exported : ((Backend.saved ? "Saved" : "Saving…") + "  ·  " + (Backend.index + 1) + " of " + Backend.count)) }
            Seg { visible: win.exported !== ""; text: "Show"; onClicked: Backend.reveal(win.exported) } },
        // find and replace
        Island { visible: win.finding && !win.browsing && !win.presenting; y: 60; x: (win.width - width) / 2; z: 9
            TextBox { id: findBox; width: 200; height: 30; placeholder: "Find in the slides"; anchors.verticalCenter: parent.verticalCenter
                onAccepted: win.findNext(1)
                Keys.onPressed: function (e) { if (e.key === Qt.Key_Escape) { win.finding = false; canvasKeys.forceActiveFocus(); e.accepted = true } } }
            Label { anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 11; secondary: true; width: 80; horizontalAlignment: Text.AlignHCenter
                text: findBox.text ? (win.tick, Backend.findText(findBox.text).length) + " slides" : "" }
            Seg { icon: "up"; onClicked: win.findNext(-1) }
            Seg { icon: "down"; onClicked: win.findNext(1) }
            TextBox { id: replaceBox; width: 150; height: 30; placeholder: "Replace with"; anchors.verticalCenter: parent.verticalCenter }
            Seg { text: "Replace All"; onClicked: { win.endEdit(); var n = Backend.replaceAll(findBox.text, replaceBox.text); win.say(n + " replaced") } }
            Seg { icon: "x"; onClicked: { win.finding = false; canvasKeys.forceActiveFocus() } } },
        // formatting, floating by what's chosen
        Island { id: fmtBar; z: 9
            readonly property var list: (win.tick, win.chosen())
            readonly property var box: (win.tick, win.bounds(fmtBar.list))
            readonly property bool texty: win.editId !== "" || fmtBar.list.some(function (it) { return it.kind === "text" })
            readonly property bool shapey: win.editId === "" && fmtBar.list.length > 0 && fmtBar.list.every(function (it) { return it.kind === "shape" })
            readonly property bool liney: fmtBar.list.length > 0 && fmtBar.list.every(function (it) { return win.isLine(it) })
            readonly property bool picture: fmtBar.list.length === 1 && fmtBar.list[0].kind === "picture"
            // in the top row, where the tools to add things are when nothing is chosen
            visible: !win.browsing && !win.presenting && fmtBar.list.length > 0
            y: 12; x: Math.max(win.titleEnd + 12, Math.min(win.toolStart - width - 12, (win.width - width) / 2))
            Tool { id: addBtn2; icon: "plus"; tip: "Add a text box, shape or picture"; on: win.pop === "add"; onClicked: win.openPop("add", addBtn2) }
            Gap { visible: fmtBar.texty }
            Pick { id: fontPick; visible: fmtBar.texty; span: 118; text: win.fmt.font || "Font"; onClicked: win.openPop("font", fontPick) }
            Pick { id: sizePick; visible: fmtBar.texty; span: 58; text: win.fmt.size ? String(win.fmt.size) : "–"; onClicked: win.openPop("size", sizePick) }
            Tool { visible: fmtBar.texty; icon: "bold"; tip: "Bold (Ctrl+B)"; on: !!win.fmt.b; onClicked: win.apply("bold") }
            Tool { visible: fmtBar.texty; icon: "italic"; tip: "Italic (Ctrl+I)"; on: !!win.fmt.i; onClicked: win.apply("italic") }
            Tool { visible: fmtBar.texty && win.width > 1250; icon: "underline"; tip: "Underline (Ctrl+U)"; on: !!win.fmt.u; onClicked: win.apply("underline") }
            Tool { id: inkBtn; visible: fmtBar.texty; tip: "Text colour"; onClicked: win.openPop("ink", inkBtn)
                Label { anchors.centerIn: parent; anchors.verticalCenterOffset: -2; text: "A"; font.pixelSize: 14; font.weight: Font.Bold }
                Rectangle { x: 8; y: 22; width: 14; height: 3; radius: 1.5; color: win.fmt.color || Theme.t.text } }
            Tool { id: alignBtn; visible: fmtBar.texty; icon: win.fmt.align === "center" ? "aligncenter" : win.fmt.align === "right" ? "alignright" : win.fmt.align === "justify" ? "alignjustify" : "alignleft"
                tip: "Alignment"; onClicked: win.openPop("align", alignBtn) }
            Tool { visible: fmtBar.texty; icon: "list"; tip: "Bullets"; on: win.fmt.list === "bullet"; onClicked: win.apply("bullet") }
            Tool { visible: fmtBar.texty; icon: "numbers"; tip: "Numbering"; on: win.fmt.list === "number"; onClicked: win.apply("number") }
            Tool { visible: fmtBar.texty && win.editId !== ""; text: "⇤"; tip: "Less indent (Shift+Tab)"; onClicked: win.apply("outdent") }
            Tool { visible: fmtBar.texty && win.editId !== ""; text: "⇥"; tip: "More indent (Tab)"; onClicked: win.apply("indent") }
            Gap { visible: fmtBar.shapey }
            Tool { id: fillBtn; visible: fmtBar.shapey && !fmtBar.liney; tip: "Fill"; onClicked: win.openPop("fill", fillBtn)
                Glyph { anchors.centerIn: parent; anchors.verticalCenterOffset: -2; name: "bucket"; size: 14; ink: Theme.t.icon }
                Rectangle { x: 8; y: 22; width: 14; height: 3; radius: 1.5; color: fmtBar.list.length && fmtBar.list[0].fillHex ? fmtBar.list[0].fillHex : "transparent"; border.width: 1; border.color: Theme.t.islandLine } }
            Tool { id: lineBtn; visible: fmtBar.shapey; tip: "Outline"; onClicked: win.openPop("line", lineBtn)
                Rectangle { anchors.centerIn: parent; anchors.verticalCenterOffset: -2; width: 14; height: 12; radius: 2; color: "transparent"; border.width: 2; border.color: Theme.t.icon }
                Rectangle { x: 8; y: 22; width: 14; height: 3; radius: 1.5; color: fmtBar.list.length && fmtBar.list[0].lineHex ? fmtBar.list[0].lineHex : "transparent"; border.width: 1; border.color: Theme.t.islandLine } }
            Pick { id: kindBtn; visible: fmtBar.shapey && fmtBar.list.length === 1 && !fmtBar.liney; span: 46; text: "◆"; onClicked: win.openPop("shape", kindBtn) }
            Tool { visible: fmtBar.picture; icon: "image"; tip: "Replace the picture"; onClicked: win.replacePicture() }
            Gap {}
            Tool { id: arrangeBtn; icon: "layers"; tip: "Arrange and align"; onClicked: win.openPop("arrange", arrangeBtn) }
            Tool { id: buildBtn; icon: "sparkle"; tip: "Build: how it comes in while presenting"; on: fmtBar.list.length > 0 && !!fmtBar.list[0].anim; onClicked: win.openPop("build", buildBtn) }
            Tool { icon: "trash"; tip: "Delete"; onClicked: { win.endEdit(); win.deleteItems() } } }
    ]
    function findNext(dir) {
        var hits = Backend.findText(findBox.text)
        if (!hits.length) { say("Not found"); return }
        var at = Backend.index, pick = hits[0]
        if (dir > 0) { pick = hits.filter(function (i) { return i > at })[0]; if (pick === undefined) pick = hits[0] }
        else { var before = hits.filter(function (i) { return i < at }); pick = before.length ? before[before.length - 1] : hits[hits.length - 1] }
        endEdit(); Backend.select(pick)
    }
    function replacePicture() { if (sel.length !== 1) return; var id = sel[0]
        Picker.open("Another picture", [["Pictures", "*.png *.jpg *.jpeg *.webp *.gif *.bmp"]], function (paths) { if (paths.length) Backend.replacePicture(id, paths[0]) }) }

    component Tool: Pressable { id: t; property string icon: ""; property string text: ""; property bool on: false; property string tip: ""; property int span: 30
        width: visible ? span : 0; height: 30; radius: 11; anchors.verticalCenter: parent ? parent.verticalCenter : undefined; color: on ? Theme.t.accent : (hovered ? Theme.t.hover : "transparent")
        Glyph { visible: t.icon !== ""; anchors.centerIn: parent; name: t.icon; size: 16; ink: t.on ? Theme.t.onAccent : Theme.t.icon }
        Label { visible: t.text !== ""; anchors.centerIn: parent; text: t.text; color: t.on ? Theme.t.onAccent : Theme.t.text; font.pixelSize: 14; font.weight: Font.DemiBold }
        Rectangle { visible: t.hovered && t.tip !== "" && win.pop === ""; z: 9; color: Theme.t.tooltip_bg; border.width: 1; border.color: Theme.t.menu_border; radius: 6; width: tt.width + 14; height: 24
            anchors { top: parent.bottom; topMargin: 10; horizontalCenter: parent.horizontalCenter }
            Label { id: tt; anchors.centerIn: parent; text: t.tip; font.pixelSize: 11 } } }
    component Pick: Pressable { id: pk; property string text: ""; property int span: 90
        width: visible ? span : 0; height: 30; radius: 10; anchors.verticalCenter: parent ? parent.verticalCenter : undefined; color: hovered ? Theme.t.hover : Theme.t.group
        Label { x: 10; width: parent.width - 28; anchors.verticalCenter: parent.verticalCenter; text: pk.text; elide: Text.ElideRight; font.pixelSize: 12 }
        Glyph { anchors { right: parent.right; rightMargin: 7; verticalCenter: parent.verticalCenter } name: "down"; size: 11; ink: Theme.t.text_secondary } }
    component Gap: Item { width: visible ? 9 : 0; height: 30; anchors.verticalCenter: parent ? parent.verticalCenter : undefined; Rectangle { anchors.centerIn: parent; width: 1; height: 16; color: Theme.t.islandLine } }

    // ------------------------------------------------------------------ a slide in the filmstrip
    property bool dragSlide: false
    property int dropAt: -1
    component Thumb: Item {
        id: th
        property var view: ({})
        property int at: 0
        readonly property bool here: Backend.index === at
        width: 120; height: 70
        Rectangle { anchors.fill: parent; radius: 10; color: "transparent"; border.width: th.here ? 2 : 0; border.color: Theme.t.accent }
        SlideFace { id: tf; x: 4; y: 4; width: 112; slide: th.view; opacity: th.view.hidden ? 0.4 : 1 }
        Rectangle { anchors.fill: tf; color: "transparent"; border.width: 1; border.color: Theme.t.islandLine; radius: 2 }
        Rectangle { x: 8; y: 8; width: n.width + 8; height: 15; radius: 5; color: "#99000000"
            Label { id: n; anchors.centerIn: parent; text: th.at + 1; color: "#FFFFFF"; font.pixelSize: 9; font.weight: Font.Bold } }
        Row { anchors { right: tf.right; bottom: tf.bottom; margins: 4 } spacing: 3
            Rectangle { visible: !!th.view.hidden; width: 15; height: 15; radius: 5; color: "#99000000"; Glyph { anchors.centerIn: parent; name: "eyeoff"; size: 10; ink: "#FFFFFF" } }
            Rectangle { visible: (th.view.steps || 0) > 0; width: 15; height: 15; radius: 5; color: "#99000000"; Glyph { anchors.centerIn: parent; name: "sparkle"; size: 10; ink: "#FFFFFF" } }
            Rectangle { visible: !!th.view.transition && th.view.transition.kind !== "none"; width: 15; height: 15; radius: 5; color: "#99000000"; Glyph { anchors.centerIn: parent; name: "layers"; size: 10; ink: "#FFFFFF" } } }
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton; preventStealing: win.dragSlide
            property real fromX: 0
            onPressed: function (m) { fromX = m.x; if (m.button === Qt.LeftButton) { win.endEdit(); win.sel = []; Backend.select(th.at) } }
            onPositionChanged: function (m) {
                if (!(pressedButtons & Qt.LeftButton)) return
                if (!win.dragSlide && Math.abs(m.x - fromX) > 12) win.dragSlide = true
                if (win.dragSlide) { var p = mapToItem(nav, m.x, m.y); win.dropAt = Math.max(0, Math.min(Backend.count, Math.round(p.x / 128))) } }
            onReleased: { if (win.dragSlide) { var to = win.dropAt > th.at ? win.dropAt - 1 : win.dropAt; if (to !== th.at && to >= 0) Backend.moveTo(th.at, to) }
                win.dragSlide = false; win.dropAt = -1 }
            onClicked: function (m) { if (m.button === Qt.RightButton) { Backend.select(th.at); var g = mapToItem(win.contentItem, m.x, m.y); win.menu = { x: g.x, y: g.y - 260, slide: true } } }
            onDoubleClicked: win.start(th.at, false) }
    }

    // ------------------------------------------------------------------ the start
    Column { visible: win.browsing; anchors.verticalCenter: parent.verticalCenter; x: win.middleX(width, parent.y + y, height) - parent.x; spacing: 10
        Item { width: 300; height: 170; anchors.horizontalCenter: parent.horizontalCenter      // three slides fanned out, the front one with a title on it
            Rectangle { x: 60; y: 0; width: 224; height: 126; radius: 10; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; rotation: 7; opacity: 0.5 }
            Rectangle { x: 44; y: 14; width: 224; height: 126; radius: 10; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; rotation: 3; opacity: 0.75 }
            Rectangle { x: 24; y: 32; width: 240; height: 135; radius: 10; border.width: 1; border.color: Theme.t.islandLine
                gradient: Gradient { GradientStop { position: 0; color: Theme.t.accent } GradientStop { position: 1; color: Qt.darker(Theme.t.accent, 1.9) } }
                Rectangle { x: 22; y: 44; width: 130; height: 12; radius: 4; color: "#FFFFFF" } Rectangle { x: 22; y: 66; width: 84; height: 6; radius: 3; color: "#B3FFFFFF" }
                Rectangle { x: 180; y: 86; width: 38; height: 38; radius: 19; color: "#33FFFFFF" } } }
        Label { text: Backend.current === "" ? "Start a presentation" : "Choose a presentation on the left"; font.pixelSize: 17; font.weight: Font.DemiBold; anchors.horizontalCenter: parent.horizontalCenter }
        Btn { text: "New Presentation"; primary: true; anchors.horizontalCenter: parent.horizontalCenter; onClicked: { Backend.create(); win.browsing = false } }
        Btn { visible: Backend.current !== ""; text: "Back to “" + Backend.title + "”"; anchors.horizontalCenter: parent.horizontalCenter; onClicked: win.browsing = false } }

    // ------------------------------------------------------------------ the slide being made
    Item { id: work; visible: !win.browsing && !win.presenting; anchors.fill: parent
        ImportNote { id: note; x: 16; y: 56; width: parent.width - 32; z: 3; file: Backend.importedFile; dropped: Backend.importedDropped; onDismissed: Backend.dismissNote() }
        Item { id: stage; x: 24; y: note.visible ? note.y + note.height + 8 : 58; width: parent.width - 48; height: parent.height - y - 112 - (win.notesOpen ? 92 : 0)
            // a click on the bare stage around the slide chooses nothing
            MouseArea { anchors.fill: parent; onPressed: { win.endEdit(); win.sel = []; win.pop = ""; win.menu = null; canvasKeys.forceActiveFocus() } }
            SlideFace { id: face; x: (stage.width - width) / 2; y: (stage.height - height) / 2; width: Math.max(100, Math.min(stage.width, stage.height * Backend.slideW / 1080))
                slide: win.cur; hints: true; hideText: win.editId; preview: win.preview }
            Rectangle { anchors.fill: face; color: "transparent"; border.width: 1; border.color: Theme.t.dark ? "#000000" : "#C3C9D0" }
            // the working layer, in slide units: choosing, moving, sizing, turning, typing
            Item { id: layer; x: face.x; y: face.y; width: Backend.slideW; height: 1080; scale: face.k; transformOrigin: Item.TopLeft
                Item { id: canvasKeys; focus: true; Keys.onPressed: function (e) { win.canvasKey(e) } }
                MouseArea { id: pointer; anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton; hoverEnabled: true; preventStealing: true
                    property var hitItem: null
                    property point from
                    property bool moving: false
                    property bool wasSole: false
                    cursorShape: moving ? Qt.SizeAllCursor : Qt.ArrowCursor
                    onPressed: function (m) {
                        win.pop = ""; win.menu = null
                        var it = win.hitAt(m.x, m.y)
                        if (win.editId && (!it || it.id !== win.editId)) win.endEdit()
                        from = Qt.point(m.x, m.y); moving = false; hitItem = it
                        if (m.button === Qt.RightButton) {
                            if (it && win.sel.indexOf(it.id) < 0) win.sel = [it.id]
                            var g = mapToItem(win.contentItem, m.x, m.y); win.menu = { x: g.x, y: g.y, slide: !it }; return }
                        if (!it) { if (!(m.modifiers & (Qt.ShiftModifier | Qt.ControlModifier))) win.sel = []; win.band = { x: m.x, y: m.y, w: 0, h: 0 }; canvasKeys.forceActiveFocus(); return }
                        wasSole = win.sel.length === 1 && win.sel[0] === it.id
                        if (m.modifiers & (Qt.ShiftModifier | Qt.ControlModifier)) {
                            var s = win.sel.slice(), i = s.indexOf(it.id); if (i >= 0) s.splice(i, 1); else s.push(it.id); win.sel = s
                        } else if (win.sel.indexOf(it.id) < 0) win.sel = [it.id]
                        canvasKeys.forceActiveFocus()
                    }
                    onPositionChanged: function (m) {
                        if (!pressed) return
                        if (win.band) { win.band = { x: Math.min(from.x, m.x), y: Math.min(from.y, m.y), w: Math.abs(m.x - from.x), h: Math.abs(m.y - from.y), fx: from.x, fy: from.y }; return }
                        if (!hitItem || (pressedButtons & Qt.RightButton)) return
                        if (!moving && Math.hypot(m.x - from.x, m.y - from.y) < 4 / win.k) return
                        moving = true
                        win.dragTo(m.x - from.x, m.y - from.y, !!(m.modifiers & Qt.ShiftModifier))
                    }
                    onReleased: function (m) {
                        if (win.band) { win.bandSelect(m.modifiers & (Qt.ShiftModifier | Qt.ControlModifier)); win.band = null; return }
                        if (moving) { win.dropMove(); moving = false; return }
                        var it = hitItem
                        if (it && m.button === Qt.LeftButton && !(m.modifiers & (Qt.ShiftModifier | Qt.ControlModifier)) && win.hasText(it) && (wasSole || (it.empty && it.role)))
                            win.startEdit(it.id, m.x, m.y)
                    }
                    onDoubleClicked: function (m) { var it = win.hitAt(m.x, m.y); if (!it) return
                        if (win.hasText(it)) win.startEdit(it.id, m.x, m.y); else if (it.kind === "picture") { win.sel = [it.id]; win.replacePicture() } } }
                // smart guides
                Repeater { model: win.guides
                    Rectangle { required property var modelData; color: "#FF3B6B"; z: 30
                        x: modelData.v ? modelData.at - width / 2 : 0; y: modelData.v ? 0 : modelData.at - height / 2
                        width: modelData.v ? 1.5 / win.k : Backend.slideW; height: modelData.v ? 1080 : 1.5 / win.k } }
                // the rubber band
                Rectangle { visible: win.band !== null; z: 31; x: win.band ? win.band.x : 0; y: win.band ? win.band.y : 0; width: win.band ? win.band.w : 0; height: win.band ? win.band.h : 0
                    color: Qt.alpha(Theme.t.accent, 0.12); border.width: 1.5 / win.k; border.color: Theme.t.accent }
                // the chosen items: outlines and handles
                Repeater { model: (win.tick, win.chosen())
                    Chosen { required property var modelData; it: modelData } }
                // typing in an item
                Item { id: editBox; z: 25; visible: win.editId !== ""
                    readonly property var it: (win.tick, win.editId ? win.item(win.editId) : null)
                    readonly property real fit: it && it.fit ? it.fit : 1
                    x: it ? it.x : 0; y: it ? it.y : 0; width: it ? it.w : 0; rotation: it ? (it.rot || 0) : 0
                    height: it ? (it.grow ? Math.max(it.h, editor.contentHeight * fit + 14.4) : it.h) : 0
                    TextEdit { id: editor; x: 14.4; width: editBox.it ? (editBox.it.w - 28.8) / editBox.fit : 10; scale: editBox.fit; transformOrigin: Item.TopLeft
                        textFormat: TextEdit.RichText; wrapMode: TextEdit.Wrap; selectByMouse: true; persistentSelection: true; selectionColor: Qt.alpha(Theme.t.accent, 0.55)
                        y: !editBox.it ? 0 : editBox.it.valign === "middle" ? (editBox.height - contentHeight * editBox.fit) / 2 : editBox.it.valign === "bottom" ? editBox.height - 7.2 - contentHeight * editBox.fit : 7.2
                        cursorDelegate: Rectangle { width: 3 / win.k; color: Theme.t.accent }
                        Component.onCompleted: Backend.attachEditor(textDocument)
                        onTextChanged: if (win.editId) commitTimer.restart()
                        onCursorPositionChanged: if (win.editId) win.refreshFmt()
                        Keys.onPressed: function (e) { win.editorKey(e) } }
                    Rectangle { anchors.fill: parent; anchors.margins: -2 / win.k; color: "transparent"; border.width: 1.5 / win.k; border.color: Theme.t.accent; opacity: 0.8 } }
            }
        }
        // speaker notes
        Rectangle { visible: win.notesOpen; x: 24; anchors { bottom: parent.bottom; bottomMargin: 110 } width: parent.width - 48; height: 82; radius: 12; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
            Label { x: 16; y: 8; text: "SPEAKER NOTES"; color: Theme.t.text_secondary; font.pixelSize: 10; font.weight: Font.DemiBold }
            Flickable { x: 16; y: 26; width: parent.width - 32; height: 50; contentHeight: notes.height; clip: true
                TextEdit { id: notes; width: parent.width; wrapMode: TextEdit.Wrap; color: Theme.t.text; font.family: Theme.t.font; font.pixelSize: 13; selectionColor: Theme.t.accent; selectByMouse: true
                    property int slot: Backend.index; property string source: win.cur.notes || ""
                    onSlotChanged: text = source; onSourceChanged: if (!activeFocus) text = source; Component.onCompleted: text = source
                    onTextChanged: if (activeFocus) Backend.setNotes(Backend.index, text)
                    Label { visible: notes.text === ""; text: "Notes only you see while presenting"; color: Theme.t.text_secondary } } } }
    }

    // ------------------------------------------------------------------ choosing, moving, sizing
    function hitAt(px, py) {
        var a = cur.items
        for (var i = a.length - 1; i >= 0; i--) {
            var it = a[i]
            if (it.locked) continue
            var g = geo(it), cx = g.x + g.w / 2, cy = g.y + g.h / 2, r = -(g.rot || 0) * Math.PI / 180
            var dx = px - cx, dy = py - cy, lx = dx * Math.cos(r) - dy * Math.sin(r), ly = dx * Math.sin(r) + dy * Math.cos(r)
            if (isLine(it)) {
                var x0 = it.flipH ? g.w / 2 : -g.w / 2, y0 = it.flipV ? g.h / 2 : -g.h / 2, x1 = -x0, y1 = -y0
                var L = Math.max(1e-6, (x1 - x0) * (x1 - x0) + (y1 - y0) * (y1 - y0)), t = Math.max(0, Math.min(1, ((lx - x0) * (x1 - x0) + (ly - y0) * (y1 - y0)) / L))
                if (Math.hypot(lx - (x0 + t * (x1 - x0)), ly - (y0 + t * (y1 - y0))) <= 10 / k) return it
                continue
            }
            if (Math.abs(lx) <= g.w / 2 && Math.abs(ly) <= g.h / 2) return it
        }
        return null
    }
    function bandSelect(add) {
        var b = band, out = add ? sel.slice() : []
        if (!b || (b.w < 3 && b.h < 3)) return
        for (var i = 0; i < cur.items.length; i++) {
            var it = cur.items[i]
            if (it.locked) continue
            if (it.x < b.x + b.w && it.x + it.w > b.x && it.y < b.y + b.h && it.y + Math.max(it.h, 1) > b.y && out.indexOf(it.id) < 0) out.push(it.id)
        }
        sel = out
    }
    // dragging the chosen items: the move snaps to the slide's middle and edges and to other items', with guides
    function dragTo(dx, dy, straight) {
        var list = chosen().filter(function (it) { return !it.locked })
        if (!list.length) return
        if (straight) { if (Math.abs(dx) > Math.abs(dy)) dy = 0; else dx = 0 }
        var b = { x: 1e9, y: 1e9, x1: -1e9, y1: -1e9 }
        for (var i = 0; i < list.length; i++) { b.x = Math.min(b.x, list[i].x); b.y = Math.min(b.y, list[i].y); b.x1 = Math.max(b.x1, list[i].x + list[i].w); b.y1 = Math.max(b.y1, list[i].y + list[i].h) }
        var xs = [0, Backend.slideW / 2, Backend.slideW], ys = [0, 540, 1080]
        for (var j = 0; j < cur.items.length; j++) { var o = cur.items[j]; if (sel.indexOf(o.id) >= 0) continue
            xs.push(o.x, o.x + o.w / 2, o.x + o.w); ys.push(o.y, o.y + o.h / 2, o.y + o.h) }
        var near = 8 / k, g = []
        var mine = [b.x + dx, (b.x + b.x1) / 2 + dx, b.x1 + dx], best = null
        for (var a = 0; a < mine.length; a++) for (var c = 0; c < xs.length; c++) { var d = xs[c] - mine[a]; if (Math.abs(d) < near && (best === null || Math.abs(d) < Math.abs(best.d))) best = { d: d, at: xs[c] } }
        if (best && !(straight && dx === 0)) { dx += best.d; g.push({ v: true, at: best.at }) }
        var mineY = [b.y + dy, (b.y + b.y1) / 2 + dy, b.y1 + dy], bestY = null
        for (var e = 0; e < mineY.length; e++) for (var f = 0; f < ys.length; f++) { var dd = ys[f] - mineY[e]; if (Math.abs(dd) < near && (bestY === null || Math.abs(dd) < Math.abs(bestY.d))) bestY = { d: dd, at: ys[f] } }
        if (bestY && !(straight && dy === 0)) { dy += bestY.d; g.push({ v: false, at: bestY.at }) }
        var p = {}
        for (var q = 0; q < list.length; q++) p[list[q].id] = { x: list[q].x + dx, y: list[q].y + dy, w: list[q].w, h: list[q].h }
        preview = p; guides = g; moveBy = Qt.point(dx, dy)
    }
    property point moveBy
    function dropMove() { var ids = Object.keys(preview); if (ids.length) Backend.moveItems(ids, moveBy.x, moveBy.y); preview = ({}); guides = [] }

    // outline and handles on a chosen item
    component Chosen: Item {
        id: ch
        property var it: ({})
        readonly property var g: win.geo(it)
        readonly property real hs: 11 / win.k                // a handle's size, the same on screen at any zoom
        readonly property bool line: win.isLine(it)
        readonly property bool solo: win.sel.length === 1 && win.editId === ""
        x: g.x; y: g.y; width: g.w; height: Math.max(g.h, 0.01); rotation: g.rot; z: 20
        Rectangle { visible: !ch.line; anchors.fill: parent; anchors.margins: -1.5 / win.k; color: "transparent"; border.width: 2 / win.k; border.color: Theme.t.accent; opacity: win.editId === ch.it.id ? 0 : 1 }
        // eight handles to size it (pictures keep their shape unless Shift is held)
        Repeater { model: ch.solo && !ch.line && !ch.it.locked ? [[0, 0], [0.5, 0], [1, 0], [1, 0.5], [1, 1], [0.5, 1], [0, 1], [0, 0.5]] : []
            Rectangle { required property var modelData; width: ch.hs; height: ch.hs; radius: ch.hs / 2; color: "#FFFFFF"; border.width: 1.5 / win.k; border.color: Theme.t.accent
                x: modelData[0] * ch.width - width / 2; y: modelData[1] * ch.height - height / 2
                MouseArea { anchors.fill: parent; anchors.margins: -4 / win.k; preventStealing: true
                    cursorShape: (parent.modelData[0] === 0.5) ? Qt.SizeVerCursor : (parent.modelData[1] === 0.5) ? Qt.SizeHorCursor
                                 : ((parent.modelData[0] === parent.modelData[1]) ? Qt.SizeFDiagCursor : Qt.SizeBDiagCursor)
                    property var start
                    onPressed: function (m) { var p = mapToItem(layer, m.x, m.y); start = { px: p.x, py: p.y, x: ch.it.x, y: ch.it.y, w: ch.it.w, h: ch.it.h } }
                    onPositionChanged: function (m) { var p = mapToItem(layer, m.x, m.y); win.resizeTo(ch.it, start, parent.modelData, p.x - start.px, p.y - start.py, !!(m.modifiers & Qt.ShiftModifier)) }
                    onReleased: { var v = win.preview[ch.it.id]; if (v) Backend.place(ch.it.id, v.x, v.y, v.w, v.h); win.preview = ({}) } } } }
        // the handle to turn it
        Rectangle { visible: ch.solo && !ch.line && !ch.it.locked; width: 1.5 / win.k; height: 26 / win.k; x: ch.width / 2; y: -height; color: Theme.t.accent }
        Rectangle { visible: ch.solo && !ch.line && !ch.it.locked; width: ch.hs * 1.2; height: width; radius: width / 2; x: ch.width / 2 - width / 2; y: -26 / win.k - height
            color: Theme.t.accent; border.width: 1.5 / win.k; border.color: "#FFFFFF"
            MouseArea { anchors.fill: parent; anchors.margins: -4 / win.k; preventStealing: true; cursorShape: Qt.CrossCursor
                onPositionChanged: function (m) { var p = mapToItem(layer, m.x, m.y), cx = ch.it.x + ch.it.w / 2, cy = ch.it.y + ch.it.h / 2
                    var deg = Math.atan2(p.y - cy, p.x - cx) * 180 / Math.PI + 90
                    deg = ((m.modifiers & Qt.ShiftModifier) ? Math.round(deg / 15) * 15 : Math.round(deg)); deg = ((deg % 360) + 360) % 360
                    if (!(m.modifiers & Qt.ShiftModifier)) for (var s = 0; s <= 360; s += 90) if (Math.abs(deg - s) < 4) deg = s % 360
                    var p2 = {}; p2[ch.it.id] = { x: ch.it.x, y: ch.it.y, w: ch.it.w, h: ch.it.h, rot: deg }; win.preview = p2 }
                onReleased: { var v = win.preview[ch.it.id]; if (v && v.rot !== undefined) Backend.setItems([ch.it.id], "rot", v.rot); win.preview = ({}) } } }
        // a line's two ends
        Repeater { model: ch.solo && ch.line ? [0, 1] : []
            Rectangle { required property int modelData
                readonly property bool startEnd: modelData === 0
                width: ch.hs; height: ch.hs; radius: ch.hs / 2; color: "#FFFFFF"; border.width: 1.5 / win.k; border.color: Theme.t.accent
                x: ((startEnd !== !!ch.it.flipH) ? 0 : ch.width) - width / 2; y: ((startEnd !== !!ch.it.flipV) ? 0 : ch.height) - height / 2
                MouseArea { anchors.fill: parent; anchors.margins: -4 / win.k; preventStealing: true; cursorShape: Qt.CrossCursor
                    onPositionChanged: function (m) { var p = mapToItem(layer, m.x, m.y)
                        var x0 = ch.it.flipH ? ch.it.x + ch.it.w : ch.it.x, y0 = ch.it.flipV ? ch.it.y + ch.it.h : ch.it.y
                        var x1 = ch.it.flipH ? ch.it.x : ch.it.x + ch.it.w, y1 = ch.it.flipV ? ch.it.y : ch.it.y + ch.it.h
                        if (parent.startEnd) { x0 = p.x; y0 = p.y } else { x1 = p.x; y1 = p.y }
                        if (m.modifiers & Qt.ShiftModifier) { if (Math.abs(x1 - x0) > Math.abs(y1 - y0)) { if (parent.startEnd) y0 = y1; else y1 = y0 } else { if (parent.startEnd) x0 = x1; else x1 = x0 } }
                        lineEnds = [x0, y0, x1, y1]
                        var p2 = {}; p2[ch.it.id] = { x: Math.min(x0, x1), y: Math.min(y0, y1), w: Math.max(0.01, Math.abs(x1 - x0)), h: Math.max(0.01, Math.abs(y1 - y0)) }; win.preview = p2 }
                    property var lineEnds: null
                    onReleased: { if (lineEnds) Backend.placeLine(ch.it.id, lineEnds[0], lineEnds[1], lineEnds[2], lineEnds[3]); lineEnds = null; win.preview = ({}) } } } }
        // its place in the builds
        Rectangle { visible: !!ch.it.anim; x: -width - 6 / win.k; y: 0; width: 24 / win.k; height: width; radius: width / 2; color: "#FF8A4C"
            Label { anchors.centerIn: parent; text: ch.it.anim ? Math.round(ch.it.anim.order) : ""; color: "#FFFFFF"; font.pixelSize: Math.max(8, 12 / win.k); font.weight: Font.Bold } }
    }
    function resizeTo(it, s, h, dx, dy, shift) {
        var r = (it.rot || 0) * Math.PI / 180, lx = dx * Math.cos(r) + dy * Math.sin(r), ly = -dx * Math.sin(r) + dy * Math.cos(r)
        var w = s.w, hh = s.h, x0 = 0, y0 = 0
        if (h[0] === 0) { w = s.w - lx; x0 = lx } else if (h[0] === 1) w = s.w + lx
        if (h[1] === 0) { hh = s.h - ly; y0 = ly } else if (h[1] === 1) hh = s.h + ly
        var keep = (it.kind === "picture") !== shift
        if (keep && h[0] !== 0.5 && h[1] !== 0.5) {           // from a corner: the same shape
            var ratio = s.w / Math.max(1, s.h)
            if (Math.abs(w / s.w) > Math.abs(hh / s.h)) { var nh = w / ratio; if (h[1] === 0) y0 += hh - nh; hh = nh } else { var nw = hh * ratio; if (h[0] === 0) x0 += w - nw; w = nw }
        }
        w = Math.max(16, w); hh = Math.max(it.kind === "text" && it.grow ? 16 : 16, hh)
        if (it.kind === "text" && it.grow && h[1] === 0.5) hh = s.h
        // where the box's corner goes, with the turn: keep the opposite side where it was
        var cx = s.x + s.w / 2, cy = s.y + s.h / 2
        var ox = x0 + w / 2 - s.w / 2, oy = y0 + hh / 2 - s.h / 2         // the new centre, in the item's own axes
        var ncx = cx + ox * Math.cos(r) - oy * Math.sin(r), ncy = cy + ox * Math.sin(r) + oy * Math.cos(r)
        var p = {}; p[it.id] = { x: ncx - w / 2, y: ncy - hh / 2, w: w, h: hh }; preview = p
    }

    // ------------------------------------------------------------------ keys
    function canvasKey(e) {
        var ctrl = e.modifiers & Qt.ControlModifier, shift = e.modifiers & Qt.ShiftModifier
        var arrows = { [Qt.Key_Left]: [-1, 0], [Qt.Key_Right]: [1, 0], [Qt.Key_Up]: [0, -1], [Qt.Key_Down]: [0, 1] }
        if (arrows[e.key] && sel.length) { var d = arrows[e.key], step = shift ? 20 : 2; Backend.moveItems(sel, d[0] * step, d[1] * step); e.accepted = true; return }
        if (arrows[e.key] || e.key === Qt.Key_PageDown || e.key === Qt.Key_PageUp) {      // nothing chosen: the arrows go through the slides
            var dir = (e.key === Qt.Key_Right || e.key === Qt.Key_Down || e.key === Qt.Key_PageDown) ? 1 : -1
            Backend.select(Math.max(0, Math.min(Backend.count - 1, Backend.index + dir))); e.accepted = true; return }
        if ((e.key === Qt.Key_Delete || e.key === Qt.Key_Backspace) && sel.length) { deleteItems(); e.accepted = true; return }
        if (e.key === Qt.Key_Escape) { sel = []; pop = ""; menu = null; e.accepted = true; return }
        if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter || e.key === Qt.Key_F2) && sel.length === 1) { startEdit(sel[0]); e.accepted = true; return }
        if (e.key === Qt.Key_Tab && cur.items.length) {        // Tab goes through the items
            var i = sel.length ? cur.items.findIndex(function (it) { return it.id === sel[0] }) : -1
            var n = (i + (shift ? -1 : 1) + cur.items.length) % cur.items.length; sel = [cur.items[n].id]; e.accepted = true; return }
        if (!ctrl && e.text && e.text.length === 1 && e.text >= " " && sel.length === 1 && hasText(item(sel[0]))) {      // typing on a chosen box replaces its text
            startEdit(sel[0]); editor.remove(0, editor.length); editor.insert(0, e.text); editor.cursorPosition = e.text.length; e.accepted = true; return }
    }
    function editorKey(e) {
        if (e.key === Qt.Key_Escape) { var id = editId; endEdit(); sel = [id]; e.accepted = true; return }
        if (e.key === Qt.Key_Tab || e.key === Qt.Key_Backtab) {
            var atStart = editor.cursorPosition === 0 || editor.getText(editor.cursorPosition - 1, editor.cursorPosition) === "\n"
            if (fmt.list || atStart || editor.selectionStart !== editor.selectionEnd || e.key === Qt.Key_Backtab) { apply(e.key === Qt.Key_Backtab || (e.modifiers & Qt.ShiftModifier) ? "outdent" : "indent"); e.accepted = true; return }
        }
    }

    // ------------------------------------------------------------------ the little menus
    Rectangle { id: popBox; visible: win.pop !== "" && win.popFrom !== null; z: 60; radius: 14; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        readonly property point at: win.popFrom ? win.popFrom.mapToItem(win.contentItem, 0, 0) : Qt.point(0, 0)
        readonly property bool below: at.y < win.height / 2
        width: popGrid.visible ? Math.max(popGrid.width, win.pop === "bg" ? 230 : 0) + 16 : popSlides.visible ? popSlides.width + 16 : win.pop === "transition" || win.pop === "build" ? 360 : win.pop === "insertShape" || win.pop === "shape" ? 240 : 250
        height: Math.min(win.height - 80, popCol.height + 12)
        x: Math.max(8, Math.min(win.width - width - 8, at.x + (win.popFrom ? win.popFrom.width / 2 : 0) - width / 2))
        y: below ? at.y + (win.popFrom ? win.popFrom.height : 0) + 12 : at.y - height - 12
        MouseArea { anchors.fill: parent }
        Flickable { anchors.fill: parent; anchors.margins: 6; contentHeight: popCol.height; clip: true; boundsBehavior: Flickable.StopAtBounds
            Column { id: popCol; width: parent.width; spacing: 2
                // lists
                Repeater { model: win.popList()
                    Pressable { required property var modelData; width: popCol.width; height: modelData[0] === "-" ? 9 : 32; radius: 9; enabled: modelData[0] !== "-"
                        color: hovered && modelData[0] !== "-" ? Theme.t.hover : (modelData[3] ? Qt.alpha(Theme.t.accent, 0.16) : "transparent")
                        onClicked: win.popPick(modelData[0])
                        Rectangle { visible: parent.modelData[0] === "-"; anchors.centerIn: parent; width: parent.width - 16; height: 1; color: Theme.t.islandLine }
                        Label { visible: parent.modelData[0] !== "-"; x: 10; anchors.verticalCenter: parent.verticalCenter; text: parent.modelData[1]; font.pixelSize: 13
                            font.family: win.pop === "font" ? parent.modelData[0] : Theme.t.font }
                        Label { visible: parent.modelData[0] !== "-"; anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: parent.modelData[2] || ""; font.pixelSize: 11; secondary: true } } }
                // colours
                Grid { id: popGrid; visible: win.pop === "ink" || win.pop === "fill" || win.pop === "line" || win.pop === "bg"; columns: 6; spacing: 6; padding: 4
                    Repeater { model: popGrid.visible ? win.swatches() : []
                        Rectangle { required property var modelData; width: 26; height: 26; radius: 13; border.width: 1; border.color: Theme.t.islandLine
                            color: modelData[1] === "none" || modelData[1] === "theme" ? "transparent" : modelData[1]
                            Label { visible: parent.modelData[1] === "none" || parent.modelData[1] === "theme"; anchors.centerIn: parent; text: parent.modelData[1] === "none" ? "×" : "T"; font.pixelSize: 13 }
                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: win.popPick(parent.modelData[0]) } } } }
                // shapes
                Grid { visible: win.pop === "insertShape" || win.pop === "shape"; columns: 6; spacing: 4; padding: 2
                    Repeater { model: (win.pop === "insertShape" || win.pop === "shape") ? Backend.shapes.filter(function (s) { return win.pop === "insertShape" || (s.key !== "line" && s.key !== "arrowline") }) : []
                        Pressable { id: shp; required property var modelData; width: 36; height: 32; radius: 8; color: hovered ? Theme.t.hover : "transparent"; onClicked: win.popPick(modelData.key)
                            Shape { x: 4; y: 6; width: 28; height: 20; preferredRendererType: Shape.CurveRenderer
                                ShapePath { fillColor: shp.modelData.key === "line" || shp.modelData.key === "arrowline" ? "transparent" : Qt.alpha(Theme.t.accent, 0.35)
                                    strokeColor: Theme.t.accent; strokeWidth: 1.5; PathSvg { path: shp.modelData.path } } } } } }
                // slides: layouts to pick
                Grid { id: popSlides; visible: win.pop === "layout" || win.pop === "addSlide"; columns: 3; spacing: 8; padding: 4
                    Repeater { model: popSlides.visible ? Backend.samples : []
                        Column { id: lay; required property var modelData; spacing: 4
                            Rectangle { width: 136; height: 136 * 1080 / Backend.slideW + 4; radius: 6; color: "transparent"; border.width: hit.containsMouse || (win.pop === "layout" && win.cur.layout === lay.modelData.key) ? 2 : 1
                                border.color: hit.containsMouse || (win.pop === "layout" && win.cur.layout === lay.modelData.key) ? Theme.t.accent : Theme.t.islandLine
                                SlideFace { x: 2; y: 2; width: 132; slide: lay.modelData; hints: true }
                                MouseArea { id: hit; anchors.fill: parent; hoverEnabled: true; onClicked: win.popPick(lay.modelData.key) } }
                            Label { text: modelData.name; font.pixelSize: 11; anchors.horizontalCenter: parent.horizontalCenter } } } }
                // themes
                Column { visible: win.pop === "theme"; width: popCol.width; spacing: 6
                    Grid { columns: 2; spacing: 8
                        Repeater { model: win.pop === "theme" ? Backend.themes : []
                            Column { id: thm; required property var modelData; spacing: 3
                                Rectangle { width: 112; height: 63; radius: 7; border.width: Backend.theme === modelData.key ? 2 : 1; border.color: Backend.theme === modelData.key ? Theme.t.accent : Theme.t.islandLine
                                    color: modelData.bg.color || modelData.bg.from || "#FFFFFF"
                                    gradient: thm.modelData.bg.from ? grad : null
                                    Gradient { id: grad; orientation: (thm.modelData.bg.angle || 0) % 180 === 0 ? Gradient.Horizontal : Gradient.Vertical
                                        GradientStop { position: 0; color: thm.modelData.bg.from || "#FFFFFF" } GradientStop { position: 1; color: thm.modelData.bg.to || "#FFFFFF" } }
                                    Text { x: 10; y: 14; text: "Aa"; color: thm.modelData.title; font.family: thm.modelData.head; font.pixelSize: 20; font.bold: true }
                                    Row { x: 10; y: 44; spacing: 3; Repeater { model: thm.modelData.accents.slice(0, 4); Rectangle { required property string modelData; width: 12; height: 8; radius: 2; color: modelData } } }
                                    MouseArea { anchors.fill: parent; onClicked: { Backend.setTheme(thm.modelData.key); win.pop = "" } } }
                                Label { text: modelData.name; font.pixelSize: 11 } } } }
                    Label { visible: Backend.theme === ""; text: "This presentation keeps the design it came with. A theme replaces it."; wrapMode: Text.WordWrap; width: parent.width; font.pixelSize: 11; secondary: true }
                    Row { spacing: 6; height: 30; Label { text: "Slide size"; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter; rightPadding: 6 }
                        Seg { text: "16:9"; on: Backend.size === "16:9"; onClicked: Backend.setSize("16:9") } Seg { text: "4:3"; on: Backend.size === "4:3"; onClicked: Backend.setSize("4:3") } } }
                // transitions
                Column { visible: win.pop === "transition"; width: popCol.width; spacing: 6
                    Row { spacing: 3
                        Repeater { model: [["none", "None"], ["fade", "Fade"], ["push", "Push"], ["wipe", "Wipe"], ["zoom", "Zoom"], ["cover", "Cover"]]
                            Seg { required property var modelData; text: modelData[1]; on: win.cur.transition && win.cur.transition.kind === modelData[0]
                                onClicked: Backend.setTransition(modelData[0], win.cur.transition ? win.cur.transition.ms : 500, win.trAll) } } }
                    Row { spacing: 4; height: 30; Label { text: "Time"; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter; rightPadding: 4 }
                        Repeater { model: [[300, "0.3 s"], [500, "0.5 s"], [800, "0.8 s"], [1200, "1.2 s"]]
                            Seg { required property var modelData; text: modelData[1]; on: win.cur.transition && win.cur.transition.ms === modelData[0]
                                onClicked: Backend.setTransition(win.cur.transition ? win.cur.transition.kind : "fade", modelData[0], win.trAll) } } }
                    Row { Seg { text: "Every slide"; on: win.trAll; onClicked: { win.trAll = !win.trAll; if (win.trAll && win.cur.transition) Backend.setTransition(win.cur.transition.kind, win.cur.transition.ms, true) } } } }
                // builds
                Column { id: buildCol; visible: win.pop === "build"; width: popCol.width; spacing: 6
                    readonly property var first: win.chosen()[0] || ({})
                    Row { spacing: 3
                        Repeater { model: [["", "None"], ["appear", "Appear"], ["fade", "Fade"], ["rise", "Rise"], ["zoom", "Zoom"]]
                            Seg { required property var modelData; text: modelData[1]; on: (buildCol.first.anim ? buildCol.first.anim.kind : "") === modelData[0]
                                onClicked: { var f = buildCol.first; Backend.setItems(win.sel, "anim", modelData[0] ? { kind: modelData[0], byPara: f.anim ? !!f.anim.byPara : f.role === "body" || f.role === "body2", order: f.anim ? f.anim.order : undefined } : null) } } } }
                    Row { visible: win.hasText(buildCol.first) && !!buildCol.first.anim
                        Seg { text: "One paragraph at a time"; on: !!(buildCol.first.anim && buildCol.first.anim.byPara)
                            onClicked: { var a = buildCol.first.anim; Backend.setItems(win.sel, "anim", { kind: a.kind, byPara: !a.byPara, order: a.order, ms: a.ms }) } } }
                    Label { text: "Builds come in one click at a time while presenting, in the order of the numbers beside them."; wrapMode: Text.WordWrap; width: parent.width; font.pixelSize: 11; secondary: true } }
                // backgrounds: and for every slide
                Row { visible: win.pop === "bg"; spacing: 4
                    Seg { text: "Every slide"; on: win.bgAll; onClicked: win.bgAll = !win.bgAll }
                    Seg { text: "A picture…"; onClicked: { win.pop = ""; var all = win.bgAll
                            Picker.open("A picture for the background", [["Pictures", "*.png *.jpg *.jpeg *.webp"]], function (paths) { if (paths.length) Backend.setBackground((all ? "all:" : "") + paths[0]) }) } } }
            } } }
    function popList() {
        var p = pop, f = fmt
        if (p === "font") return Backend.fonts().map(function (n) { return [n, n, "", n === f.font] })
        if (p === "size") return [12, 14, 16, 18, 20, 24, 28, 32, 36, 40, 44, 48, 54, 60, 72, 88, 96].map(function (s) { return ["size:" + s, String(s), "", s === f.size] })
        if (p === "align") return [["left", "Left", "Ctrl+L"], ["center", "Centre", "Ctrl+E"], ["right", "Right", "Ctrl+R"], ["justify", "Justify", "Ctrl+J"]].map(function (a) { return a.concat([f.align === a[0]]) })
        if (p === "arrange") return [["front", "Bring to Front", ""], ["forward", "Bring Forward", ""], ["backward", "Send Backward", ""], ["back", "Send to Back", ""], ["-", ""],
                                     ["a:left", "Align Left", sel.length > 1 ? "" : "to the slide"], ["a:center", "Align Centres", ""], ["a:right", "Align Right", ""],
                                     ["a:top", "Align Tops", ""], ["a:middle", "Align Middles", ""], ["a:bottom", "Align Bottoms", ""]].concat(
                                     sel.length > 2 ? [["-", ""], ["a:hspread", "Spread Across", ""], ["a:vspread", "Spread Down", ""]] : []).concat(
                                     hasText(chosen()[0]) ? [["-", ""], ["v:top", "Text at the Top", ""], ["v:middle", "Text in the Middle", ""], ["v:bottom", "Text at the Bottom", ""]] : [])
        if (p === "line") return [["w:0", "No outline", ""], ["w:2", "Thin", "1 pt"], ["w:4", "Medium", "2 pt"], ["w:8", "Thick", "4 pt"], ["w:14", "Heavy", "7 pt"]]
        if (p === "add") return [["text", "Text Box", ""], ["shape", "Shape…", ""], ["picture", "Picture…", ""]]
        if (p === "present") return [["start", "From the Start", "F5"], ["here", "From This Slide", "Shift+F5"], ["presenter", "Presenter View", "Alt+F5"]]
        if (p === "bg") return [["theme", "The theme's own", ""]]
        return []
    }
    function swatches() {
        var acc = Backend.look.accents || []
        var themed = acc.map(function (c, i) { return ["accent" + (i + 1), c] })
        if (pop === "bg") return [["", "theme"]].concat(acc.map(function (c) { return [c, c] })).concat([["#FFFFFF", "#FFFFFF"], ["#F1F3F5", "#F1F3F5"], ["#101317", "#101317"], ["#0F2624", "#0F2624"],
                                ["#1C2B4A", "#1C2B4A"], ["#FFF4E6", "#FFF4E6"]])
        var base = [["#FFFFFF", "#FFFFFF"], ["#E9ECEF", "#E9ECEF"], ["#868E96", "#868E96"], ["#343A40", "#343A40"], ["#000000", "#000000"], ["#D93A3F", "#D93A3F"]]
        if (pop === "ink") return [["#" + "theme", "theme"]].concat(acc.map(function (c) { return [c, c] })).concat(base).concat([["#2B8A3E", "#2B8A3E"], ["#1C7ED6", "#1C7ED6"], ["#F08C00", "#F08C00"]])
        return [["", "none"]].concat(themed).concat(base).concat([["#2B8A3E", "#2B8A3E"], ["#1C7ED6", "#1C7ED6"], ["#F08C00", "#F08C00"]])
    }
    function popPick(key) {
        var kind = pop
        if (kind === "font") apply("font:" + key)
        else if (kind === "size" || kind === "align") apply(key)
        else if (kind === "ink") apply(key === "#theme" ? "clear" : key)
        else if (kind === "fill") Backend.setItems(sel, "fill", key)
        else if (kind === "line") { if (key.indexOf("w:") === 0) { var w = parseInt(key.slice(2)); Backend.setItems(sel, "lineW", w); if (w && !chosen()[0].line) Backend.setItems(sel, "line", "text") } else { Backend.setItems(sel, "line", key); if (key && !chosen()[0].lineW) Backend.setItems(sel, "lineW", 2) } return }
        else if (kind === "shape") Backend.setItems(sel, "shape", key)
        else if (kind === "insertShape") { var id = Backend.addItem("shape", key); if (id) sel = [id] }
        else if (kind === "layout") { endEdit(); Backend.setLayout(key) }
        else if (kind === "addSlide") { endEdit(); Backend.add(key); sel = [] }
        else if (kind === "arrange") { if (key.indexOf("a:") === 0) Backend.align(sel, key.slice(2)); else if (key.indexOf("v:") === 0) Backend.setItems(sel, "valign", key.slice(2)); else arrange(key) }
        else if (kind === "add") { pop = ""; if (key === "text") insertText(); else if (key === "picture") insertPicture(); else Qt.callLater(function () { win.openPop("insertShape", addBtn2) }); return }
        else if (kind === "present") { pop = ""; if (key === "start") present(); else if (key === "here") presentHere(); else presenterView(); return }
        else if (kind === "bg") Backend.setBackground((bgAll ? "all:" : "") + key)
        pop = ""
    }

    // ------------------------------------------------------------------ the right-click menu
    Rectangle { visible: win.menu !== null; z: 61; x: Math.min(win.width - width - 8, win.menu ? win.menu.x : 0); y: Math.max(8, Math.min(win.height - height - 8, win.menu ? win.menu.y : 0))
        width: 230; height: menuCol.height + 12; radius: 14; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        Column { id: menuCol; x: 6; y: 6; width: parent.width - 12; spacing: 1
            readonly property bool forSlide: !!(win.menu && win.menu.slide)
            MenuItem { visible: !parent.forSlide; label: "Cut"; keys: "Ctrl+X"; onClicked: { win.menu = null; win.menuCut() } }
            MenuItem { visible: !parent.forSlide; label: "Copy"; keys: "Ctrl+C"; onClicked: { win.menu = null; win.menuCopy() } }
            MenuItem { label: "Paste"; keys: "Ctrl+V"; onClicked: { win.menu = null; win.menuPaste() } }
            MenuItem { visible: !parent.forSlide; label: "Duplicate"; keys: "Ctrl+D"; onClicked: { win.menu = null; win.duplicateItems() } }
            MenuItem { visible: !parent.forSlide; label: "Delete"; keys: "Delete"; onClicked: { win.menu = null; win.deleteItems() } }
            MenuItem { visible: !parent.forSlide && win.sel.length === 1 && win.hasText(win.item(win.sel[0] || "")); label: "Edit the Text"; keys: "Enter"; onClicked: { win.menu = null; win.startEdit(win.sel[0]) } }
            Rectangle { visible: !parent.forSlide; width: parent.width; height: 1; color: Theme.t.islandLine }
            MenuItem { visible: !parent.forSlide; label: "Bring to Front"; onClicked: { win.menu = null; win.arrange("front") } }
            MenuItem { visible: !parent.forSlide; label: "Send to Back"; onClicked: { win.menu = null; win.arrange("back") } }
            MenuItem { visible: parent.forSlide; label: "New Slide"; keys: "Ctrl+M"; onClicked: { win.menu = null; win.newSlide() } }
            MenuItem { visible: parent.forSlide; label: "Duplicate Slide"; onClicked: { win.menu = null; win.duplicateSlide() } }
            MenuItem { visible: parent.forSlide; label: win.cur.hidden ? "Show in the Show" : "Hide in the Show"; onClicked: { win.menu = null; win.toggleHidden() } }
            MenuItem { visible: parent.forSlide && Backend.count > 1; label: "Delete Slide"; onClicked: { win.menu = null; win.deleteSlide() } }
            MenuItem { visible: parent.forSlide; label: "Present From Here"; onClicked: { win.menu = null; win.presentHere() } } } }
    component MenuItem: Pressable { property string label: ""; property string keys: ""; width: parent ? parent.width : 200; height: visible ? 30 : 0; radius: 9; color: hovered ? Theme.t.hover : "transparent"
        Label { x: 10; anchors.verticalCenter: parent.verticalCenter; text: parent.label; font.pixelSize: 13 }
        Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: parent.keys; font.pixelSize: 11; secondary: true } }
    MouseArea { anchors.fill: parent; z: 59; visible: win.menu !== null || win.pop !== ""; acceptedButtons: Qt.AllButtons; onPressed: { win.menu = null; win.pop = "" } }

    // ------------------------------------------------------------------ presenting: the slides, full screen
    component Stage: Rectangle {
        id: st
        color: win.blank === "white" ? "#FFFFFF" : "#000000"
        property int index: win.showIndex
        property int last: -1
        readonly property real fw: Math.min(width, height * Backend.slideW / 1080)
        readonly property var view: Backend.slides[Math.min(st.index, Backend.count - 1)] || ({ items: [] })
        Item { id: box; anchors.centerIn: parent; width: st.fw; height: st.fw * 1080 / Backend.slideW; clip: true; visible: win.blank === "" && !win.showEnded
            SlideFace { id: under; width: box.width; live: true; step: 9999; visible: false }
            Item { id: front; width: box.width; height: box.height; clip: true
                SlideFace { width: box.width; live: true; step: win.showStep; forward: win.forward; slide: st.view } } }
        Label { visible: win.showEnded && win.blank === ""; anchors.centerIn: parent; text: "The end of the show. Click to leave."; color: "#8A9099"; font.pixelSize: 18 }
        onIndexChanged: go()
        Component.onCompleted: last = index
        function go() {
            var t = st.view.transition || { kind: "none" }
            if (last >= 0 && last !== index && win.forward && t.kind && t.kind !== "none") {
                under.slide = Backend.slides[last]; under.x = 0; under.visible = true
                front.x = 0; front.opacity = 1; front.scale = 1; front.width = box.width
                var ms = t.ms || 500
                if (t.kind === "fade") { fadeA.duration = ms; fadeA.start() }
                else if (t.kind === "push") { pushA.duration = ms; pushB.duration = ms; pushAll.start() }
                else if (t.kind === "cover") { pushA.duration = ms; pushA.start() }
                else if (t.kind === "wipe") { wipeA.duration = ms; wipeA.start() }
                else if (t.kind === "zoom") { zoomA.duration = ms; zoomB.duration = ms; zoomAll.start() }
            }
            last = index
        }
        NumberAnimation { id: fadeA; target: front; property: "opacity"; from: 0; to: 1; easing.type: Easing.InOutQuad; onFinished: under.visible = false }
        NumberAnimation { id: pushA; target: front; property: "x"; from: box.width; to: 0; easing.type: Easing.InOutCubic; onFinished: under.visible = false }
        ParallelAnimation { id: pushAll; NumberAnimation { id: pushB; target: under; property: "x"; from: 0; to: -box.width; easing.type: Easing.InOutCubic }
            NumberAnimation { target: front; property: "x"; from: box.width; to: 0; duration: pushB.duration; easing.type: Easing.InOutCubic }
            onFinished: { under.visible = false; under.x = 0 } }
        NumberAnimation { id: wipeA; target: front; property: "width"; from: 0; to: box.width; easing.type: Easing.InOutQuad; onFinished: under.visible = false }
        ParallelAnimation { id: zoomAll; NumberAnimation { id: zoomA; target: front; property: "scale"; from: 0.82; to: 1; easing.type: Easing.OutCubic }
            NumberAnimation { id: zoomB; target: front; property: "opacity"; from: 0; to: 1; easing.type: Easing.OutCubic }
            onFinished: under.visible = false }
    }
    // the show on this screen (one screen, no presenter view)
    Stage { visible: win.presenting && !win.presenterUi; anchors.fill: parent; z: 100
        Item { id: stageKeys; focus: win.presenting && !win.presenterUi; Keys.onPressed: function (e) { win.showKey(e) } }
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton; hoverEnabled: true; cursorShape: idle.running ? Qt.ArrowCursor : Qt.BlankCursor
            onPositionChanged: idle.restart()
            onClicked: function (m) { if (m.button === Qt.RightButton) win.prev(); else win.next() }
            Timer { id: idle; interval: 2000 } }
        Label { anchors { bottom: parent.bottom; right: parent.right; margins: 14 } text: (win.showIndex + 1) + " / " + Backend.count; color: "#55FFFFFF"; font.pixelSize: 12; visible: idle.running } }
    // the show on another screen
    Window { id: audience; visible: false; color: "#000000"; title: (Backend.title || "Slides") + " — show"
        onClosing: if (win.presenting) win.stop()
        Stage { anchors.fill: parent
            Item { focus: true; Keys.onPressed: function (e) { win.showKey(e) } }
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton; cursorShape: Qt.BlankCursor
                onClicked: function (m) { if (m.button === Qt.RightButton) win.prev(); else win.next() } } } }
    // the presenter view: this slide as the audience sees it, the next, the notes, the time
    Rectangle { visible: win.presenting && win.presenterUi; anchors.fill: parent; z: 100; color: "#0E1013"
        Item { id: presenterKeys; focus: win.presenting && win.presenterUi; Keys.onPressed: function (e) { win.showKey(e) } }
        readonly property real gap: 24
        Stage { id: nowStage; x: parent.gap; y: parent.gap + 34; width: parent.width * 0.6 - parent.gap * 1.5; height: width * 1080 / Backend.slideW; radius: 10; clip: true
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton; onClicked: function (m) { if (m.button === Qt.RightButton) win.prev(); else win.next() } } }
        Label { x: parent.gap; y: parent.gap; text: "Slide " + (win.showIndex + 1) + " of " + Backend.count + (Backend.slides[win.showIndex] && Backend.slides[win.showIndex].steps ? "  ·  build " + win.showStep + " of " + Backend.slides[win.showIndex].steps : "")
            color: "#C9CED6"; font.pixelSize: 14; font.weight: Font.DemiBold }
        Column { x: nowStage.x + nowStage.width + parent.gap; y: parent.gap; width: parent.width - x - parent.gap; spacing: 10
            Label { text: "NEXT"; color: "#8A9099"; font.pixelSize: 11; font.weight: Font.DemiBold }
            Item { width: parent.width * 0.8; height: width * 1080 / Backend.slideW
                readonly property int nextIndex: win.visibleFrom(win.showIndex + 1, 1)
                readonly property bool more: (win.showStep < (Backend.slides[win.showIndex] ? Backend.slides[win.showIndex].steps : 0))
                SlideFace { visible: parent.more || parent.nextIndex < Backend.count; width: parent.width; live: true
                    slide: parent.more ? Backend.slides[win.showIndex] : (Backend.slides[parent.nextIndex] || ({ items: [] })); step: parent.more ? win.showStep + 1 : 0 }
                Rectangle { anchors.fill: parent; color: "transparent"; border.width: 1; border.color: "#2A2F36"; radius: 4 }
                Label { visible: !parent.more && parent.nextIndex >= Backend.count; anchors.centerIn: parent; text: "The end"; color: "#8A9099" } }
            Row { spacing: 8
                Label { text: "NOTES"; color: "#8A9099"; font.pixelSize: 11; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
                Seg { text: "A−"; onClicked: win.notesSize = Math.max(12, win.notesSize - 2) } Seg { text: "A+"; onClicked: win.notesSize = Math.min(44, win.notesSize + 2) } } }
        Flickable { x: nowStage.x + nowStage.width + parent.gap; y: nowStage.y + nowStage.height * 0.62; width: parent.width - x - parent.gap; height: parent.height - y - 90; contentHeight: notesText.height; clip: true
            Text { id: notesText; width: parent.width; wrapMode: Text.Wrap; color: "#ECEFF3"; font.family: Theme.t.font; font.pixelSize: win.notesSize; lineHeight: 1.25
                text: (Backend.slides[win.showIndex] ? Backend.slides[win.showIndex].notes : "") || "No notes for this slide." } }
        // the strip of slides, to jump
        ListView { x: parent.gap; y: nowStage.y + nowStage.height + 16; width: nowStage.width; height: 78; orientation: ListView.Horizontal; spacing: 8; clip: true; model: Backend.slides
            currentIndex: win.showIndex; highlightFollowsCurrentItem: true; highlightMoveDuration: 200
            delegate: Item { required property var modelData; required property int index; width: 112 * 1.15; height: 72
                SlideFace { y: 4; width: 128; slide: parent.modelData; opacity: parent.modelData.hidden ? 0.35 : 1 }
                Rectangle { y: 2; width: 132; height: 128 * 1080 / Backend.slideW + 4; color: "transparent"; radius: 4; border.width: parent.index === win.showIndex ? 2 : 0; border.color: Theme.t.accent; x: -2 }
                MouseArea { anchors.fill: parent; onClicked: win.goTo(parent.index) } } }
        Row { anchors { left: parent.left; leftMargin: parent.gap; bottom: parent.bottom; bottomMargin: parent.gap } spacing: 10
            Rectangle { width: 150; height: 44; radius: 12; color: "#1A1E24"
                Label { anchors.centerIn: parent; text: win.clock(win.elapsed); color: win.timing ? "#ECEFF3" : "#8A9099"; font.pixelSize: 24; font.family: Theme.t.fontMono } }
            Seg { icon: win.timing ? "pause" : "play"; tip: win.timing ? "Pause the timer" : "Carry on"; onClicked: win.timing = !win.timing }
            Seg { icon: "refresh"; tip: "Start the timer again"; onClicked: win.elapsed = 0 }
            Label { text: Qt.formatTime(new Date(new Date().getTime() + win.elapsed * 0), "hh:mm"); color: "#8A9099"; font.pixelSize: 16; anchors.verticalCenter: parent.verticalCenter; leftPadding: 10 } }
        Row { anchors { right: parent.right; rightMargin: parent.gap; bottom: parent.bottom; bottomMargin: parent.gap } spacing: 8
            Btn { text: "◀  Back"; onClicked: win.prev() }
            Btn { text: "Next  ▶"; primary: true; onClicked: win.next() }
            Btn { text: win.blank === "black" ? "Show the Slide" : "Black Screen"; onClicked: win.blank = win.blank === "black" ? "" : "black" }
            Btn { text: "End Show"; danger: true; onClicked: win.stop() } } }
}
