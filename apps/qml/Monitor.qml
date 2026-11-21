import QtQuick

// System Monitor: what the computer is doing, and what you can do about it.
// Across the top, five live cards: Processor, Memory, Graphics, Disk and Network, each with its last two minutes; a
// card opens its detail in Performance. Under them, one of four views:
//   Apps        the processes put together as you think of them (an app and its helpers are one row, with its icon),
//               then the session's helpers (Background), then everyone else's (System, folded away);
//   Processes   every process with every column, sorted by any of them, yours or everyone's;
//   Performance the card chosen above, in full: the processor's cores, what the memory holds, the graphics card's
//               readings, each drive and each network connection;
//   Startup     what starts when you sign in, each switched on or off, with how heavy it was then (huginn_autostart.py).
// Select a row for End and More…; right-click for everything (pause, priority, location, details, force stop).
GlassWindow {
    id: win
    title: "System Monitor"; heading: ({ apps: "Apps", procs: "Processes", perf: "Performance", startup: "Startup" })[view] || ""
    width: 1200; height: 780; minimumWidth: 900; glow: "top"; padTop: 58
    property string view: "apps"                 // apps | procs | perf | startup
    onViewChanged: if (view === "startup") Backend.loadStartup()
    property string startPicked: ""              // Startup: the chosen sign-in program's id
    readonly property var st: Backend.startup || ({})
    readonly property var stRows: st.entries || []
    readonly property var stPicked: stRows.filter(function (e) { return e.id === win.startPicked })[0] || null
    Timer { interval: 10000; repeat: true; running: win.view === "startup" && win.visible; onTriggered: Backend.loadStartup() }
    property var startMenu: null                 // {e, x, y}
    property string perf: "cpu"                  // cpu | mem | gpu | disk | net
    property string filter: ""
    property string sortKey: "cpu"
    property bool sortUp: false
    property bool everyone: false                // Processes: everyone's, not only yours
    property bool showSystem: false              // Apps: the System section unfolded
    property var open: ({})                      // Apps: unfolded apps, by key
    property var picked: null                    // {kind: "app", key} or {kind: "proc", pid}
    property var menuFor: null                   // {item, x, y}
    property var asking: null                    // {item, force}
    property var props: null                     // {title, list}
    property string notice: ""
    readonly property var cpu: Backend.cpuInfo || ({})
    readonly property var mem: Backend.memInfo || ({})
    readonly property var gpu: Backend.gpuInfo || ({})
    readonly property var hist: Backend.history || ({})
    readonly property var tot: Backend.totals || ({})
    readonly property bool hasGpu: gpu.load !== undefined
    readonly property color ink: Theme.t.accent
    readonly property color ink2: Theme.t.glowB
    Connections { target: Backend; function onFailed(msg) { win.notice = msg; hide.restart() } }
    Timer { id: hide; interval: 6000; onTriggered: win.notice = "" }

    // ---------------------------------------------------------------------------------------------------- helpers
    function pct(v) { return (v < 10 && v > 0 ? v.toFixed(1) : Math.round(v)) + "%" }
    function gb(b) { return (b / 1073741824).toFixed(b >= 107374182400 ? 0 : 1) + " GB" }
    function size(b) { return Backend.size(b) }
    function rate(b) { return b < 0 ? "–" : Backend.rate(b) }
    function heat(v) { var a = Math.max(0, Math.min(1, v)); return Qt.rgba(ink.r, ink.g, ink.b, a < 0.08 ? 0 : 0.05 + a * 0.3) }   // only what stands out
    function matches(name) { return win.filter === "" || String(name).toLowerCase().indexOf(win.filter.toLowerCase()) >= 0 }
    function order(list) {
        var k = sortKey, up = sortUp
        return list.slice().sort(function (a, b) {
            var d = k === "name" || k === "user" ? String(a[k]).toLowerCase().localeCompare(String(b[k]).toLowerCase()) : (a[k] - b[k])
            if (d === 0) d = a.memory - b.memory
            return up ? d : -d
        })
    }
    function sortBy(k) { if (sortKey === k) sortUp = !sortUp; else { sortKey = k; sortUp = (k === "name" || k === "user" || k === "pid") } }
    function letterColor(s) { var h = 0; for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360; return Qt.hsla(h / 360, 0.45, Theme.t.dark ? 0.42 : 0.55, 1) }
    function duration(s) { var h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60); return h >= 24 ? Math.floor(h / 24) + " d " + (h % 24) + " h" : h > 0 ? h + " h " + m + " min" : m + " min" }
    readonly property var appsAll: Backend.apps || []
    readonly property var appNames: { var m = {}; for (var i = 0; i < appsAll.length; i++) if (appsAll[i].kind === "app") m[appsAll[i].key] = appsAll[i].name; return m }
    readonly property var sections: {
        var by = { app: [], background: [], system: [] }
        for (var i = 0; i < appsAll.length; i++) if (matches(appsAll[i].name)) by[appsAll[i].kind].push(appsAll[i])
        return [{ id: "app", title: "Apps", rows: order(by.app) }, { id: "background", title: "Background", rows: order(by.background) },
                { id: "system", title: "System", rows: order(by.system) }]
    }
    function rowsOf(key) { return order((Backend.rows || []).filter(function (r) { return r.app === key })) }
    readonly property var procRows: order((Backend.rows || []).filter(function (r) { return (everyone || r.mine) && (matches(r.name) || String(r.pid) === win.filter) }))
    function itemOf(sel) {
        if (!sel) return null
        if (sel.kind === "app") { var a = appsAll.filter(function (x) { return x.key === sel.key })[0]; return a ? { kind: "app", name: a.name, pids: a.pids, paused: a.paused, mine: a.kind !== "system", app: a } : null }
        var r = (Backend.rows || []).filter(function (x) { return x.pid === sel.pid })[0]
        return r ? { kind: "proc", name: r.name, pids: [r.pid], paused: r.paused, mine: r.mine, row: r } : null
    }
    readonly property var current: itemOf(picked)
    function act(what, it) {
        if (!it) return
        if (what === "end") asking = { item: it, force: false }
        else if (what === "force") asking = { item: it, force: true }
        else if (what === "pause") it.paused ? Backend.resume(it.pids) : Backend.pause(it.pids)
        else if (what === "where") Backend.showLocation(it.pids[0])
        else if (what === "slow") { for (var i = 0; i < it.pids.length; i++) Backend.setNice(it.pids[i], 10) }
        else if (what === "normal") { for (var j = 0; j < it.pids.length; j++) Backend.setNice(it.pids[j], 0) }
        else if (what === "props") {
            var list = Backend.details(it.pids[0])
            if (it.kind === "app" && it.pids.length > 1) list = [{ name: "Processes", value: it.pids.length + " (" + it.pids.slice(0, 12).join(", ") + (it.pids.length > 12 ? "…" : "") + ")" }].concat(list)
            props = { title: it.name, list: list }
        }
    }

    // ---------------------------------------------------------------------------------------------------- pieces
    component Cell: Item {   // a number in a column, tinted by how much it is
        property string text; property real amount: 0; property bool dim: false
        width: 104; height: parent ? parent.height : 40
        Rectangle { anchors.fill: parent; anchors.margins: 3; radius: 7; color: win.heat(parent.amount) }
        Label { anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter } text: parent.text
            font.family: Theme.t.fontMono; font.pixelSize: 12; color: parent.dim ? Theme.t.text_secondary : Theme.t.text }
    }
    component Head: Pressable {   // a column's name: click to sort by it
        id: hd
        property string text; property string key; property bool alignLeft: false
        width: 104; height: 32; radius: 8
        onClicked: if (key) win.sortBy(key)
        readonly property bool on: win.sortKey === key
        Label { x: hd.alignLeft ? 10 : 6; width: parent.width - 18; anchors.verticalCenter: parent.verticalCenter; horizontalAlignment: hd.alignLeft ? Text.AlignLeft : Text.AlignRight
            text: hd.text + (hd.on ? (win.sortUp ? "  ↑" : "  ↓") : ""); font.pixelSize: 11; font.weight: hd.on ? Font.DemiBold : Font.Medium
            color: hd.on ? Theme.t.text : Theme.t.text_secondary }
    }
    component Icon: Item {   // an app's icon, or its first letter on a colour of its own; a helper's, a plain tile with a sign
        id: ic
        property string icon; property string name; property int s: 28; property string glyph: ""
        width: s; height: s
        Image { id: im; anchors.fill: parent; visible: status === Image.Ready && ic.glyph === ""; source: ic.icon !== "" && ic.glyph === "" ? "image://sysicon/" + ic.icon : ""
            sourceSize: Qt.size(ic.s * 2, ic.s * 2); asynchronous: true }
        Rectangle { anchors.fill: parent; visible: im.status !== Image.Ready || ic.glyph !== ""; radius: ic.s * 0.28
            color: ic.glyph !== "" ? Theme.t.hover : win.letterColor(ic.name)
            Label { visible: ic.glyph === ""; anchors.centerIn: parent; text: String(ic.name).charAt(0).toUpperCase(); color: "#FFFFFF"; font.pixelSize: ic.s * 0.46; font.weight: Font.DemiBold }
            Glyph { visible: ic.glyph !== ""; anchors.centerIn: parent; name: ic.glyph; size: ic.s * 0.55; ink: Theme.t.text_secondary } }
    }
    component Top: Column {   // what's using the most of one thing, apps and helpers together; a click shows it in Apps
        id: tp
        property string by: "cpu"
        property string title: ""
        width: parent ? parent.width : 400; spacing: 4
        readonly property var list: (win.appsAll || []).filter(function (a) { return a[tp.by] > 0 }).sort(function (a, b) { return b[tp.by] - a[tp.by] }).slice(0, 5)
        readonly property real most: list.length ? list[0][tp.by] : 1
        function shown(v) { return tp.by === "memory" ? win.size(v) : tp.by === "disk" ? win.rate(v) : win.pct(v) }
        Label { text: tp.title; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold; bottomPadding: 4 }
        Repeater { model: tp.list
            Pressable { required property var modelData; width: tp.width; height: 32; radius: 8; color: hovered ? Theme.t.hover : "transparent"
                onClicked: { win.picked = { kind: "app", key: modelData.key }; win.view = "apps" }
                Icon { x: 6; s: 20; anchors.verticalCenter: parent.verticalCenter; icon: modelData.icon; name: modelData.name
                    glyph: modelData.kind === "app" ? "" : modelData.kind === "system" ? "shield" : "gear" }
                Label { x: 36; width: 240; anchors.verticalCenter: parent.verticalCenter; text: modelData.name; elide: Text.ElideRight; font.pixelSize: 12 }
                Meter { x: 290; width: parent.width - 290 - 120; anchors.verticalCenter: parent.verticalCenter; value: modelData[tp.by] / Math.max(0.0001, tp.most) }
                Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: tp.shown(modelData[tp.by]); font.family: Theme.t.fontMono; font.pixelSize: 12 } } }
    }
    component Card: Rectangle { radius: 16; color: Theme.t.group; border.width: 1; border.color: Theme.t.separator }
    component Stat: Column {   // a reading in the Performance view: its name over its value
        property string name; property string value; property color dot: "transparent"
        width: 170; spacing: 3
        Row { spacing: 6
            Rectangle { visible: parent.parent.dot.a > 0; width: 8; height: 8; radius: 4; color: parent.parent.dot; anchors.verticalCenter: parent.verticalCenter }
            Label { text: parent.parent.name; secondary: true; font.pixelSize: 11 } }
        Label { text: parent.value; font.pixelSize: 17; font.weight: Font.Medium }
    }

    // ---------------------------------------------------------------------------------------------------- toolbar
    toolbar: [
        IslandField { visible: win.view === "apps" || win.view === "procs"; text: win.filter; onTextChanged: win.filter = text; placeholder: win.view === "apps" ? "Find an app" : "Find a process" },
        Seg { icon: "bolt"; text: "Startup"; on: win.view === "startup"; onClicked: win.view = "startup" },
        Seg { icon: "sliders"; text: "Performance"; on: win.view === "perf"; onClicked: win.view = "perf" },
        Seg { icon: "list"; text: "Processes"; on: win.view === "procs"; onClicked: win.view = "procs" },
        Seg { icon: "apps"; text: "Apps"; on: win.view === "apps"; onClicked: win.view = "apps" }
    ]

    Label { visible: !Backend.supported; anchors.centerIn: parent; secondary: true; text: "System Monitor reads Linux's process list, which this system doesn't have." }

    Item {
        visible: Backend.supported
        anchors { fill: parent; leftMargin: 14; rightMargin: 14; bottomMargin: 14 }

        // ------------------------------------------------------------------------------------------- the five cards
        Row {
            id: vitals
            width: parent.width; height: 110; spacing: 10
            Repeater {
                model: [
                    { id: "cpu", title: "Processor", glyph: "cpu", value: win.pct((win.cpu.load || 0) * 100),
                      sub: [win.cpu.ghz ? win.cpu.ghz + " GHz" : "", win.cpu.temp ? win.cpu.temp + " °C" : ""].filter(Boolean).join("  ·  ") || ((win.cpu.count || 0) + " threads"),
                      a: win.hist.cpu || [], b: [], unit: true },
                    { id: "mem", title: "Memory", glyph: "memory", value: win.gb(win.mem.used || 0),
                      sub: "of " + win.gb(win.mem.total || 0) + "  ·  " + Math.round(100 * (win.mem.used || 0) / Math.max(1, win.mem.total || 1)) + "%", a: win.hist.mem || [], b: [], unit: true },
                    { id: "gpu", title: "Graphics", glyph: "display", value: win.hasGpu ? win.gpu.load + "%" : "–",
                      sub: win.hasGpu ? [win.gpu.memTotal ? win.gpu.memUsed + " of " + win.gpu.memTotal + " GB" : "", win.gpu.temp ? win.gpu.temp + " °C" : ""].filter(Boolean).join("  ·  ") : "No readings from this card",
                      a: win.hist.gpu || [], b: [], unit: true },
                    { id: "disk", title: "Disk", glyph: "drive", value: win.rate((win.tot.read || 0) + (win.tot.write || 0)),
                      sub: "Read " + win.rate(win.tot.read || 0) + "  ·  Write " + win.rate(win.tot.write || 0), a: win.hist.read || [], b: win.hist.write || [], unit: false },
                    { id: "net", title: "Network", glyph: "globe", value: win.rate(win.tot.down || 0),
                      sub: "↓ " + win.rate(win.tot.down || 0) + "  ·  ↑ " + win.rate(win.tot.up || 0), a: win.hist.down || [], b: win.hist.up || [], unit: false }]
                Pressable {
                    id: vc
                    required property var modelData
                    objectName: "vital_" + modelData.id
                    readonly property bool chosen: win.view === "perf" && win.perf === modelData.id
                    width: (vitals.width - 40) / 5; height: vitals.height; radius: 16
                    color: chosen ? Qt.rgba(win.ink.r, win.ink.g, win.ink.b, Theme.t.dark ? 0.16 : 0.12) : (hovered ? Theme.t.hover : Theme.t.group)
                    border.width: chosen ? 2 : 1; border.color: chosen ? Theme.t.accent : Theme.t.separator
                    onClicked: { win.perf = modelData.id; win.view = "perf" }
                    Graph { x: 1; y: parent.height - height - 2; width: parent.width - 2; height: 34; first: vc.modelData.a; second: vc.modelData.b; unit: vc.modelData.unit
                        grid: false; opacity: 0.8 }
                    Row { x: 14; y: 11; spacing: 6
                        Glyph { name: vc.modelData.glyph; size: 13; ink: Theme.t.text_secondary; anchors.verticalCenter: parent.verticalCenter }
                        Label { text: vc.modelData.title; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold } }
                    Label { x: 14; y: 26; text: vc.modelData.value; font.pixelSize: 21; font.weight: Font.Light }
                    Label { x: 14; y: 53; width: parent.width - 28; text: vc.modelData.sub; secondary: true; font.pixelSize: 11; elide: Text.ElideRight }
                }
            }
        }

        // ------------------------------------------------------------------------------------------- Apps
        Card {
            id: appsCard
            visible: win.view === "apps"
            y: vitals.height + 12; width: parent.width; height: parent.height - y
            Row { id: appsHead; x: 8; y: 6; height: 32
                Head { width: appsCard.width - 16 - 4 * 104; text: "Name"; key: "name"; alignLeft: true }
                Head { text: "Processor"; key: "cpu" } Head { text: "Memory"; key: "memory" } Head { text: "Graphics"; key: "gpu" } Head { text: "Disk"; key: "disk" } }
            Rectangle { y: 40; width: parent.width; height: 1; color: Theme.t.separator }
            Flickable {
                id: appsList
                x: 8; y: 44; width: parent.width - 16; height: parent.height - y - 44; contentHeight: appsCol.height; clip: true; boundsBehavior: Flickable.StopAtBounds
                Column {
                    id: appsCol
                    width: parent.width
                    Repeater {
                        model: win.sections
                        Column {
                            id: sec
                            required property var modelData
                            readonly property bool folded: modelData.id === "system" && !win.showSystem
                            width: appsCol.width
                            visible: modelData.rows.length > 0
                            Item { width: parent.width; height: 34
                                Label { x: 8; anchors.verticalCenter: parent.verticalCenter; text: sec.modelData.title + "  ·  " + sec.modelData.rows.length
                                    font.pixelSize: 12; font.weight: Font.DemiBold; secondary: true }
                                Label { visible: sec.modelData.id === "system"; anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
                                    text: win.showSystem ? "Hide" : "Show"; color: Theme.t.accent; font.pixelSize: 12
                                    MouseArea { anchors.fill: parent; anchors.margins: -6; cursorShape: Qt.PointingHandCursor; onClicked: win.showSystem = !win.showSystem } }
                                Label { visible: sec.modelData.id === "system" && !win.showSystem; x: 140; anchors.verticalCenter: parent.verticalCenter
                                    text: "Other users' and the system's own: services, drivers' helpers"; secondary: true; font.pixelSize: 11 } }
                            Repeater {
                                model: sec.folded ? [] : sec.modelData.rows
                                Column {
                                    id: ar
                                    required property var modelData
                                    readonly property bool unfolded: !!win.open[modelData.key]
                                    width: sec.width
                                    Pressable {
                                        id: line
                                        objectName: "app_" + ar.modelData.key
                                        readonly property bool sel: win.picked !== null && win.picked.kind === "app" && win.picked.key === ar.modelData.key
                                        width: parent.width; height: 46; radius: 10
                                        color: sel ? Qt.rgba(win.ink.r, win.ink.g, win.ink.b, 0.22) : (hovered ? Theme.t.hover : "transparent")
                                        border.width: sel ? 1 : 0; border.color: Theme.t.accent
                                        // unfold its processes
                                        Item { x: 4; width: 22; height: parent.height; visible: ar.modelData.count > 1
                                            Glyph { anchors.centerIn: parent; name: ar.unfolded ? "down" : "forward"; size: 11; ink: Theme.t.text_secondary }
                                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                                onClicked: { var o = Object.assign({}, win.open); o[ar.modelData.key] = !ar.unfolded; win.open = o } } }
                                        Icon { x: 30 + (ar.modelData.kind === "app" ? 0 : 2); anchors.verticalCenter: parent.verticalCenter; icon: ar.modelData.icon; name: ar.modelData.name
                                            s: ar.modelData.kind === "app" ? 28 : 24; glyph: ar.modelData.kind === "app" ? "" : ar.modelData.kind === "system" ? "shield" : "gear" }
                                        Column { x: 68; width: parent.width - 68 - 4 * 104 - 8; anchors.verticalCenter: parent.verticalCenter; spacing: 1
                                            Label { width: parent.width; text: ar.modelData.name + (ar.modelData.paused ? "  ·  paused" : ""); elide: Text.ElideRight
                                                font.pixelSize: 13; font.weight: ar.modelData.kind === "app" ? Font.DemiBold : Font.Normal }
                                            Label { visible: ar.modelData.sub !== "" || ar.modelData.kind === "system"; width: parent.width; elide: Text.ElideRight; secondary: true; font.pixelSize: 11
                                                text: [ar.modelData.sub, ar.modelData.kind === "system" ? ar.modelData.user : ""].filter(Boolean).join("  ·  ") } }
                                        Row { anchors.right: parent.right; height: parent.height
                                            Cell { text: win.pct(ar.modelData.cpu); amount: ar.modelData.cpu / 50 }
                                            Cell { text: win.size(ar.modelData.memory); amount: ar.modelData.memory / Math.max(1, win.mem.total || 1) * 6 }
                                            Cell { text: ar.modelData.gpu > 0 ? win.pct(ar.modelData.gpu) : "–"; amount: ar.modelData.gpu / 60; dim: ar.modelData.gpu <= 0 }
                                            Cell { text: ar.modelData.disk > 0 ? win.rate(ar.modelData.disk) : "–"; amount: ar.modelData.disk / 50e6; dim: ar.modelData.disk <= 0 } }
                                        MouseArea { anchors.fill: parent; anchors.leftMargin: ar.modelData.count > 1 ? 26 : 0; acceptedButtons: Qt.LeftButton | Qt.RightButton
                                            onClicked: function (m) {
                                                win.picked = { kind: "app", key: ar.modelData.key }
                                                if (m.button === Qt.RightButton) { var p = mapToItem(win.contentItem, m.x, m.y); win.menuFor = { item: win.itemOf(win.picked), x: p.x, y: p.y } }
                                            }
                                            onDoubleClicked: { var o = Object.assign({}, win.open); o[ar.modelData.key] = !ar.unfolded; win.open = o } }
                                    }
                                    // its processes, unfolded
                                    Repeater {
                                        model: ar.unfolded ? win.rowsOf(ar.modelData.key) : []
                                        Pressable {
                                            required property var modelData
                                            readonly property bool sel: win.picked !== null && win.picked.kind === "proc" && win.picked.pid === modelData.pid
                                            width: ar.width; height: 34; radius: 8
                                            color: sel ? Qt.rgba(win.ink.r, win.ink.g, win.ink.b, 0.18) : (hovered ? Theme.t.hover : "transparent")
                                            Rectangle { x: 44; width: 1; height: parent.height; color: Theme.t.separator }
                                            Label { x: 68; width: parent.width - 68 - 4 * 104 - 8; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; font.pixelSize: 12
                                                text: modelData.name + "   " + modelData.pid + (modelData.paused ? "  ·  paused" : ""); color: Theme.t.text_secondary }
                                            Row { anchors.right: parent.right; height: parent.height
                                                Cell { text: win.pct(modelData.cpu); amount: modelData.cpu / 50 }
                                                Cell { text: win.size(modelData.memory); amount: 0 }
                                                Cell { text: modelData.gpu > 0 ? win.pct(modelData.gpu) : "–"; amount: 0; dim: true }
                                                Cell { text: modelData.disk > 0 ? win.rate(modelData.disk) : "–"; amount: 0; dim: true } }
                                            MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton
                                                onClicked: function (m) {
                                                    win.picked = { kind: "proc", pid: modelData.pid }
                                                    if (m.button === Qt.RightButton) { var p = mapToItem(win.contentItem, m.x, m.y); win.menuFor = { item: win.itemOf(win.picked), x: p.x, y: p.y } }
                                                } }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    Label { visible: win.filter !== "" && win.sections.every(function (s) { return s.rows.length === 0 }); x: 12; topPadding: 20
                        text: "Nothing running is called “" + win.filter + "”."; secondary: true }
                }
            }
            Footer { anchors.bottom: parent.bottom
                summary: (Backend.counts.apps || 0) + " apps  ·  " + (Backend.counts.background || 0) + " in the background  ·  " + (Backend.counts.processes || 0) + " processes  ·  up " + win.duration(Backend.uptime) }
        }

        // ------------------------------------------------------------------------------------------- Processes
        Card {
            id: procCard
            visible: win.view === "procs"
            y: vitals.height + 12; width: parent.width; height: parent.height - y
            readonly property int cols: 7
            Row { id: procHead; x: 8; y: 6; height: 32
                Head { width: procCard.width - 16 - 2 * 80 - 90 - 4 * 104; text: "Name"; key: "name"; alignLeft: true }
                Head { width: 80; text: "Number"; key: "pid" } Head { width: 90; text: "User"; key: "user" }
                Head { text: "Processor"; key: "cpu" } Head { text: "Memory"; key: "memory" } Head { text: "Graphics"; key: "gpu" } Head { text: "Disk"; key: "disk" }
                Head { width: 80; text: "Threads"; key: "threads" } }
            Rectangle { y: 40; width: parent.width; height: 1; color: Theme.t.separator }
            ListView {
                id: procList
                x: 8; y: 44; width: parent.width - 16; height: parent.height - y - 44; clip: true; boundsBehavior: Flickable.StopAtBounds
                model: win.procRows
                reuseItems: true
                delegate: Pressable {
                    required property var modelData
                    required property int index
                    readonly property bool sel: win.picked !== null && win.picked.kind === "proc" && win.picked.pid === modelData.pid
                    width: procList.width; height: 34; radius: 8
                    color: sel ? Qt.rgba(win.ink.r, win.ink.g, win.ink.b, 0.22) : (hovered ? Theme.t.hover : (index % 2 ? (Theme.t.dark ? "#06FFFFFF" : "#06141E28") : "transparent"))
                    Row { x: 12; width: procCard.width - 16 - 2 * 80 - 90 - 4 * 104 - 20; anchors.verticalCenter: parent.verticalCenter; spacing: 8; clip: true
                        Label { text: modelData.name + (modelData.paused ? "  ·  paused" : ""); font.pixelSize: 12 }
                        Label { readonly property string app: win.appNames[modelData.app] || ""
                            visible: app !== "" && app !== modelData.name; text: app; secondary: true; font.pixelSize: 11; anchors.verticalCenter: parent.verticalCenter } }
                    Row { anchors.right: parent.right; height: parent.height
                        Cell { width: 80; text: modelData.pid; dim: true }
                        Item { width: 90; height: parent.height
                            Label { anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter } width: parent.width - 16; horizontalAlignment: Text.AlignRight
                                elide: Text.ElideRight; text: modelData.user; font.pixelSize: 12; color: modelData.mine ? Theme.t.text : Theme.t.text_secondary } }
                        Cell { text: win.pct(modelData.cpu); amount: modelData.cpu / 50 }
                        Cell { text: win.size(modelData.memory); amount: modelData.memory / Math.max(1, win.mem.total || 1) * 6 }
                        Cell { text: modelData.gpu > 0 ? win.pct(modelData.gpu) : "–"; amount: modelData.gpu / 60; dim: modelData.gpu <= 0 }
                        Cell { text: modelData.disk > 0 ? win.rate(modelData.disk) : (modelData.disk < 0 ? "" : "–"); amount: modelData.disk / 50e6; dim: modelData.disk <= 0 }
                        Cell { width: 80; text: modelData.threads; dim: true } }
                    MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton
                        onClicked: function (m) {
                            win.picked = { kind: "proc", pid: modelData.pid }
                            if (m.button === Qt.RightButton) { var p = mapToItem(win.contentItem, m.x, m.y); win.menuFor = { item: win.itemOf(win.picked), x: p.x, y: p.y } }
                        } }
                }
            }
            Footer { anchors.bottom: parent.bottom
                summary: win.procRows.length + (win.everyone ? " processes" : " of yours") + "  ·  " + (Backend.counts.threads || 0) + " threads in all"
                Row { spacing: 2; anchors.verticalCenter: parent.verticalCenter
                    Seg { text: "Yours"; on: !win.everyone; onClicked: win.everyone = false }
                    Seg { text: "Everyone's"; on: win.everyone; onClicked: win.everyone = true } } }
        }

        // ------------------------------------------------------------------------------------------- Startup
        Card {
            id: stCard
            objectName: "startupCard"
            visible: win.view === "startup"
            y: vitals.height + 12; width: parent.width; height: parent.height - y
            function impactName(i) { return i === "high" ? "High" : i === "medium" ? "Medium" : i === "low" ? "Low" : "" }
            function impactInk(i) { return i === "high" ? "#E5484D" : i === "medium" ? "#E8A10C" : "#30A46C" }
            Item { x: 20; y: 14; width: parent.width - 40; height: 46
                Column { width: parent.width - addBtn.width - 20
                    Label { text: "Starts when you sign in"; font.pixelSize: 16; font.weight: Font.DemiBold }
                    Label { width: parent.width; elide: Text.ElideRight; secondary: true; font.pixelSize: 12
                        text: win.st.signin ? "How heavy each was: measured over the first minute after you signed in, " + Qt.formatDateTime(new Date(win.st.signin * 1000), "ddd h:mm") + ". High: over a second of the processor or 3 MB read."
                                             : "How heavy each is shows after the next sign-in (it's measured over the first minute)." } }
                Btn { id: addBtn; anchors { right: parent.right; verticalCenter: parent.verticalCenter } text: "Add an App…"; onClicked: Backend.addStartup() } }
            Row { id: stHead; x: 8; y: 66; height: 32
                Head { width: stCard.width - 16 - 110 - 120 - 210 - 120; text: "Name"; key: ""; alignLeft: true }
                Head { width: 110; text: "Status"; key: "" } Head { width: 120; text: "Impact"; key: "" } Head { width: 210; text: "At sign-in"; key: "" } Head { width: 120; text: "Now"; key: "" } }
            Rectangle { y: 100; width: parent.width; height: 1; color: Theme.t.separator }
            Flickable {
                x: 8; y: 104; width: parent.width - 16; height: parent.height - y - 44; contentHeight: stCol.height; clip: true; boundsBehavior: Flickable.StopAtBounds
                Column {
                    id: stCol
                    width: parent.width
                    Label { visible: win.stRows.length === 0; x: 12; topPadding: 18; width: parent.width - 24; wrapMode: Text.WordWrap; secondary: true
                        text: win.st.error ? win.st.error : "Nothing starts when you sign in besides Huginn itself. Apps you set to start with the computer (Steam's and Discord's own setting, or Add an App) show here." }
                    Repeater {
                        model: win.stRows
                        Pressable {
                            id: sr
                            required property var modelData
                            objectName: "startup_" + modelData.id
                            readonly property bool sel: win.startPicked === modelData.id
                            width: stCol.width; height: 50; radius: 10
                            color: sel ? Qt.rgba(win.ink.r, win.ink.g, win.ink.b, 0.22) : (hovered ? Theme.t.hover : "transparent")
                            border.width: sel ? 1 : 0; border.color: Theme.t.accent
                            Icon { x: 10; anchors.verticalCenter: parent.verticalCenter; icon: sr.modelData.icon; name: sr.modelData.name; s: 30; opacity: sr.modelData.enabled ? 1 : 0.5 }
                            Column { x: 52; width: stCard.width - 16 - 110 - 120 - 210 - 120 - 60; anchors.verticalCenter: parent.verticalCenter; spacing: 1
                                Label { width: parent.width; text: sr.modelData.name; font.pixelSize: 13; font.weight: Font.DemiBold; elide: Text.ElideRight
                                    color: sr.modelData.enabled ? Theme.t.text : Theme.t.text_secondary }
                                Label { width: parent.width; elide: Text.ElideMiddle; font.pixelSize: 11; secondary: true
                                    text: sr.modelData.why || sr.modelData.failed || ((sr.modelData.mine ? "" : "Set up by the system  ·  ") + sr.modelData.exec) } }
                            Row { anchors.right: parent.right; height: parent.height
                                Item { width: 110; height: parent.height
                                    Toggle { anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter } on: sr.modelData.enabled
                                        onToggled: function (v) { Backend.setStartup(sr.modelData.id, v) } } }
                                Item { width: 120; height: parent.height
                                    Rectangle { visible: sr.modelData.enabled && stCard.impactName(sr.modelData.impact) !== ""; anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                                        width: impL.width + 20; height: 22; radius: 11; color: Qt.rgba(Qt.color(stCard.impactInk(sr.modelData.impact)).r, Qt.color(stCard.impactInk(sr.modelData.impact)).g, Qt.color(stCard.impactInk(sr.modelData.impact)).b, 0.18)
                                        Label { id: impL; anchors.centerIn: parent; text: stCard.impactName(sr.modelData.impact); font.pixelSize: 11; font.weight: Font.DemiBold; color: stCard.impactInk(sr.modelData.impact) } }
                                    Label { visible: !sr.modelData.enabled || stCard.impactName(sr.modelData.impact) === ""; anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                                        text: !sr.modelData.enabled ? "Off" : sr.modelData.why ? "Won't start" : "Not measured"; secondary: true; font.pixelSize: 12 } }
                                Item { width: 210; height: parent.height
                                    Label { anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter } font.family: Theme.t.fontMono; font.pixelSize: 12
                                        color: Theme.t.text_secondary
                                        text: sr.modelData.cpu >= 0 && sr.modelData.enabled ? sr.modelData.cpu.toFixed(1) + " s  ·  " + win.size(Math.max(0, sr.modelData.disk)) + " read" : "–" } }
                                Item { width: 120; height: parent.height
                                    Label { anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter } font.family: Theme.t.fontMono; font.pixelSize: 12
                                        color: sr.modelData.running ? Theme.t.text : Theme.t.text_secondary
                                        text: sr.modelData.running ? win.size(sr.modelData.memoryNow) : "Not running" } } }
                            MouseArea { anchors.fill: parent; z: -1; acceptedButtons: Qt.LeftButton | Qt.RightButton
                                onClicked: function (m) {
                                    win.startPicked = sr.modelData.id
                                    if (m.button === Qt.RightButton) { var p = mapToItem(win.contentItem, m.x, m.y); win.startMenu = { e: sr.modelData, x: p.x, y: p.y } }
                                } }
                        }
                    }
                }
            }
            Footer { anchors.bottom: parent.bottom; startup: true
                summary: win.stRows.filter(function (e) { return e.enabled }).length + " of " + win.stRows.length + " on" +
                         (win.stRows.some(function (e) { return e.enabled && e.impact === "high" }) ? "  ·  turning off a High one makes signing in quicker" : "") }
        }

        // ------------------------------------------------------------------------------------------- Performance
        Card {
            id: perfCard
            visible: win.view === "perf"
            y: vitals.height + 12; width: parent.width; height: parent.height - y
            Flickable {
                anchors { fill: parent; margins: 20 }
                contentHeight: perfCol.height; clip: true; boundsBehavior: Flickable.StopAtBounds
                Column {
                    id: perfCol
                    width: parent.width; spacing: 18
                    // the heading: what, and its make
                    Item { width: parent.width; height: 34
                        Label { text: ({ cpu: "Processor", mem: "Memory", gpu: "Graphics card", disk: "Disks", net: "Network" })[win.perf] || ""; font.pixelSize: 24; font.weight: Font.Light }
                        Label { anchors { right: parent.right; verticalCenter: parent.verticalCenter } secondary: true; font.pixelSize: 13
                            text: win.perf === "cpu" ? (win.cpu.model || "") : win.perf === "gpu" ? (win.gpu.name || "") : win.perf === "mem" ? win.gb(win.mem.total || 0) + " in all" : "" } }
                    // the last two minutes: what's drawn named above it
                    Column {
                        width: parent.width; spacing: 6
                        readonly property bool two: win.perf === "disk" || win.perf === "net"
                        readonly property var first: win.perf === "cpu" ? (win.hist.cpu || []) : win.perf === "mem" ? (win.hist.mem || []) : win.perf === "gpu" ? (win.hist.gpu || []) : win.perf === "disk" ? (win.hist.read || []) : (win.hist.down || [])
                        readonly property var second: win.perf === "disk" ? (win.hist.write || []) : win.perf === "net" ? (win.hist.up || []) : []
                        readonly property real peak: Math.max.apply(null, [1].concat(first).concat(second))
                        Item { width: parent.width; height: 16
                            Label { text: "The last two minutes"; secondary: true; font.pixelSize: 11 }
                            Row { anchors.right: parent.right; spacing: 14
                                Row { spacing: 6
                                    Rectangle { width: 8; height: 8; radius: 4; color: win.ink; anchors.verticalCenter: parent.verticalCenter }
                                    Label { text: ({ cpu: "In use", mem: "In use", gpu: "Busy", disk: "Read", net: "Down" })[win.perf] || ""; secondary: true; font.pixelSize: 11 } }
                                Row { visible: parent.parent.parent.two; spacing: 6
                                    Rectangle { width: 8; height: 8; radius: 4; color: win.ink2; anchors.verticalCenter: parent.verticalCenter }
                                    Label { text: win.perf === "disk" ? "Write" : "Up"; secondary: true; font.pixelSize: 11 } }
                                Label { text: parent.parent.parent.two ? "top of the graph " + win.rate(parent.parent.parent.peak) : "top of the graph 100%"; secondary: true; font.pixelSize: 11 } } }
                        Rectangle { width: parent.width; height: 170; radius: 12; color: Theme.t.dark ? "#14000000" : "#0A141E28"
                            Graph { anchors { fill: parent; margins: 8 } first: parent.parent.first; second: parent.parent.second; unit: !parent.parent.two } } }

                    // ---- processor
                    Flow { visible: win.perf === "cpu"; width: parent.width; spacing: 18
                        Stat { name: "In use"; value: win.pct((win.cpu.load || 0) * 100); dot: win.ink }
                        Stat { name: "Speed now"; value: win.cpu.ghz ? win.cpu.ghz + " GHz" : "–" }
                        Stat { name: "Top speed"; value: win.cpu.maxGhz ? win.cpu.maxGhz + " GHz" : "–" }
                        Stat { name: "Temperature"; value: win.cpu.temp ? win.cpu.temp + " °C" : "–" }
                        Stat { name: "Threads"; value: String(win.cpu.count || 0) }
                        Stat { name: "Processes"; value: (Backend.counts.processes || 0) + "  ·  " + (Backend.counts.threads || 0) + " threads" }
                        Stat { name: "Up for"; value: win.duration(Backend.uptime) } }
                    Column { visible: win.perf === "cpu"; width: parent.width; spacing: 8
                        Label { text: "Each thread of the processor"; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold }
                        Grid {
                            id: coreGrid
                            readonly property int n: (win.cpu.cores || []).length
                            columns: n <= 16 ? Math.max(1, n) : Math.min(16, Math.ceil(n / Math.ceil(n / 16))); spacing: 8
                            Repeater { model: win.cpu.cores || []
                                Item { required property var modelData; required property int index
                                    width: (perfCol.width - (coreGrid.columns - 1) * 8) / coreGrid.columns; height: 58
                                    Rectangle { anchors.fill: parent; radius: 9; color: Theme.t.hover }
                                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: Math.max(3, parent.height * modelData); radius: Math.min(9, height / 2)
                                        color: Qt.rgba(win.ink.r, win.ink.g, win.ink.b, 0.35 + 0.4 * modelData) }
                                    Label { x: 8; y: 6; text: index; secondary: true; font.pixelSize: 10 }
                                    Label { anchors { right: parent.right; rightMargin: 8; bottom: parent.bottom; bottomMargin: 6 } text: Math.round(modelData * 100) + "%"; font.pixelSize: 12
                                        font.family: Theme.t.fontMono } } } } }

                    Top { visible: win.perf === "cpu" && list.length > 0; by: "cpu"; title: "Using the most" }

                    // ---- memory
                    Column { visible: win.perf === "mem"; width: parent.width; spacing: 10
                        readonly property real t: Math.max(1, win.mem.total || 1)
                        Label { text: "What it holds"; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold }
                        Row { width: parent.width; height: 26
                            Rectangle { width: parent.width * (win.mem.used || 0) / parent.parent.t; height: parent.height; radius: 6; color: win.ink }
                            Rectangle { width: parent.width * Math.min(win.mem.cached || 0, (win.mem.available || 0)) / parent.parent.t; height: parent.height; color: Qt.rgba(win.ink.r, win.ink.g, win.ink.b, 0.38) }
                            Rectangle { width: Math.max(0, parent.width - parent.children[0].width - parent.children[1].width); height: parent.height; radius: 6; color: Theme.t.hover } }
                        Flow { width: parent.width; spacing: 18
                            Stat { name: "In use by programs"; value: win.gb(win.mem.used || 0); dot: win.ink }
                            Stat { name: "Kept as a cache (given back when needed)"; width: 250; value: win.gb(win.mem.cached || 0); dot: Qt.rgba(win.ink.r, win.ink.g, win.ink.b, 0.38) }
                            Stat { name: "Free"; value: win.gb(win.mem.free || 0); dot: Theme.t.hover }
                            Stat { name: "Available"; value: win.gb(win.mem.available || 0) }
                            Stat { name: win.mem.zram ? "Compressed swap (zram)" : "Swap"; width: 210; value: win.mem.swapTotal ? win.gb(win.mem.swapUsed || 0) + " of " + win.gb(win.mem.swapTotal) : "None" } }
                        Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                            text: "Memory kept as a cache holds files read recently so they open fast again; programs get it the moment they need it. " +
                                  (win.mem.zram ? "When memory runs short, what's been unused longest is compressed in memory first, before anything is stopped." : "") } }

                    Top { visible: win.perf === "mem" && list.length > 0; by: "memory"; title: "Using the most" }

                    // ---- graphics card
                    Column { visible: win.perf === "gpu"; width: parent.width; spacing: 14
                        Label { visible: !win.hasGpu; width: parent.width; wrapMode: Text.WordWrap; secondary: true
                            text: "This graphics card doesn't give readings here (AMD cards do, and NVIDIA's with its driver). Which app uses it is in the Graphics column of Apps." }
                        Flow { visible: win.hasGpu; width: parent.width; spacing: 18
                            Stat { name: "Busy"; value: (win.gpu.load || 0) + "%"; dot: win.ink }
                            Stat { name: "Video memory"; value: win.gpu.memTotal ? win.gpu.memUsed + " of " + win.gpu.memTotal + " GB" : "–" }
                            Stat { name: "Temperature"; value: win.gpu.temp !== undefined ? win.gpu.temp + " °C" + (win.gpu.hot ? "  (hottest " + win.gpu.hot + ")" : "") : "–"; width: 210 }
                            Stat { name: "Power"; value: win.gpu.watts !== undefined ? win.gpu.watts + " W" + (win.gpu.capWatts ? " of " + win.gpu.capWatts : "") : "–" }
                            Stat { name: "Clock"; value: win.gpu.coreMhz ? win.gpu.coreMhz + " MHz" : (win.gpu.ghz ? win.gpu.ghz + " GHz" : "–") }
                            Stat { name: "Memory clock"; value: win.gpu.memMhz ? win.gpu.memMhz + " MHz" : "–" }
                            Stat { name: "Fan"; value: win.gpu.fan !== undefined ? win.gpu.fan + " RPM" + (win.gpu.fanPercent !== undefined ? "  ·  " + win.gpu.fanPercent + "%" : "") : "–" } }
                        Column { visible: win.hasGpu && !!win.gpu.memTotal; width: parent.width; spacing: 6
                            Label { text: "Video memory"; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold }
                            Meter { width: parent.width; height: 10; radius: 5; value: (win.gpu.memUsed || 0) / Math.max(0.1, win.gpu.memTotal || 1) } }
                        Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                            text: "Settings › Graphics has the card's performance level and its power limit." } }

                    Top { visible: win.perf === "gpu" && list.length > 0; by: "gpu"; title: "Using it the most (your apps)" }

                    // ---- disks
                    Column { visible: win.perf === "disk"; width: parent.width; spacing: 12
                        Repeater { model: Backend.disks
                            Rectangle { required property var modelData; width: perfCol.width; height: dk.height + 28; radius: 12; color: Theme.t.hover
                                Column { id: dk; x: 16; y: 14; width: parent.width - 32; spacing: 10
                                    Item { width: parent.width; height: 22
                                        Row { spacing: 8
                                            Glyph { name: "drive"; size: 16; anchors.verticalCenter: parent.verticalCenter }
                                            Label { text: modelData.model || modelData.name; font.pixelSize: 14; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
                                            Label { text: modelData.kind + "  ·  " + win.size(modelData.size).replace(".0 ", " ") + "  ·  " + modelData.name; secondary: true; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter } }
                                        Label { anchors.right: parent.right; text: "Busy " + Math.round(modelData.busy * 100) + "%"; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter } }
                                    Row { spacing: 28
                                        Stat { name: "Reading"; value: win.rate(modelData.read); dot: win.ink }
                                        Stat { name: "Writing"; value: win.rate(modelData.write); dot: win.ink2 } }
                                    Repeater { model: modelData.parts
                                        Column { required property var modelData; width: dk.width; spacing: 4
                                            Item { width: parent.width; height: 16
                                                Label { text: modelData.where === "/" ? "The system ( / )" : modelData.where; font.pixelSize: 12 }
                                                Label { anchors.right: parent.right; text: win.gb(modelData.total - modelData.used) + " free of " + win.gb(modelData.total); secondary: true; font.pixelSize: 12 } }
                                            Meter { width: parent.width; value: modelData.used / Math.max(1, modelData.total); fill: modelData.used / modelData.total > 0.9 ? Theme.t.danger : Theme.t.accent } } } } } }
                        Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                            text: "Settings › Storage shows what each app and game takes, and takes them off." } }

                    Top { visible: win.perf === "disk" && list.length > 0; by: "disk"; title: "Reading and writing the most (your apps)" }

                    // ---- network
                    Column { visible: win.perf === "net"; width: parent.width; spacing: 12
                        Repeater { model: Backend.nets
                            Rectangle { required property var modelData; width: perfCol.width; height: 92; radius: 12; color: Theme.t.hover; opacity: modelData.up_ ? 1 : 0.6
                                Row { x: 16; y: 14; spacing: 8
                                    Glyph { name: modelData.kind === "Wi‑Fi" ? "wifi" : modelData.kind === "VPN" ? "lock" : "ethernet"; size: 16; anchors.verticalCenter: parent.verticalCenter }
                                    Label { text: modelData.kind; font.pixelSize: 14; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
                                    Label { text: modelData.name + (modelData.address ? "  ·  " + modelData.address : "") + (modelData.up_ ? "" : "  ·  not connected"); secondary: true; font.pixelSize: 12
                                        anchors.verticalCenter: parent.verticalCenter } }
                                Row { x: 16; y: 44; spacing: 28
                                    Stat { name: "Down"; value: win.rate(modelData.down); dot: win.ink }
                                    Stat { name: "Up"; value: win.rate(modelData.up); dot: win.ink2 }
                                    Stat { name: "Since it started"; width: 240; value: "↓ " + win.size(modelData.rx) + "   ↑ " + win.size(modelData.tx) } } } }
                        Label { visible: (Backend.nets || []).length === 0; text: "No network connections."; secondary: true } }
                }
            }
        }
    }

    // ---------------------------------------------------------------------------------------------------- the footer
    component Footer: Rectangle {
        property string summary
        property bool startup: false
        default property alias extra: extraRow.data
        width: parent ? parent.width : 400; height: 44; color: "transparent"
        Rectangle { width: parent.width; height: 1; color: Theme.t.separator }
        Label { x: 16; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 420; elide: Text.ElideRight; font.pixelSize: 12
            color: win.notice ? Theme.t.danger : Theme.t.text_secondary; text: win.notice || parent.summary }
        Row { id: extraRow; anchors { right: actions.left; rightMargin: 12; verticalCenter: parent.verticalCenter } height: 30 }
        Row { id: actions; anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } spacing: 6
            Btn { visible: parent.parent.startup && win.stPicked !== null; height: 28; text: "More…"
                onClicked: { var p = mapToItem(win.contentItem, 0, -8); win.startMenu = { e: win.stPicked, x: p.x - 120, y: p.y - 120 } } }
            Btn { visible: parent.parent.startup && win.stPicked !== null; height: 28; primary: win.stPicked !== null && !win.stPicked.enabled
                text: win.stPicked && win.stPicked.enabled ? "Turn Off" : "Turn On"; objectName: "startupSwitch"
                onClicked: Backend.setStartup(win.stPicked.id, !win.stPicked.enabled) }
            Btn { visible: !parent.parent.startup && win.current !== null; height: 28; text: "More…"
                onClicked: { var p = mapToItem(win.contentItem, 0, -8); win.menuFor = { item: win.current, x: p.x - 120, y: p.y - 230 } } }
            Btn { visible: !parent.parent.startup && win.current !== null; height: 28; danger: true; objectName: "endButton"
                text: win.current && win.current.kind === "app" ? "End App" : "End Process"
                onClicked: win.act("end", win.current) } }
    }

    // ---------------------------------------------------------------------------------------------------- menu, sheets
    MouseArea { visible: win.menuFor !== null; anchors.fill: parent; z: 19; acceptedButtons: Qt.LeftButton | Qt.RightButton; onClicked: win.menuFor = null }
    Rectangle {
        objectName: "rowMenu"
        visible: win.menuFor !== null; z: 20; width: 240; height: menu.height + 10; radius: Theme.t.radiusCard; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        x: win.menuFor ? Math.max(8, Math.min(win.menuFor.x, parent.width - width - 8)) : 0; y: win.menuFor ? Math.max(8, Math.min(win.menuFor.y, parent.height - height - 8)) : 0
        readonly property var it: win.menuFor ? win.menuFor.item : null
        Column { id: menu; x: 5; y: 5; width: parent.width - 10
            Repeater {
                model: parent.parent.it ? [[parent.parent.it.kind === "app" ? "End app" : "End process", "x", "end"], [parent.parent.it.paused ? "Resume" : "Pause", parent.parent.it.paused ? "play" : "pause", "pause"],
                                           ["Run in the background (lower priority)", "down", "slow"], ["Normal priority", "up", "normal"],
                                           ["Show program location", "folder", "where"], ["Details", "info", "props"], ["", "", ""], ["Force stop", "trash", "force"]] : []
                Item { required property var modelData; width: menu.width; height: modelData[0] ? 30 : 9
                    Rectangle { visible: !modelData[0]; y: 4; width: parent.width; height: 1; color: Theme.t.separator }
                    Pressable { visible: modelData[0] !== ""; anchors.fill: parent; radius: Theme.t.radiusControl
                        onClicked: { var it = win.menuFor.item, a = modelData[2]; win.act(a, it); win.menuFor = null }   // (the menu last: this entry goes with it)
                        Glyph { x: 8; anchors.verticalCenter: parent.verticalCenter; name: modelData[1]; size: 14; ink: modelData[2] === "force" ? Theme.t.danger : Theme.t.icon }
                        Label { x: 32; width: parent.width - 40; anchors.verticalCenter: parent.verticalCenter; text: modelData[0]; elide: Text.ElideRight; color: modelData[2] === "force" ? Theme.t.danger : Theme.t.text } } } } }
    }
    MouseArea { visible: win.startMenu !== null; anchors.fill: parent; z: 19; acceptedButtons: Qt.LeftButton | Qt.RightButton; onClicked: win.startMenu = null }
    Rectangle {
        objectName: "startupMenu"
        visible: win.startMenu !== null; z: 20; width: 240; height: smenu.height + 10; radius: Theme.t.radiusCard; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        x: win.startMenu ? Math.max(8, Math.min(win.startMenu.x, parent.width - width - 8)) : 0; y: win.startMenu ? Math.max(8, Math.min(win.startMenu.y, parent.height - height - 8)) : 0
        readonly property var e: win.startMenu ? win.startMenu.e : null
        Column { id: smenu; x: 5; y: 5; width: parent.width - 10
            Repeater {
                model: parent.parent.e ? [[parent.parent.e.enabled ? "Turn off" : "Turn on", parent.parent.e.enabled ? "x" : "check", "switch"], ["Details", "info", "props"],
                                          ["Show where it's set up", "folder", "where"]].concat(parent.parent.e.mine && !parent.parent.e.system ? [["", "", ""], ["Remove from sign-in", "trash", "remove"]] : []) : []
                Item { required property var modelData; width: smenu.width; height: modelData[0] ? 30 : 9
                    Rectangle { visible: !modelData[0]; y: 4; width: parent.width; height: 1; color: Theme.t.separator }
                    Pressable { visible: modelData[0] !== ""; anchors.fill: parent; radius: Theme.t.radiusControl
                        onClicked: {
                            var e = win.startMenu.e, a = modelData[2]
                            if (a === "switch") Backend.setStartup(e.id, !e.enabled)
                            else if (a === "where") Backend.showFile(e.path)
                            else if (a === "remove") Backend.removeStartup(e.id)
                            else win.props = { title: e.name, list: [{ name: "Runs", value: e.exec }, { name: "Set up in", value: e.path },
                                                                     { name: "Status", value: e.why ? e.why : e.enabled ? "On" : "Off" },
                                                                     { name: "At sign-in", value: e.cpu >= 0 ? e.cpu.toFixed(2) + " s of the processor, " + win.size(Math.max(0, e.disk)) + " read" : "Not measured" },
                                                                     { name: "Now", value: e.running ? win.size(e.memoryNow) + " of memory" : "Not running" }] }
                            win.startMenu = null                  // last: this entry goes with the menu
                        }
                        Glyph { x: 8; anchors.verticalCenter: parent.verticalCenter; name: modelData[1]; size: 14; ink: modelData[2] === "remove" ? Theme.t.danger : Theme.t.icon }
                        Label { x: 32; width: parent.width - 40; anchors.verticalCenter: parent.verticalCenter; text: modelData[0]; elide: Text.ElideRight; color: modelData[2] === "remove" ? Theme.t.danger : Theme.t.text } } } } }
    }
    Rectangle { visible: win.asking !== null || win.props !== null; anchors.fill: parent; color: "#66000000"; z: 30; MouseArea { anchors.fill: parent; onClicked: { win.props = null; win.asking = null } } }
    Rectangle {
        objectName: "endSheet"
        visible: win.asking !== null; z: 31; anchors.centerIn: parent; width: 420; height: 184; radius: Theme.t.radiusTile; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        readonly property var it: win.asking ? win.asking.item : null
        readonly property bool force: !!(win.asking && win.asking.force)
        Label { x: 22; y: 20; width: parent.width - 44; elide: Text.ElideRight; font.pixelSize: 16; font.weight: Font.DemiBold
            text: parent.it ? (parent.force ? "Force “" + parent.it.name + "” to stop?" : "End “" + parent.it.name + "”?") : "" }
        Label { x: 22; y: 52; width: parent.width - 44; wrapMode: Text.WordWrap; secondary: true; lineHeight: 1.3
            text: parent.force ? "It stops at once, with no chance to save. Use this only when End didn't work."
                               : (parent.it && parent.it.kind === "app" && parent.it.pids.length > 1 ? "The app and its " + (parent.it.pids.length - 1) + " helpers are asked to close. " : "It's asked to close. ") + "Anything not saved in it may be lost." }
        Row { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 20 } spacing: 8
            Btn { text: "Cancel"; onClicked: win.asking = null }
            Btn { text: parent.parent.force ? "Force Stop" : "End"; danger: true
                onClicked: { var a = win.asking; a.force ? Backend.force(a.item.pids) : Backend.end(a.item.pids); win.asking = null; win.picked = null } } }
    }
    Rectangle {
        visible: win.props !== null; z: 31; anchors.centerIn: parent; width: 520; height: plist.height + 110; radius: Theme.t.radiusTile; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
        Label { x: 22; y: 20; width: parent.width - 44; elide: Text.ElideRight; text: win.props ? win.props.title : ""; font.pixelSize: 16; font.weight: Font.DemiBold }
        Column { id: plist; x: 22; y: 54; width: parent.width - 44
            Repeater { model: win.props ? win.props.list : []
                Item { required property var modelData; width: plist.width; height: Math.max(30, v.height + 12)
                    Label { y: 6; text: modelData.name; secondary: true } Label { id: v; x: 150; y: 6; width: parent.width - 150; text: modelData.value; wrapMode: Text.WrapAnywhere; font.pixelSize: 12 } } } }
        Btn { anchors { right: parent.right; rightMargin: 22; bottom: parent.bottom; bottomMargin: 18 } text: "Done"; primary: true; onClicked: win.props = null }
    }
}
