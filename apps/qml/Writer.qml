import QtQuick

// Writer, "floating pages": real pages float on the tint, one sheet after another; formatting is the island under
// them, where the light is. The document list (or its headings) runs down the left; the page's own tools sit at the
// top right.
GlassWindow {
    id: win
    title: "Writer"; glow: "bottom"; width: 1280; height: 840; minimumWidth: 820
    property var st: ({})
    property string notice: ""
    property string exported: ""
    property real zoomSet: 0                // 0: as big as fits, up to the real size; otherwise as the person set it
    readonly property real zoom: zoomSet > 0 ? zoomSet : Math.max(0.4, Math.min(1, (scroll.width - 60) / Math.max(1, pg.w)))
    property string pop: ""                 // the little menu that's open: style, font, size, colour, mark, align, spacing, insert
    property Item popFrom: null
    property string sheet: ""               // page, print, link, table
    property var sheetData: ({})
    property bool finding: false
    property bool replacing: false
    property int found: 0
    property string railTab: "docs"         // docs | outline | review
    property int replying: 0                // the comment being answered (its number)
    property var ctx: null                  // the right-click menu: {x, y, word, pos}
    property var pending: []                // formatting asked for with nothing selected: it goes on what's typed next
    property int pendingAt: -1
    property int pendingLen: 0
    readonly property var pg: Backend.paper
    readonly property int railW: 244
    readonly property real pageX: railW + 24

    function refresh() { st = Backend.state(editor.selectedText !== "" ? editor.selectionStart + 1 : editor.cursorPosition) }
    readonly property var toggles: ["bold", "italic", "underline", "strike", "super", "sub"]
    function apply(what) {
        var charLike = toggles.indexOf(what) >= 0 || /^(size:|font:|mark:|#)/.test(what)
        if (charLike && editor.selectedText === "" && atWordEdge()) {     // nothing to change yet: it goes on what's typed next
            var keep = pending.filter(function (w) { return w !== what && (toggles.indexOf(what) >= 0 || w.split(":")[0] !== what.split(":")[0]) && !(what.charAt(0) === "#" && w.charAt(0) === "#") })
            pending = toggles.indexOf(what) >= 0 && pending.indexOf(what) >= 0 ? keep : keep.concat([what])
            pendingAt = editor.cursorPosition; pendingLen = editor.length; editor.forceActiveFocus(); return
        }
        Backend.style(editor.selectionStart, editor.selectionEnd, what); refresh(); editor.forceActiveFocus()
    }
    function atWordEdge() { var p = editor.cursorPosition, t = editor.getText(Math.max(0, p - 1), p + 1); return !/\w/.test(t.charAt(1) || " ") || !/\w/.test(t.charAt(0) || " ") }
    function on(key) { return !!st[key] !== (pending.indexOf(key) >= 0) }
    // words spelled wrong: red waves under them, for what's on screen (Qt Quick's text can't draw them itself)
    property var squiggles: []
    Timer { id: spellTick; interval: 350; onTriggered: win.markSpelling() }
    Connections { target: Backend; function onSpellChanged() { spellTick.restart() } function onPageChanged() { spellTick.restart() } }
    function markSpelling() {
        if (Backend.current === "" || !Backend.spelling.on) { squiggles = []; return }
        var topY = Math.max(0, (scroll.contentY - host.y) / zoom), bottomY = topY + scroll.height / zoom
        var ranges = Backend.spellMarks(editor.positionAt(0, topY), editor.positionAt(pg.w, bottomY)), out = [], here = editor.cursorPosition
        for (var i = 0; i < ranges.length; i++) {
            var a = ranges[i][0], b = ranges[i][1]
            if (here >= a && here <= b && editor.activeFocus && typingTick.running) continue       // (not the word being typed)
            var r0 = editor.positionToRectangle(a), r1 = editor.positionToRectangle(b)
            if (Math.abs(r0.y - r1.y) < 2 && r1.x > r0.x) out.push({ x: r0.x, y: r0.y + r0.height - 1, w: r1.x - r0.x })
        }
        squiggles = out
    }
    Timer { id: typingTick; interval: 1500 }
    function checkPending() {     // typed on from where it was asked: it goes on what was typed; moved away: forgotten
        if (!pending.length || pendingAt < 0) return
        var here = editor.cursorPosition
        if (here > pendingAt && editor.length - pendingLen === here - pendingAt) {
            var at = pendingAt, list = pending; pending = []; pendingAt = -1
            for (var i = 0; i < list.length; i++) Backend.style(at, here, list[i])
            refresh()
        } else if (here !== pendingAt) { pending = []; pendingAt = -1 }
    }
    function openPop(kind, from) { if (pop === kind) { pop = ""; return } popFrom = from; pop = kind }
    property int footTick: 0
    Connections { target: Backend; function onFootnotesChanged() { win.footTick++ } }
    function ask(kind, data) { pop = ""; ctx = null; sheet = kind; sheetData = data || ({}) }
    function say(text) { win.notice = text; hide.restart() }
    // the top bar's menus (and their keys)
    function openFile() { Picker.open("Open a document", [["Documents", "*.odt *.docx *.doc *.rtf *.md *.txt *.html"]], function (paths) { if (paths.length) Backend.open(paths[0]) }) }
    function exportPdf() { if (Backend.current === "") return; var p = Backend.export("pdf"); if (p) { win.exported = p; win.notice = ""; hide.restart() } }
    function find() { if (Backend.current === "") return; finding = true; replacing = false; findBox.text = editor.selectedText || findBox.text; findBox.focusIn(); runFind() }
    function replace() { find(); replacing = true }
    function printIt() { if (Backend.current !== "") ask("print", { printers: Backend.printers(), copies: 1, pages: "", sides: false }) }
    function pageSetup() { if (Backend.current !== "") ask("page") }
    function insertImage() { if (Backend.current === "") return; var at = editor.cursorPosition
        Picker.open("Put in a picture", [["Pictures", "*.png *.jpg *.jpeg *.webp *.gif *.bmp"]], function (paths) {
            if (paths.length) { var why = Backend.insertPicture(at, paths[0]); if (why) say(why); else editor.forceActiveFocus() } }) }
    function insertTable() { if (Backend.current !== "") openPop("table", insertBtn) }
    function pageBreak() { if (Backend.current === "") return; var at = Backend.pageBreak(editor.cursorPosition); editor.cursorPosition = at; editor.forceActiveFocus() }
    function link() { if (Backend.current === "") return; ask("link", { url: Backend.linkAt(editor.selectionStart), text: editor.selectedText, a: editor.selectionStart, b: editor.selectionEnd }) }
    function zoomIn() { zoomBy(1.15) }
    function zoomOut() { zoomBy(1 / 1.15) }
    function showHeadings() { railTab = "outline"; outlineList.model = Backend.outline() }
    // review: comments and tracked changes (huginn_review)
    function showReview() { if (Backend.current !== "") railTab = "review" }
    function toggleTrack() { if (Backend.current === "") return; Backend.setTracking(!Backend.tracking); say(Backend.tracking ? "Changes are tracked: what you type and delete is marked." : "Changes aren't tracked any more.") }
    // footnotes: a numbered mark in the text, its words at the bottom of the page (Ctrl+Alt+F)
    function addFootnote() { if (Backend.current === "") return
        var at = editor.selectionEnd, id = Backend.insertFootnote(at); if (!id) return
        editor.cursorPosition = Math.min(editor.length, at + 1); editFootnote(id, true) }
    function editFootnote(id, fresh) { ask("footnote", { id: id, fresh: !!fresh }); footBox.many = Backend.footnote(id); footBox.focusIn() }
    function saveFootnote() { var d = sheetData
        if (!footBox.many.trim() && d.fresh) Backend.removeFootnote(d.id); else Backend.setFootnote(d.id, footBox.many.trim())
        sheet = ""; editor.forceActiveFocus() }
    function newNote() { if (Backend.current === "") return
        var a = editor.selectionStart, b = editor.selectionEnd
        if (a === b) { var w = Backend.wordAt(editor.cursorPosition); if (w && w.end > w.start) { a = w.start; b = w.end } }
        if (a === b) { say("Select the words to comment on first."); return }
        ask("note", { a: a, b: b, quote: Backend.textOf(a, b) }) }
    function nextChange(back) { if (Backend.current === "") return
        var hit = Backend.nextChange(back ? editor.selectionStart : editor.selectionEnd, back)
        if (!hit.length) { say("No changes to go through."); return }
        editor.select(hit[0], hit[1]); follow(editor.positionToRectangle(hit[0])) }
    function settleHere(accept) { if (Backend.current === "") return
        var hit = Backend.nextChange(Math.max(0, editor.selectionStart - 1), false), here = editor.selectionStart
        var list = Backend.changes, pick = null
        for (var i = 0; i < list.length; i++) if (here >= list[i].start && here <= list[i].end) { pick = list[i]; break }
        if (!pick) { if (hit.length) { editor.select(hit[0], hit[1]); follow(editor.positionToRectangle(hit[0])) } else say("No changes to go through."); return }
        var at = Backend.settle(pick.id, accept); if (at >= 0) editor.cursorPosition = Math.min(at, editor.length)
        nextChange(false) }
    function nextChangeOn() { nextChange(false) }
    function prevChange() { nextChange(true) }
    function acceptHere() { settleHere(true) }
    function rejectHere() { settleHere(false) }
    function acceptAll() { settleAll(true) }
    function rejectAll() { settleAll(false) }
    function settleAll(accept) { if (Backend.current === "") return; var n = Backend.settleAll(accept); say(n ? (n + (n === 1 ? " change " : " changes ") + (accept ? "accepted." : "rejected.")) : "No changes to go through.") }
    function wordBack(p) { var t = editor.getText(Math.max(0, p - 200), p), i = t.length
        while (i > 0 && /\s/.test(t.charAt(i - 1))) i--
        while (i > 0 && /\w/.test(t.charAt(i - 1))) i--
        return p - (t.length - i) }
    function zoomBy(f) { zoomSet = Math.max(0.4, Math.min(3, Math.round(zoom * f * 20) / 20)) }
    function fitWidth() { zoomSet = Math.max(0.4, Math.min(2.5, (scroll.width - 80) / pg.w)) }
    function runFind() { found = Backend.findAll(findBox.text, caseBtn.on, wholeBtn.on) }
    function step(back) {
        var hit = Backend.findNext(findBox.text, caseBtn.on, wholeBtn.on, back ? editor.selectionStart : editor.selectionEnd, back)
        if (hit.length) { editor.select(hit[0], hit[1]); follow(editor.positionToRectangle(hit[0])) } }
    function follow(r) {
        var top = host.y + r.y * zoom, bottom = top + r.height * zoom
        if (top < scroll.contentY + 40) scroll.contentY = Math.max(0, top - 40)
        else if (bottom > scroll.contentY + scroll.height - 120) scroll.contentY = Math.min(scroll.contentHeight - scroll.height, bottom - scroll.height + 120)
    }
    function goTo(at) { editor.cursorPosition = at; editor.forceActiveFocus(); var r = editor.positionToRectangle(at); scroll.contentY = Math.max(0, host.y + r.y * zoom - 60) }
    readonly property int pageNow: Math.min(Backend.pages, Math.max(1, Math.floor((editor.cursorRectangle.y) / Math.max(1, pg.stride)) + 1))

    // Huginn AI (Settings › AI): on what's selected, or on the whole document when nothing is
    readonly property var aiChoices: [["rewrite:clearer", "Make it clearer", ""], ["rewrite:shorter", "Make it shorter", ""], ["rewrite:friendlier", "Make it friendlier", ""],
                                      ["rewrite:formal", "Make it more formal", ""], ["rewrite:simpler", "Make it simpler", ""], ["", "", ""],
                                      ["proofread", "Proofread", ""], ["summarise", "Summarise", ""], ["continue", "Carry on writing", "at the cursor"]]
    function ai(key) {
        var a = editor.selectionStart, b = editor.selectionEnd, all = a === b
        var task = key.split(":")[0], style = key.split(":")[1] || ""
        if (task === "continue") { b = a = editor.cursorPosition; all = false }
        var text = task === "continue" ? Backend.textOf(0, a > 0 ? a : editor.length) : all ? Backend.textOf(0, 0) : Backend.textOf(a, b)
        if (text.trim() === "") { say("Write something first."); return }
        if (all) { a = 0; b = editor.length }
        var asked = task === "continue" ? "" : text
        function stillThere() { return task === "continue" || (all ? Backend.textOf(0, 0) : Backend.textOf(a, b)) === asked }
        function put(answer, at, till, lead) {
            if (!stillThere()) { aiPanel.copyIt(); say("The document changed meanwhile, so the answer is copied: paste it where you want it."); return }
            var end = Backend.putText(at, till, (lead || "") + answer); editor.cursorPosition = end; editor.forceActiveFocus()
        }
        var head = { "rewrite": ({ clearer: "Clearer", shorter: "Shorter", friendlier: "Friendlier", formal: "More formal", simpler: "Simpler" })[style], proofread: "Proofread",
                     summarise: "Summary", "continue": "Carried on" }[task]
        if (task === "summarise") aiPanel.run({ task: task, text: text, heading: head, accept: "Insert Below", onAccept: function (t) { put(t, b, b, "\n") } })
        else if (task === "continue") aiPanel.run({ task: task, text: text, heading: head, accept: "Insert", onAccept: function (t) { put(t, a, a, a > 0 ? "\n" : "") } })
        else aiPanel.run({ task: task, text: text, extra: { style: style }, heading: head, accept: all ? "Replace the Document" : "Replace", onAccept: function (t) { put(t, a, b, "") } })
    }
    Connections { target: Backend
        function onFailed(msg) { win.say(msg) }
        function onLoaded() { editor.cursorPosition = 0; win.refresh(); top.restart(); win.pending = []; if (win.finding) win.runFind(); spellTick.restart() } }
    Timer { id: hide; interval: 7000; onTriggered: { win.notice = ""; win.exported = "" } }
    Timer { id: top; interval: 30; onTriggered: { editor.cursorPosition = 0; scroll.contentY = 0 } }
    Component.onCompleted: { Backend.attach(editor.textDocument); refresh(); top.restart() }
    onClosing: Backend.save()
    Shortcut { sequence: "Ctrl+F"; enabled: Backend.current !== ""; onActivated: win.find() }
    Shortcut { sequence: "Ctrl+H"; enabled: Backend.current !== ""; onActivated: win.replace() }
    Shortcut { sequence: "Ctrl+P"; enabled: Backend.current !== ""; onActivated: win.printIt() }
    Shortcut { sequence: "Ctrl+K"; enabled: Backend.current !== ""; onActivated: win.link() }
    Shortcut { sequence: "Escape"; enabled: win.pop !== "" || win.sheet !== "" || win.ctx !== null || win.finding
        onActivated: { if (win.pop) win.pop = ""; else if (win.ctx) win.ctx = null; else if (win.sheet) win.sheet = ""; else { win.finding = false; Backend.findAll("", false, false) } editor.forceActiveFocus() } }

    islands: [
        Island {   // the document: its name, whether it is saved, how long it is, where the cursor is
            visible: Backend.current !== ""; x: win.pageX + Math.max(0, (win.width - win.pageX - width - toolsIsland.width - 24) / 2); y: 12
            Label { text: Backend.title || "Untitled"; font.pixelSize: 12; font.weight: Font.DemiBold; leftPadding: 10; width: Math.min(implicitWidth, 220); elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter }
            Label { leftPadding: 6; rightPadding: 10; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter; width: Math.min(implicitWidth, Math.max(120, win.width - win.pageX - 560)); elide: Text.ElideMiddle
                color: win.notice ? Theme.t.danger : Theme.t.text_secondary
                text: win.notice || (win.exported ? "Exported to " + win.exported : ((Backend.saved ? "Saved" : "Saving…") + "  ·  " + (editor.selectedText !== "" ? Backend.wordsIn(editor.selectionStart, editor.selectionEnd) + " of " : "")
                      + Backend.words + (Backend.words === 1 ? " word" : " words") + "  ·  page " + win.pageNow + " of " + Backend.pages)) }
            Seg { visible: win.exported !== ""; text: "Show in Files"; onClicked: Backend.reveal(win.exported) }
        },
        Island { id: toolsIsland; visible: Backend.current !== ""; anchors { right: parent.right; rightMargin: 12 } y: 12; z: 8
            Seg { icon: "search"; tip: "Find and replace (Ctrl+F)"; on: win.finding; onClicked: win.finding ? (win.finding = false) : win.find() }
            Seg { text: Backend.tracking ? "Tracking" : "Review"; on: Backend.tracking || win.railTab === "review"; tip: "Comments and tracked changes"
                onClicked: win.railTab = win.railTab === "review" ? "docs" : "review" }
            Seg { icon: "doc"; tip: "Page: size, margins, header and footer"; on: win.sheet === "page"; onClicked: win.pageSetup() }
            Seg { icon: "printer"; tip: "Print (Ctrl+P)"; onClicked: win.printIt() }
            ExportMenu {
                choices: [["pdf", "PDF", "For sending and printing, pages as you see them"], ["docx", "Word", "A .docx file for Microsoft Word and others"],
                          ["odt", "OpenDocument", "An .odt file"], ["md", "Markdown", "Plain text with simple marks"], ["txt", "Plain text", "Only the words"]]
                onChosen: function (key) { var p = Backend.export(key); if (p) { win.exported = p; win.notice = ""; hide.restart() } } } },
        // find and replace, under the name
        Island { id: findIsland; visible: win.finding && Backend.current !== ""; x: win.pageX + Math.max(0, (win.width - win.pageX - width) / 2); y: 60; z: 7
            TextBox { id: findBox; width: 200; height: 30; placeholder: "Find"; anchors.verticalCenter: parent.verticalCenter
                onEdited: win.runFind(); onAccepted: win.step(false)
                Keys.onPressed: function (e) { if (e.key === Qt.Key_Escape) { win.finding = false; Backend.findAll("", false, false); editor.forceActiveFocus(); e.accepted = true } } }
            Label { anchors.verticalCenter: parent.verticalCenter; width: 72; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 11; secondary: true
                text: findBox.text === "" ? "" : win.found === 0 ? "none" : win.found + (win.found === 1 ? " found" : " found") }
            Seg { icon: "up"; tip: "Previous"; onClicked: win.step(true) }
            Seg { icon: "down"; tip: "Next (Enter)"; onClicked: win.step(false) }
            Seg { id: caseBtn; text: "Aa"; tip: "Match capitals"; onClicked: { on = !on; win.runFind() } }
            Seg { id: wholeBtn; text: "Whole"; onClicked: { on = !on; win.runFind() } }
            IslandGap {}
            Seg { visible: !win.replacing; text: "Replace…"; onClicked: { win.replacing = true; replaceBox.focusIn() } }
            TextBox { id: replaceBox; visible: win.replacing; width: 170; height: 30; placeholder: "Replace with"; anchors.verticalCenter: parent.verticalCenter
                onAccepted: replaceOne.clicked() }
            Seg { id: replaceOne; visible: win.replacing; text: "Replace"; onClicked: {
                    if (editor.selectedText !== "" && editor.selectedText.toLowerCase() === findBox.text.toLowerCase()) { var end = Backend.replaceAt(editor.selectionStart, editor.selectionEnd, replaceBox.text); editor.cursorPosition = end }
                    win.runFind(); win.step(false) } }
            Seg { visible: win.replacing; text: "All"; onClicked: { var n = Backend.replaceAll(findBox.text, replaceBox.text, caseBtn.on, wholeBtn.on); win.say(n + (n === 1 ? " replaced" : " replaced")); win.runFind() } }
            Seg { icon: "x"; tip: "Close (Esc)"; onClicked: { win.finding = false; Backend.findAll("", false, false); editor.forceActiveFocus() } } },
        // the left: documents, or this one's headings
        Rail { id: docRail; x: 12; y: 64; width: win.railW - 12; maxHeight: win.height - 64 - 14
            Row { id: railTabs; visible: Backend.current !== ""; spacing: 2; height: 34
                readonly property real each: (docRail.width - 14) / 3
                Seg { width: railTabs.each; text: "Documents"; on: win.railTab === "docs"; onClicked: win.railTab = "docs" }
                Seg { width: railTabs.each; text: "Headings"; on: win.railTab === "outline"; onClicked: { win.railTab = "outline"; outlineList.model = Backend.outline() } }
                Seg { width: railTabs.each; text: "Review" + (Backend.changes.length + Backend.notes.length ? " · " + (Backend.changes.length + Backend.notes.length) : ""); on: win.railTab === "review"
                    onClicked: win.railTab = "review" } }
            DocList { visible: win.railTab === "docs" || Backend.current === ""; newLabel: "New Document"; icon: "doc"; empty: "Documents you write appear here. Word files in your Documents folder do too." }
            Column { visible: win.railTab === "outline" && Backend.current !== ""; width: parent.width; spacing: 1
                Timer { running: win.railTab === "outline"; interval: 1500; repeat: true; onTriggered: outlineList.model = Backend.outline() }
                Repeater { id: outlineList; model: []
                    Pressable { required property var modelData; width: parent.width; height: 30; radius: 9; color: hovered ? Theme.t.hover : "transparent"
                        onClicked: win.goTo(modelData.at)
                        Label { x: 8 + Math.max(0, modelData.level - 1) * 12; width: parent.width - x - 34; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight
                            text: modelData.text; font.pixelSize: modelData.level <= 2 ? 12 : 11; font.weight: modelData.level <= 2 ? Font.DemiBold : Font.Normal }
                        Label { anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } text: modelData.page; font.pixelSize: 10; secondary: true } } }
                Label { visible: outlineList.count === 0; width: parent.width; leftPadding: 8; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                    text: "Headings show here. Make one with the Style menu (Title, Heading, Subheading), then click to go to it." }
                Seg { visible: outlineList.count > 0; text: "Put Contents at the Cursor"; fill: true; onClicked: { var at = Backend.insertContents(editor.cursorPosition); editor.cursorPosition = at } } }
            // review: tracking, the changes, the comments
            Column { visible: win.railTab === "review" && Backend.current !== ""; width: parent.width; spacing: 6
                Item { width: parent.width; height: 34
                    Label { x: 8; anchors.verticalCenter: parent.verticalCenter; text: "Track changes"; font.weight: Font.DemiBold }
                    Toggle { anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter } on: Backend.tracking; onToggled: function (v) { Backend.setTracking(v) } } }
                Label { width: parent.width; leftPadding: 8; rightPadding: 8; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11
                    text: Backend.tracking ? "What you type is underlined in blue and what you delete stays, struck through, until someone accepts it. Signed " + Backend.author + "."
                                           : "Turn it on before handing the document round: everyone's additions and deletions are kept for you to accept or reject." }
                Label { visible: Backend.changes.length > 0; leftPadding: 8; topPadding: 6; text: "CHANGES · " + Backend.changes.length; secondary: true; font.pixelSize: 10; font.weight: Font.DemiBold }
                Row { visible: Backend.changes.length > 0; spacing: 2; height: 30
                    Seg { text: "Accept All"; onClicked: win.settleAll(true) } Seg { text: "Reject All"; onClicked: win.settleAll(false) }
                    Seg { icon: "up"; tip: "Previous change"; onClicked: win.nextChange(true) } Seg { icon: "down"; tip: "Next change"; onClicked: win.nextChange(false) } }
                Repeater { model: win.railTab === "review" ? Backend.changes : []
                    Pressable { required property var modelData; width: parent.width; height: 50; radius: 9; color: hovered ? Theme.t.hover : "transparent"
                        onClicked: { editor.select(modelData.start, modelData.end); win.follow(editor.positionToRectangle(modelData.start)); editor.forceActiveFocus() }
                        Rectangle { x: 4; y: 9; width: 3; height: parent.height - 18; radius: 1.5; color: modelData.kind === "ins" ? "#1A73E8" : "#D93025" }
                        Label { x: 14; y: 7; width: parent.width - 84; elide: Text.ElideRight; font.pixelSize: 10; secondary: true
                            text: (modelData.kind === "ins" ? "Added" : "Deleted") + " · " + modelData.by + (modelData.when ? " · " + modelData.when : "") }
                        Label { x: 14; y: 24; width: parent.width - 84; elide: Text.ElideRight; font.pixelSize: 12; font.strikeout: modelData.kind === "del"; text: modelData.text || "(a line break)" }
                        Row { anchors { right: parent.right; rightMargin: 4; verticalCenter: parent.verticalCenter } spacing: 0
                            Seg { icon: "check"; tip: "Accept"; onClicked: { Backend.settle(modelData.id, true); editor.forceActiveFocus() } }
                            Seg { icon: "x"; tip: "Reject"; onClicked: { Backend.settle(modelData.id, false); editor.forceActiveFocus() } } } } }
                Item { width: parent.width; height: 30
                    Label { x: 8; anchors.verticalCenter: parent.verticalCenter; text: "COMMENTS" + (Backend.notes.length ? " · " + Backend.notes.length : ""); secondary: true; font.pixelSize: 10; font.weight: Font.DemiBold }
                    Seg { anchors { right: parent.right; rightMargin: 2; verticalCenter: parent.verticalCenter } text: "+ New"; tip: "Comment on what's selected (Ctrl+Alt+M)"; onClicked: win.newNote() } }
                Label { visible: Backend.notes.length === 0; width: parent.width; leftPadding: 8; rightPadding: 8; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11
                    text: "Select some words and press Ctrl+Alt+M (or right-click › Comment) to leave a note on them." }
                Repeater { model: win.railTab === "review" ? Backend.notes : []
                    Rectangle { id: noteCard; required property var modelData; width: parent.width; height: noteCol.height + 16; radius: 11
                        color: Theme.t.group; border.width: 1; border.color: Backend.noteAt(editor.cursorPosition) === modelData.id ? Theme.t.accent : Theme.t.islandLine
                        opacity: modelData.done ? 0.62 : 1
                        MouseArea { anchors.fill: parent; enabled: !modelData.gone; onClicked: { editor.select(modelData.start, modelData.end); win.follow(editor.positionToRectangle(modelData.start)) } }
                        Column { id: noteCol; x: 10; y: 8; width: parent.width - 20; spacing: 4
                            Label { width: parent.width; elide: Text.ElideRight; font.pixelSize: 11; font.italic: true; secondary: true
                                text: modelData.gone ? "(the words it was on are gone)" : "“" + modelData.quote + "”" }
                            Label { width: parent.width; elide: Text.ElideRight; font.pixelSize: 10; font.weight: Font.DemiBold; color: Theme.t.accent
                                text: modelData.by + (modelData.when ? "  ·  " + modelData.when : "") + (modelData.done ? "  ·  resolved" : "") }
                            Label { width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 12; text: modelData.text }
                            Repeater { model: modelData.replies
                                Column { required property var modelData; width: noteCol.width; spacing: 1; topPadding: 4
                                    Label { width: parent.width; elide: Text.ElideRight; font.pixelSize: 10; font.weight: Font.DemiBold; secondary: true; text: modelData.by + (modelData.when ? "  ·  " + modelData.when : "") }
                                    Label { width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 12; text: modelData.text } } }
                            TextBox { id: replyBox; visible: win.replying === noteCard.modelData.id; width: parent.width; height: 32; placeholder: "Reply"
                                onAccepted: { Backend.replyNote(noteCard.modelData.id, text); text = ""; win.replying = 0 }
                                Keys.onEscapePressed: win.replying = 0 }
                            Row { spacing: 0
                                Seg { text: win.replying === noteCard.modelData.id ? "Send" : "Reply"
                                    onClicked: { if (win.replying === noteCard.modelData.id) { Backend.replyNote(noteCard.modelData.id, replyBox.text); replyBox.text = ""; win.replying = 0 }
                                                 else { win.replying = noteCard.modelData.id; replyBox.focusIn() } } }
                                Seg { text: noteCard.modelData.done ? "Reopen" : "Resolve"; onClicked: Backend.resolveNote(noteCard.modelData.id, !noteCard.modelData.done) }
                                Seg { icon: "trash"; tip: "Delete the comment"; onClicked: Backend.deleteNote(noteCard.modelData.id) } } } } } } },
        // a table at the cursor: its own island over the formatting one
        Island { id: tableIsland; visible: !!win.st.table && Backend.current !== ""; x: bar.x + (bar.width - width) / 2; anchors { bottom: bar.top; bottomMargin: 8 } z: 6
            Label { text: "Table"; font.pixelSize: 11; font.weight: Font.DemiBold; leftPadding: 8; rightPadding: 4; anchors.verticalCenter: parent.verticalCenter }
            Seg { text: "+ Row Above"; onClicked: win.table("rowAbove") } Seg { text: "+ Row Below"; onClicked: win.table("rowBelow") }
            Seg { text: "+ Column Left"; onClicked: win.table("colLeft") } Seg { text: "+ Column Right"; onClicked: win.table("colRight") }
            IslandGap {}
            Seg { text: "Merge"; tip: "Select cells first"; onClicked: win.table("merge") } Seg { text: "Split"; onClicked: win.table("split") }
            Seg { text: "Header Row"; onClicked: win.table("header") }
            IslandGap {}
            Seg { icon: "trash"; tip: "Delete the row"; onClicked: win.table("delRow") } Seg { text: "Delete Column"; onClicked: win.table("delCol") }
            Seg { text: "Delete Table"; danger: true; onClicked: win.table("delTable") } },
        // a picture at the cursor: how wide
        Island { id: picIsland; visible: !!win.st.image && !win.st.table && Backend.current !== ""; x: bar.x + (bar.width - width) / 2; anchors { bottom: bar.top; bottomMargin: 8 } z: 6
            Label { text: "Picture"; font.pixelSize: 11; font.weight: Font.DemiBold; leftPadding: 8; rightPadding: 4; anchors.verticalCenter: parent.verticalCenter }
            Repeater { model: [25, 50, 75, 100]
                Seg { required property int modelData; text: modelData + "%"; on: Math.abs(Backend.pictureShare(editor.cursorPosition) - modelData) <= 1
                    onClicked: { Backend.sizePicture(editor.cursorPosition, modelData); win.refresh() } } }
            Seg { text: "Left"; onClicked: win.apply("left") } Seg { text: "Centre"; onClicked: win.apply("center") }
            // text round it (Word's "Square"): the picture to one side, the words beside it
            IslandGap {}
            Label { text: "Text beside"; font.pixelSize: 11; secondary: true; leftPadding: 4; rightPadding: 2; anchors.verticalCenter: parent.verticalCenter }
            Repeater { model: [["", "No"], ["left", "On its right"], ["right", "On its left"]]
                Seg { required property var modelData; text: modelData[1]; objectName: "picSide-" + (modelData[0] || "none")
                    on: (win.st, Backend.pictureSide(editor.cursorPosition)) === modelData[0]
                    onClicked: { Backend.placePicture(editor.cursorPosition, modelData[0]); win.refresh() } } } },
        Island {   // formatting: the main island
            id: bar; visible: Backend.current !== ""; x: Math.max(12, Math.min(win.width - width - (zoomIsland.visible ? zoomIsland.width + 24 : 12), win.pageX + (win.width - win.pageX - width - (zoomIsland.visible ? zoomIsland.width + 30 : 0)) / 2))
            anchors { bottom: parent.bottom; bottomMargin: 14 }
            readonly property real room: win.width - win.pageX - (zoomIsland.visible ? zoomIsland.width : 0) - 40
            Pick { id: styleBtn; span: bar.room >= 520 ? 104 : 84; text: ({ title: "Title", heading: "Heading", subheading: "Subheading", minor: "Heading 3", body: "Body", quote: "Quote", code: "Code" })[win.st.style] || "Body"
                onClicked: win.openPop("style", styleBtn) }
            Pick { id: fontBtn; visible: bar.room >= 760; span: 112; text: win.st.font || "Inter"; font: win.st.font || "Inter"; onClicked: win.openPop("font", fontBtn) }
            Pick { id: sizeBtn; span: 50; text: win.st.size || 11; onClicked: win.openPop("size", sizeBtn) }
            Gap {}
            Tool { icon: "bold"; tip: "Bold (Ctrl+B)"; on: win.on("bold"); onClicked: win.apply("bold") }
            Tool { icon: "italic"; tip: "Italic (Ctrl+I)"; on: win.on("italic"); onClicked: win.apply("italic") }
            Tool { icon: "underline"; tip: "Underline (Ctrl+U)"; on: win.on("underline"); onClicked: win.apply("underline") }
            Tool { visible: bar.room >= 700; icon: "strike"; tip: "Strike through"; on: win.on("strike"); onClicked: win.apply("strike") }
            Tool { visible: bar.room >= 900; text: "x²"; tip: "Raised (Ctrl+Shift+=)"; on: win.on("super"); onClicked: win.apply("super") }
            Tool { visible: bar.room >= 900; text: "x₂"; tip: "Lowered (Ctrl+=)"; on: win.on("sub"); onClicked: win.apply("sub") }
            Tool { id: colourBtn; tip: "Text colour"; onClicked: win.openPop("colour", colourBtn)
                Label { anchors.centerIn: parent; anchors.verticalCenterOffset: -2; text: "A"; font.pixelSize: 14; font.weight: Font.Bold }
                Rectangle { x: 8; y: 22; width: 14; height: 3; radius: 1.5; color: win.st.colour || "#15181C" } }
            Tool { id: markBtn; visible: bar.room >= 620; tip: "Highlight"; onClicked: win.openPop("mark", markBtn)
                Glyph { anchors.centerIn: parent; anchors.verticalCenterOffset: -2; name: "pen"; size: 14; ink: Theme.t.icon }
                Rectangle { x: 8; y: 22; width: 14; height: 3; radius: 1.5; color: win.st.mark || "#FFE58F" } }
            Gap {}
            Tool { id: alignBtn; visible: bar.room >= 440; icon: ({ left: "alignleft", center: "aligncenter", right: "alignright", justify: "alignjustify" })[win.st.align || "left"]; tip: "Alignment"
                onClicked: win.openPop("align", alignBtn) }
            Tool { icon: "list"; tip: "Bullets"; on: win.st.list === "bullet"; onClicked: win.apply("bullet") }
            Tool { visible: bar.room >= 480; icon: "numbers"; tip: "Numbers"; on: win.st.list === "number"; onClicked: win.apply("number") }
            Tool { visible: bar.room >= 560; icon: "check"; tip: "Checklist"; on: win.st.list === "check"; onClicked: win.apply("check") }
            Tool { visible: bar.room >= 820; text: "⇤"; tip: "Less indent (Shift+Tab in a list)"; onClicked: win.apply("outdent") }
            Tool { visible: bar.room >= 820; text: "⇥"; tip: "More indent (Tab in a list)"; onClicked: win.apply("indent") }
            Tool { id: spacingBtn; visible: bar.room >= 760; text: "↕"; tip: "Line spacing"; onClicked: win.openPop("spacing", spacingBtn) }
            Gap {}
            Pick { id: insertBtn; span: bar.room >= 520 ? 76 : 44; text: bar.room >= 520 ? "Insert" : "+"; onClicked: win.openPop("insert", insertBtn) }
            Tool { visible: bar.room >= 980; icon: "clear"; tip: "Clear formatting"; onClicked: win.apply("clear") }
            Gap { visible: aiPanel.on("writer") }
            Tool { visible: aiPanel.on("writer"); icon: "sparkle"; tip: aiMenu.visible || aiPanel.visible ? "" : "Huginn AI"; on: aiMenu.visible || aiPanel.visible; onClicked: aiMenu.visible = !aiMenu.visible }
            Item { width: 2; height: 1 }
        },
        Island { id: zoomIsland; visible: Backend.current !== "" && win.width >= 1100; anchors { right: parent.right; rightMargin: 12; bottom: parent.bottom; bottomMargin: 14 }
            Seg { icon: "minus"; tip: "Smaller"; onClicked: win.zoomBy(1 / 1.15) }
            Pressable { width: 50; height: 30; radius: 10; anchors.verticalCenter: parent.verticalCenter; color: hovered ? Theme.t.hover : "transparent"; onClicked: win.zoomSet === 0 ? (win.zoomSet = 1) : (win.zoomSet = 0)
                Label { anchors.centerIn: parent; text: win.zoomSet === 0 && win.zoom < 1 ? "Fit" : Math.round(win.zoom * 100) + "%"; font.pixelSize: 12; font.family: Theme.t.fontMono } }
            Seg { icon: "plus"; tip: "Bigger"; onClicked: win.zoomBy(1.15) } },
        AiMenu { id: aiMenu; z: 9; items: win.aiChoices; anchors { right: bar.right; bottom: bar.top; bottomMargin: 8 }
            note: editor.selectedText !== "" ? "On what's selected." : "On the whole document (select some to work on just that)."
            onChosen: function (key) { win.ai(key) } },
        AiPanel { id: aiPanel; z: 9; x: bar.x + (bar.width - width) / 2; anchors { bottom: bar.top; bottomMargin: 8 } maxHeight: win.height * 0.55 },
        // the little menus over the formatting island
        Rectangle { id: popBox; visible: win.pop !== "" && win.popFrom !== null; z: 20; radius: 14; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
            readonly property point at: win.popFrom ? win.popFrom.mapToItem(parent, 0, 0) : Qt.point(0, 0)
            width: win.pop === "font" ? 230 : win.pop === "table" ? 8 * 26 + 24 : win.pop === "colour" || win.pop === "mark" ? 6 * 30 + 20 : win.pop === "insert" ? 230 : 170
            height: Math.min(win.height - 140, popInner.height + 12)
            x: Math.max(8, Math.min(parent.width - width - 8, at.x)); y: at.y - height - 10
            MouseArea { anchors.fill: parent }
            Flickable { anchors { fill: parent; margins: 6 } contentHeight: popInner.height; clip: true; interactive: popInner.height > height; boundsBehavior: Flickable.StopAtBounds
                Column { id: popInner; width: parent.width; spacing: 1
                    Repeater { model: win.pop === "style" ? [["title", "Title", 20], ["heading", "Heading", 16], ["subheading", "Subheading", 14], ["minor", "Heading 3", 13], ["body", "Body", 12], ["quote", "Quote", 12], ["code", "Code", 12]]
                                    : win.pop === "size" ? [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 60, 72].map(function (n) { return ["size:" + n, String(n), 12] })
                                    : win.pop === "font" ? Backend.fonts.slice(0, 300).map(function (f) { return ["font:" + f, f, 13, f] })
                                    : win.pop === "align" ? [["left", "Align left (Ctrl+L)", 12], ["center", "Centre (Ctrl+E)", 12], ["right", "Align right (Ctrl+R)", 12], ["justify", "Justify (Ctrl+J)", 12]]
                                    : win.pop === "spacing" ? [["spacing:100", "Single", 12], ["spacing:115", "1.15", 12], ["spacing:150", "1.5", 12], ["spacing:200", "Double", 12], ["space:0", "No space after paragraphs", 11], ["space:8", "Space after paragraphs", 11]]
                                    : win.pop === "insert" ? [["!table", "Table…", 12], ["!picture", "Picture…", 12], ["!break", "Page break (Ctrl+Enter)", 12], ["!link", "Link… (Ctrl+K)", 12], ["!line", "Line across", 12], ["!contents", "Contents from the headings", 12], ["!date", "Today's date", 12], ["!footnote", "Footnote (Ctrl+Alt+F)", 12]]
                                    : []
                        Pressable { required property var modelData; width: popInner.width; height: Math.max(30, modelData[2] + 16); radius: 9; color: hovered ? Theme.t.hover : "transparent"
                            onClicked: { var k = modelData[0], w = win; if (k.charAt(0) === "!") w.insertKind(k.slice(1)); else w.apply(k); if (w.pop !== "table") w.pop = "" }   // (closing last: this row goes with it)
                            Label { x: 10; width: parent.width - 20; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; text: modelData[1]; font.pixelSize: modelData[2]
                                font.family: modelData[3] || Theme.t.font; font.weight: win.pop === "style" && ["title", "heading", "subheading", "minor"].indexOf(modelData[0]) >= 0 ? Font.DemiBold : Font.Normal
                                font.italic: modelData[0] === "quote" } } }
                    Grid { visible: win.pop === "colour" || win.pop === "mark"; columns: 6; spacing: 6; padding: 4
                        Repeater { model: win.pop === "colour" ? ["#15181C", "#4B5563", "#9AA0A6", "#D93A3F", "#E8590C", "#C46A00", "#2B8A3E", "#0A8071", "#1C7ED6", "#2361AE", "#563AD1", "#C2255C"]
                                                               : ["#FFE58F", "#B7EB8F", "#91D5FF", "#FFADD2", "#FFD8BF", "#D3ADF7", "none"]
                            Rectangle { required property string modelData; width: 24; height: 24; radius: 12; color: modelData === "none" ? "transparent" : modelData; border.width: 1; border.color: Theme.t.islandLine
                                Label { visible: parent.modelData === "none"; anchors.centerIn: parent; text: "×"; font.pixelSize: 14 }
                                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: { var w = win; w.apply(w.popFrom === markBtn ? "mark:" + parent.modelData : parent.modelData); w.pop = "" } } } } }
                    // a table's size: point at the grid
                    Column { visible: win.pop === "table"; spacing: 6; padding: 6
                        property int rows: 2
                        property int cols: 3
                        id: tablePick
                        Grid { columns: 8; spacing: 2
                            Repeater { model: 48
                                Rectangle { required property int index; readonly property int r: Math.floor(index / 8) + 1; readonly property int c: index % 8 + 1
                                    width: 24; height: 18; radius: 3; color: r <= tablePick.rows && c <= tablePick.cols ? Qt.alpha(Theme.t.accent, 0.5) : Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
                                    MouseArea { anchors.fill: parent; hoverEnabled: true; onEntered: { tablePick.rows = parent.r; tablePick.cols = parent.c }
                                        onClicked: { var w = win, ed = editor, at = Backend.insertTable(ed.cursorPosition, parent.r, parent.c); ed.cursorPosition = at; ed.forceActiveFocus(); w.pop = "" } } } } }
                        Label { text: tablePick.rows + " × " + tablePick.cols; font.pixelSize: 11; secondary: true } } } } }
    ]
    function insertKind(k) {
        if (k === "table") { openPop("table", insertBtn); return }
        if (k === "picture") insertImage()
        else if (k === "break") pageBreak()
        else if (k === "link") link()
        else if (k === "line") Backend.insertLine(editor.cursorPosition)
        else if (k === "contents") { var at = Backend.insertContents(editor.cursorPosition); editor.cursorPosition = at }
        else if (k === "date") editor.insert(editor.cursorPosition, Qt.formatDate(new Date(), Qt.DefaultLocaleLongDate))
        else if (k === "footnote") { addFootnote(); return }
        editor.forceActiveFocus()
    }
    function table(action) { var at = Backend.tableDo(editor.selectionStart, editor.selectionEnd, action); editor.cursorPosition = Math.min(at, editor.length); refresh(); editor.forceActiveFocus() }

    component Tool: Pressable { id: t; property string icon: ""; property string text: ""; property bool on: false; property string tip: ""; property int span: 30
        width: span; height: 30; radius: 11; anchors.verticalCenter: parent ? parent.verticalCenter : undefined; color: on ? Theme.t.accent : (hovered ? Theme.t.hover : "transparent")
        Glyph { visible: t.icon !== ""; anchors.centerIn: parent; name: t.icon; size: 16; ink: t.on ? Theme.t.onAccent : Theme.t.icon }
        Label { visible: t.text !== ""; anchors.centerIn: parent; text: t.text; color: t.on ? Theme.t.onAccent : Theme.t.text; font.pixelSize: 13; font.weight: Font.DemiBold }
        Rectangle { visible: t.hovered && t.tip !== "" && win.pop === ""; z: 9; color: Theme.t.tooltip_bg; border.width: 1; border.color: Theme.t.menu_border; radius: 6; width: tt.width + 14; height: 24
            anchors { bottom: parent.top; bottomMargin: 10; horizontalCenter: parent.horizontalCenter }
            Label { id: tt; anchors.centerIn: parent; text: t.tip; font.pixelSize: 11 } } }
    component Pick: Pressable { id: pk; property string text: ""; property string font: ""; property int span: 90
        width: span; height: 30; radius: 10; anchors.verticalCenter: parent ? parent.verticalCenter : undefined; color: hovered || win.popFrom === pk && win.pop !== "" ? Theme.t.hover : Theme.t.group
        Label { x: 10; width: parent.width - 28; anchors.verticalCenter: parent.verticalCenter; text: pk.text; elide: Text.ElideRight; font.pixelSize: 12; font.family: pk.font || Theme.t.font }
        Glyph { anchors { right: parent.right; rightMargin: 7; verticalCenter: parent.verticalCenter } name: "down"; size: 11; ink: Theme.t.text_secondary } }
    component Gap: Item { width: 9; height: 30; anchors.verticalCenter: parent ? parent.verticalCenter : undefined; Rectangle { anchors.centerIn: parent; width: 1; height: 16; color: Theme.t.islandLine } }

    // ---------------------------------------------------------------- the start: a new document
    Column { visible: Backend.current === ""; x: win.middleX(width, parent.y + y, height, docRail) - parent.x; anchors.verticalCenter: parent.verticalCenter; spacing: 10
        Item { width: 190; height: 214; anchors.horizontalCenter: parent.horizontalCenter      // a sheet of paper with the first lines already on it
            Rectangle { x: 30; y: 14; width: 150; height: 196; radius: 6; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; rotation: 5; opacity: 0.6 }
            Rectangle { x: 20; y: 6; width: 150; height: 196; radius: 6; color: Theme.t.dark ? "#F4F1EA" : "#FFFFFF"; border.width: 1; border.color: Theme.t.islandLine
                Rectangle { x: 18; y: 22; width: 76; height: 9; radius: 3; color: Theme.t.accent }
                Repeater { model: [112, 104, 114, 92, 110, 60]; Rectangle { required property int modelData; required property int index; x: 18; y: 46 + index * 14; width: modelData; height: 4; radius: 2; color: "#33000000" } }
                Rectangle { x: 82; y: 113; width: 2; height: 12; color: Theme.t.accent; SequentialAnimation on opacity { loops: Animation.Infinite; NumberAnimation { to: 0; duration: 500 } NumberAnimation { to: 1; duration: 500 } } } } }
        Label { text: "Start a document"; font.pixelSize: 17; font.weight: Font.DemiBold; anchors.horizontalCenter: parent.horizontalCenter }
        Btn { text: "New Document"; primary: true; anchors.horizontalCenter: parent.horizontalCenter; onClicked: Backend.create() } }

    // ---------------------------------------------------------------- the pages
    Item { visible: Backend.current !== ""; x: win.pageX - 12; y: 56; width: parent.width - x; height: parent.height - 56
        Flickable { id: scroll; anchors.fill: parent; clip: true; boundsBehavior: Flickable.StopAtBounds
            onContentYChanged: spellTick.restart(); onHeightChanged: spellTick.restart()
            contentWidth: Math.max(width, win.pg.w * win.zoom + 80); contentHeight: host.y + (Backend.pages * win.pg.stride - 28) * win.zoom + 120
            WheelHandler { acceptedModifiers: Qt.ControlModifier; onWheel: function (e) { win.zoomBy(e.angleDelta.y > 0 ? 1.1 : 1 / 1.1) } }
            ImportNote { id: note; x: host.x; y: 14; width: win.pg.w * win.zoom; file: Backend.importedFile; dropped: Backend.importedDropped; onDismissed: Backend.dismissNote() }
            Item { id: host; x: Math.max(40, (scroll.width - win.pg.w * win.zoom) / 2); y: note.visible ? note.height + 28 : 22
                width: win.pg.w; height: Backend.pages * win.pg.stride; scale: win.zoom; transformOrigin: Item.TopLeft
                // a sheet of paper behind each page, with its header, footer and number
                Repeater { model: Backend.pages
                    Rectangle { required property int index; y: index * win.pg.stride; width: win.pg.w; height: win.pg.h; color: "#FFFFFF"; radius: 3
                        border.width: 1; border.color: Theme.t.dark ? "#000000" : "#CBD0D6"
                        readonly property string head: Backend.headerFor(index + 1) + (win.pg.pages >= 0 ? "" : "")
                        readonly property string foot: Backend.footerFor(index + 1) + (win.pg.pages >= 0 ? "" : "")
                        readonly property string num: Backend.numberFor(index + 1) + (win.pg.pages >= 0 ? "" : "")
                        readonly property var notes: (win.footTick, win.pg.room > 0 ? Backend.notesFor(index + 1) : [])
                        Column { visible: parent.notes.length > 0; x: win.pg.left; y: win.pg.h - win.pg.bottom - win.pg.room + 6; width: win.pg.w - win.pg.left - win.pg.right; spacing: 0
                            Rectangle { width: 140; height: 1; color: "#9AA1AA" }
                            Item { width: 1; height: 5 }
                            Repeater { model: parent.parent.notes
                                Text { required property var modelData; width: parent.width - 18; wrapMode: Text.Wrap; textFormat: Text.PlainText; bottomPadding: 3
                                    text: modelData.n + "  " + (modelData.text || "…"); color: modelData.text ? "#15181C" : "#9AA1AA"; font.family: "Inter"; font.pointSize: 9
                                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: win.editFootnote(parent.modelData.id) } } } }
                        Text { x: win.pg.left; y: Math.max(16, win.pg.top / 2 - 10); width: win.pg.w - win.pg.left - win.pg.right; height: 20; verticalAlignment: Text.AlignVCenter
                            text: parent.head; color: "#5F6670"; font.family: "Inter"; font.pointSize: 9; elide: Text.ElideRight }
                        Text { id: num1; x: win.pg.left; y: win.pg.numbers === "top-right" ? Math.max(16, win.pg.top / 2 - 10) : win.pg.h - Math.max(16, win.pg.bottom / 2) - 10
                            width: win.pg.w - win.pg.left - win.pg.right; height: 20; verticalAlignment: Text.AlignVCenter
                            horizontalAlignment: win.pg.numbers === "bottom-center" ? Text.AlignHCenter : Text.AlignRight; text: parent.num; color: "#5F6670"; font.family: "Inter"; font.pointSize: 9 }
                        Text { x: win.pg.left; y: win.pg.h - Math.max(16, win.pg.bottom / 2) - 10; width: win.pg.w - win.pg.left - win.pg.right - (num1.text !== "" && win.pg.numbers === "bottom-right" ? 40 : 0); height: 20
                            verticalAlignment: Text.AlignVCenter; text: parent.foot; color: "#5F6670"; font.family: "Inter"; font.pointSize: 9; elide: Text.ElideRight }
                        // the header and footer bands: double-click to change them
                        MouseArea { x: 0; y: 0; width: parent.width; height: win.pg.top - 4; onDoubleClicked: win.pageSetup(); cursorShape: Qt.PointingHandCursor }
                        MouseArea { x: 0; y: win.pg.h - win.pg.bottom + 4; width: parent.width; height: win.pg.bottom - 4; onDoubleClicked: win.pageSetup(); cursorShape: Qt.PointingHandCursor } } }
                Repeater { model: win.squiggles      // (over the sheets, under the text's own selection: drawn before it)
                    Canvas { required property var modelData; x: modelData.x; y: modelData.y; width: Math.max(4, modelData.w); height: 4; z: 2
                        onPaint: { var c = getContext("2d"); c.reset(); c.strokeStyle = "#E5484D"; c.lineWidth = 1.2; c.beginPath(); c.moveTo(0, 3)
                            for (var x = 0; x <= width; x += 2) c.lineTo(x, (x / 2) % 2 ? 0.8 : 3.2); c.stroke() } } }
                TextEdit { id: editor; objectName: "editor"; width: win.pg.w; focus: true; textFormat: TextEdit.RichText; wrapMode: TextEdit.Wrap
                    color: "#15181C"; selectionColor: Qt.alpha(Theme.t.accent, 0.35); selectedTextColor: "#15181C"; font.family: "Inter"; font.pointSize: 11; selectByMouse: true; persistentSelection: true
                    onCursorPositionChanged: { win.checkPending(); win.refresh(); if (win.ctx) win.ctx = null }
                    onSelectionStartChanged: win.refresh()
                    onCursorRectangleChanged: if (activeFocus) win.follow(cursorRectangle)
                    onTextChanged: { win.checkPending(); typingTick.restart(); spellTick.restart() }
                    Keys.onPressed: function (e) {
                        var ctrl = e.modifiers & Qt.ControlModifier, shift = e.modifiers & Qt.ShiftModifier
                        if (ctrl && (e.modifiers & Qt.AltModifier) && e.key === Qt.Key_M) { win.newNote(); e.accepted = true; return }
                        if (ctrl && (e.modifiers & Qt.AltModifier) && e.key === Qt.Key_F) { win.addFootnote(); e.accepted = true; return }
                        if (ctrl && shift && e.key === Qt.Key_R) { win.toggleTrack(); e.accepted = true; return }
                        if (Backend.tracking) {     // changes tracked: deleting strikes through, typing over a selection keeps it, struck through
                            var a = editor.selectionStart, b = editor.selectionEnd, at = -1
                            if (e.key === Qt.Key_Backspace || e.key === Qt.Key_Delete) {
                                if (a === b && ctrl) { if (e.key === Qt.Key_Backspace) a = win.wordBack(a); else { var t = editor.getText(b, Math.min(editor.length, b + 200)), m = /^\s*\w*/.exec(t); b += m ? m[0].length : 0 } }
                                at = Backend.trackDelete(a, b, e.key === Qt.Key_Backspace)
                                if (at >= 0) { editor.cursorPosition = at; e.accepted = true; return }
                            } else if (a !== b && ctrl && e.key === Qt.Key_X) {
                                editor.copy(); at = Backend.trackDelete(a, b, true); if (at >= 0) { editor.cursorPosition = at; e.accepted = true; return }
                            } else if (a !== b && ((ctrl && e.key === Qt.Key_V) || (!ctrl && e.text !== "" && e.text.charCodeAt(0) >= 32) || e.key === Qt.Key_Return || e.key === Qt.Key_Enter)) {
                                at = Backend.trackDelete(a, b, false); if (at >= 0) editor.cursorPosition = at      // (not taken: the editor puts the new text after it)
                            }
                        }
                        if (ctrl && (e.key === Qt.Key_Return || e.key === Qt.Key_Enter)) { win.pageBreak(); e.accepted = true; return }
                        if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter) && !shift && editor.selectedText === "") {     // after a heading or a quote: back to body text
                            var at = Backend.newParagraph(editor.cursorPosition); if (at >= 0) { editor.cursorPosition = at; e.accepted = true; return } }
                        if (e.key === Qt.Key_Tab && !ctrl && win.st.list) { win.apply("indent"); e.accepted = true; return }
                        if (e.key === Qt.Key_Backtab && win.st.list) { win.apply("outdent"); e.accepted = true; return }
                        if ((e.key === Qt.Key_Tab || e.key === Qt.Key_Backtab) && win.st.table && !ctrl) {     // the next cell (a new row after the last)
                            editor.cursorPosition = Backend.cellStep(editor.cursorPosition, e.key === Qt.Key_Backtab); e.accepted = true; return }
                        if (!ctrl) return
                        var k = { [Qt.Key_B]: "bold", [Qt.Key_I]: "italic", [Qt.Key_U]: "underline", [Qt.Key_L]: shift ? "bullet" : "left", [Qt.Key_E]: "center", [Qt.Key_R]: "right",
                                  [Qt.Key_J]: "justify", [Qt.Key_BracketRight]: "bigger", [Qt.Key_BracketLeft]: "smaller", [Qt.Key_Space]: "clear" }[e.key]
                        if (e.key === Qt.Key_Equal || e.key === Qt.Key_Plus) k = shift || e.key === Qt.Key_Plus ? "super" : "sub"
                        if ((e.modifiers & Qt.AltModifier) && e.key >= Qt.Key_1 && e.key <= Qt.Key_3) k = ["heading", "subheading", "minor"][e.key - Qt.Key_1]
                        if (shift && e.key === Qt.Key_N) k = "body"
                        if (k) { win.apply(k); e.accepted = true }
                    }
                    // a checklist's box, a link with Ctrl, a word spelled wrong with the right button
                    TapHandler { acceptedButtons: Qt.LeftButton; acceptedModifiers: Qt.NoModifier
                        onTapped: function (pt) { var p = editor.positionAt(pt.position.x, pt.position.y), s = Backend.checkboxAt(p)
                            if (s < 0) return; var r = editor.positionToRectangle(s)
                            if (pt.position.x < r.x - 2 && pt.position.x > r.x - 30 && pt.position.y >= r.y - 2 && pt.position.y <= r.y + r.height + 2) { Backend.toggleCheck(s); win.refresh() } } }
                    TapHandler { acceptedButtons: Qt.LeftButton; acceptedModifiers: Qt.ControlModifier
                        onTapped: function (pt) { var href = Backend.linkAt(editor.positionAt(pt.position.x, pt.position.y))
                            if (href.indexOf("#fn-") === 0) win.editFootnote(href.slice(4)); else if (href) Qt.openUrlExternally(href) } }
                    TapHandler { acceptedButtons: Qt.RightButton
                        onTapped: function (pt) { var p = editor.positionAt(pt.position.x, pt.position.y)
                            if (editor.selectedText === "" || p < editor.selectionStart || p > editor.selectionEnd) editor.cursorPosition = p
                            var g = editor.mapToItem(win.contentItem, pt.position.x, pt.position.y)
                            var here = Backend.changes.filter(function (c) { return p >= c.start && p <= c.end })[0]
                            var fn = Backend.footnoteAt(p), href = Backend.linkAt(p)
                            win.ctx = { x: g.x, y: g.y, pos: p, word: Backend.wordAt(p), href: href.indexOf("#fn-") === 0 ? "" : href, change: here ? here.id : 0, footnote: fn } } } } } } }

    // ---------------------------------------------------------------- the right-click menu: spelling, then the usual
    Rectangle { visible: win.ctx !== null; z: 30; x: Math.min(parent.width - width - 8, win.ctx ? win.ctx.x : 0); y: Math.min(parent.height - height - 8, win.ctx ? win.ctx.y : 0)
        width: 240; height: ctxCol.height + 12; radius: 14; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        Column { id: ctxCol; x: 6; y: 6; width: parent.width - 12; spacing: 1
            readonly property var w: win.ctx ? win.ctx.word || {} : {}
            Repeater { model: ctxCol.w.wrong ? (ctxCol.w.suggestions.length ? ctxCol.w.suggestions : ["(no suggestions)"]) : []
                Pressable { required property string modelData; width: ctxCol.width; height: 30; radius: 9; color: hovered ? Theme.t.hover : "transparent"; enabled: modelData.charAt(0) !== "("
                    onClicked: { var w = ctxCol.w, ed = editor, end = Backend.putText(w.start, w.end, modelData); ed.cursorPosition = end; ed.forceActiveFocus(); win.ctx = null }   // (the menu goes last: this row goes with it)
                    Label { x: 10; anchors.verticalCenter: parent.verticalCenter; text: modelData; font.weight: Font.DemiBold; secondary: modelData.charAt(0) === "(" } } }
            CtxItem { visible: !!ctxCol.w.wrong; label: "Add “" + (ctxCol.w.word || "") + "” to the Dictionary"; onClicked: { var w = ctxCol.w.word; win.ctx = null; Backend.learnWord(w) } }
            CtxItem { visible: !!ctxCol.w.wrong; label: "Ignore It Here"; onClicked: { var w = ctxCol.w.word; win.ctx = null; Backend.ignoreWord(w) } }
            Rectangle { visible: !!ctxCol.w.wrong; width: parent.width; height: 1; color: Theme.t.islandLine }
            CtxItem { visible: !!(win.ctx && win.ctx.href); label: "Open the Link"; onClicked: { var h = win.ctx.href; win.ctx = null; Qt.openUrlExternally(h) } }
            CtxItem { visible: !!(win.ctx && win.ctx.footnote); label: "Edit the Footnote…"; onClicked: { var f = win.ctx.footnote; win.ctx = null; win.editFootnote(f) } }
            CtxItem { visible: !!(win.ctx && win.ctx.footnote); label: "Delete the Footnote"; onClicked: { var f = win.ctx.footnote; win.ctx = null; Backend.removeFootnote(f) } }
            CtxItem { label: "Cut"; enabled: editor.selectedText !== ""; onClicked: { win.ctx = null; editor.cut() } }
            CtxItem { label: "Copy"; enabled: editor.selectedText !== ""; onClicked: { win.ctx = null; editor.copy() } }
            CtxItem { label: "Paste"; enabled: editor.canPaste; onClicked: { win.ctx = null; editor.paste() } }
            Rectangle { width: parent.width; height: 1; color: Theme.t.islandLine }
            CtxItem { label: "Link…"; onClicked: win.link() }
            CtxItem { label: "Comment…"; onClicked: { win.ctx = null; win.newNote() } }
            CtxItem { visible: !(win.ctx && win.ctx.footnote); label: "Footnote…"; onClicked: { win.ctx = null; win.addFootnote() } }
            CtxItem { visible: !!(win.ctx && win.ctx.change); label: "Accept the Change"; onClicked: { var c = win.ctx.change; win.ctx = null; Backend.settle(c, true) } }
            CtxItem { visible: !!(win.ctx && win.ctx.change); label: "Reject the Change"; onClicked: { var c = win.ctx.change; win.ctx = null; Backend.settle(c, false) } }
            CtxItem { visible: aiPanel.on("writer") && editor.selectedText !== ""; label: "Huginn AI…"; onClicked: { win.ctx = null; aiMenu.visible = true } } } }
    component CtxItem: Pressable { property string label: ""; width: parent ? parent.width : 200; height: visible ? 30 : 0; radius: 9; color: hovered ? Theme.t.hover : "transparent"; opacity: enabled ? 1 : 0.45
        Label { x: 10; anchors.verticalCenter: parent.verticalCenter; text: parent.label; font.pixelSize: 13 } }
    MouseArea { anchors.fill: parent; z: 19; visible: win.pop !== "" || win.ctx !== null; acceptedButtons: Qt.AllButtons; onPressed: { win.pop = ""; win.ctx = null } }

    // ---------------------------------------------------------------- sheets: page setup, printing, a link
    Item { anchors.fill: parent; z: 40; visible: win.sheet !== ""; onVisibleChanged: if (visible && win.sheet === "note") noteBox.focusIn()
        Rectangle { anchors.fill: parent; radius: win.r; color: "#66000000"; MouseArea { anchors.fill: parent; onClicked: if (win.sheet === "footnote") win.saveFootnote(); else win.sheet = "" } }
        Rectangle { id: card; anchors.centerIn: parent; width: 520; height: col.height + (win.sheet === "note" || win.sheet === "footnote" ? 124 : 84); radius: 20; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
            MouseArea { anchors.fill: parent }
            Label { x: 24; y: 20; font.pixelSize: 17; font.weight: Font.DemiBold; text: ({ page: "Page", print: "Print", link: "Link", note: "Comment", footnote: "Footnote" })[win.sheet] || "" }
            Column { id: col; x: 24; y: 56; width: parent.width - 48; spacing: 12
                // page setup
                Row { visible: win.sheet === "page"; spacing: 10
                    Label { text: "Paper"; width: 90; anchors.verticalCenter: parent.verticalCenter }
                    SetChoice { each: 72; value: win.pg.paper; options: [["letter", "Letter"], ["a4", "A4"], ["legal", "Legal"], ["a5", "A5"]]; onPicked: function (v) { Backend.setPage("paper", v) } } }
                Row { visible: win.sheet === "page"; spacing: 10
                    Label { text: "Turned"; width: 90; anchors.verticalCenter: parent.verticalCenter }
                    SetChoice { each: 100; value: win.pg.landscape ? "l" : "p"; options: [["p", "Portrait"], ["l", "Landscape"]]; onPicked: function (v) { Backend.setPage("landscape", v === "l") } } }
                Row { visible: win.sheet === "page"; spacing: 10
                    Label { text: "Margins"; width: 90; anchors.verticalCenter: parent.verticalCenter }
                    SetChoice { each: 80; options: [["narrow", "Narrow"], ["moderate", "Moderate"], ["normal", "Normal"], ["wide", "Wide"]]
                        value: Math.abs(win.pg.margins[0] - 12.7) < 0.1 ? "narrow" : Math.abs(win.pg.margins[1] - 19.05) < 0.1 ? "moderate" : Math.abs(win.pg.margins[1] - 50.8) < 0.1 ? "wide" : "normal"
                        onPicked: function (v) { Backend.setPage("margins", v) } } }
                Row { visible: win.sheet === "page"; spacing: 10
                    Label { text: "Header"; width: 90; anchors.verticalCenter: parent.verticalCenter }
                    TextBox { width: 360; text: win.pg.header || ""; placeholder: "At the top of each page"; onEdited: Backend.setPage("header", text) } }
                Row { visible: win.sheet === "page"; spacing: 10
                    Label { text: "Footer"; width: 90; anchors.verticalCenter: parent.verticalCenter }
                    TextBox { width: 360; text: win.pg.footer || ""; placeholder: "At the bottom of each page"; onEdited: Backend.setPage("footer", text) } }
                Label { visible: win.sheet === "page"; leftPadding: 100; width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 11; secondary: true
                    text: "{page}, {pages}, {title} and {date} are filled in on each page." }
                Row { visible: win.sheet === "page"; spacing: 10
                    Label { text: "Numbers"; width: 90; anchors.verticalCenter: parent.verticalCenter }
                    SetChoice { each: 90; value: win.pg.numbers; options: [["none", "None"], ["bottom-center", "Bottom"], ["bottom-right", "Bottom right"], ["top-right", "Top right"]]
                        onPicked: function (v) { Backend.setPage("numbers", v) } } }
                Row { visible: win.sheet === "page"; spacing: 10; height: 30
                    Label { text: "First page"; width: 90; anchors.verticalCenter: parent.verticalCenter }
                    Toggle { on: !win.pg.firstPage; anchors.verticalCenter: parent.verticalCenter; onToggled: function (v) { Backend.setPage("firstPage", !v) } }
                    Label { text: "No header, footer or number on it (a title page)"; secondary: true; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter } }
                Row { visible: win.sheet === "page" && Backend.spelling.available; spacing: 10; height: 30
                    Label { text: "Spelling"; width: 90; anchors.verticalCenter: parent.verticalCenter }
                    Toggle { on: Backend.spelling.on; anchors.verticalCenter: parent.verticalCenter; onToggled: function (v) { Backend.setSpelling(v) } }
                    Pick { id: langPick; visible: Backend.spelling.on; span: 230; text: (Backend.spelling.langs.filter(function (l) { return l.id === Backend.spelling.lang })[0] || { name: "" }).name
                        property bool open: false; onClicked: open = !open } }
                Flow { visible: win.sheet === "page" && langPick.open && langPick.visible; width: parent.width; leftPadding: 100; spacing: 4
                    Repeater { model: Backend.spelling.langs
                        Seg { required property var modelData; text: modelData.name; on: Backend.spelling.lang === modelData.id; onClicked: { Backend.setSpellLang(modelData.id); langPick.open = false } } } }
                // printing
                Label { visible: win.sheet === "print" && (win.sheetData.printers || []).length === 0; width: parent.width; wrapMode: Text.WordWrap
                    text: "No printer is set up yet. Add one in Print & Scan, or make a PDF and print it from another computer." }
                Column { visible: win.sheet === "print" && (win.sheetData.printers || []).length > 0; width: parent.width; spacing: 2
                    Repeater { model: win.sheet === "print" ? win.sheetData.printers || [] : []
                        Pressable { required property var modelData; width: parent.width; height: 38; radius: 10
                            readonly property bool chosen: (win.sheetData.printer || (win.sheetData.printers.filter(function (p) { return p["default"] })[0] || win.sheetData.printers[0]).id) === modelData.id
                            color: chosen ? Qt.alpha(Theme.t.accent, 0.2) : hovered ? Theme.t.hover : "transparent"
                            onClicked: { var d = win.sheetData; d.printer = modelData.id; win.sheetData = Object.assign({}, d) }
                            Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: "printer"; size: 16; ink: Theme.t.accent }
                            Label { x: 36; anchors.verticalCenter: parent.verticalCenter; text: modelData.name + (modelData["default"] ? "  ·  usual" : ""); font.weight: parent.chosen ? Font.DemiBold : Font.Normal } } } }
                Row { visible: win.sheet === "print" && (win.sheetData.printers || []).length > 0; spacing: 10
                    Label { text: "Copies"; width: 70; anchors.verticalCenter: parent.verticalCenter }
                    TextBox { id: copiesBox; width: 60; text: "1" }
                    Label { text: "Pages"; anchors.verticalCenter: parent.verticalCenter }
                    TextBox { id: pagesBox; width: 140; placeholder: "All, or 1-3,5" }
                    Toggle { id: sidesBox; anchors.verticalCenter: parent.verticalCenter }
                    Label { text: "Both sides"; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12 } }
                // a comment
                Label { visible: win.sheet === "note"; width: parent.width; elide: Text.ElideRight; font.italic: true; secondary: true; text: "On “" + (win.sheetData.quote || "") + "”" }
                TextBox { id: noteBox; visible: win.sheet === "note"; width: parent.width; lines: 4; placeholder: "What do you want to say about it?" }
                // a footnote
                TextBox { id: footBox; visible: win.sheet === "footnote"; width: parent.width; lines: 4; placeholder: "What goes at the bottom of the page" }
                // a link
                TextBox { id: urlBox; visible: win.sheet === "link"; width: parent.width; placeholder: "https://…"; text: win.sheetData.url || ""; onAccepted: linkOk.clicked() }
                TextBox { id: linkText; visible: win.sheet === "link" && !win.sheetData.text; width: parent.width; placeholder: "The words to show (the address, when empty)" } }
            Row { anchors { right: parent.right; rightMargin: 20; bottom: parent.bottom; bottomMargin: 16 } spacing: 8
                Btn { visible: win.sheet === "print"; text: "Make a PDF Instead"; onClicked: { win.sheet = ""; win.exportPdf() } }
                Btn { visible: win.sheet === "link" && !!win.sheetData.url; text: "Remove the Link"; onClicked: { Backend.link(win.sheetData.a, win.sheetData.b, "", ""); win.sheet = "" } }
                Btn { visible: win.sheet === "footnote"; text: "Delete the Footnote"; onClicked: { Backend.removeFootnote(win.sheetData.id); win.sheet = ""; editor.forceActiveFocus() } }
                Btn { visible: win.sheet !== "footnote"; text: win.sheet === "page" ? "Done" : "Cancel"; onClicked: { win.sheet = ""; editor.forceActiveFocus() } }
                Btn { visible: win.sheet === "footnote"; primary: true; text: "Done"; onClicked: win.saveFootnote() }
                Btn { id: linkOk; visible: win.sheet === "link"; primary: true; text: "Link"; onClicked: { Backend.link(win.sheetData.a, win.sheetData.b, urlBox.text, linkText.text); win.sheet = ""; editor.forceActiveFocus() } }
                Btn { visible: win.sheet === "note"; primary: true; text: "Comment"; opacity: noteBox.many.trim() ? 1 : 0.5
                    onClicked: { if (!noteBox.many.trim()) return; Backend.addNote(win.sheetData.a, win.sheetData.b, noteBox.many); noteBox.many = ""; noteBox.focusIn(); win.sheet = ""; win.railTab = "review"; editor.forceActiveFocus() } }
                Btn { visible: win.sheet === "print" && (win.sheetData.printers || []).length > 0; primary: true; text: "Print"
                    onClicked: { var ps = win.sheetData.printers, pr = win.sheetData.printer || (ps.filter(function (p) { return p["default"] })[0] || ps[0]).id
                        var why = Backend.printTo(pr, parseInt(copiesBox.text) || 1, pagesBox.text, sidesBox.on); win.sheet = ""; win.say(why || "Sent to " + pr.replace(/_/g, " ") + ".") } } } } }
}
