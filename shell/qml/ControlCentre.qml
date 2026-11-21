import QtQuick

// The control centre: slides out on the right, as tall as what's in it. Everything in it is the computer's real state
// (Status, from huginn_system.py). From the top: you, with Screenshot, Lock and Settings; Wi‑Fi, Bluetooth and the
// wired network with their switches; Do Not Disturb, Dark and night light; the screen's brightness and the sound;
// what's playing (Live); apps running in the background with no window (Discord, Steam: click for its window,
// right-click or × to quit); the realm; how the app menus open; and the notifications that came. Anything with more to it
// opens its page of Settings.
Glass {
    id: cc
    popup: true; radius: 22; width: 344
    // as tall as what's in it (the shell caps it at the screen and it scrolls beyond)
    implicitHeight: col.height + 28
    readonly property color accent: Theme.t.accent
    readonly property color tileOn: Qt.rgba(accent.r, accent.g, accent.b, Theme.t.dark ? 0.26 : 0.18)
    signal done()                          // something in it was chosen that takes you elsewhere: the shell closes it
    signal saverWanted()                   // the Screen saver tile
    property bool editTiles: false         // the quick tiles are being arranged

    component Block: Rectangle { color: Theme.t.hover; radius: 16; border.width: 1; border.color: Theme.t.line }
    component Dot: Rectangle { property bool on: true; property string glyph: ""; width: 30; height: 30; radius: 15
        color: on ? Theme.t.accent : (Theme.t.dark ? "#33FFFFFF" : "#26141E28")
        Behavior on color { ColorAnimation { duration: 160 } }
        Glyph { anchors.centerIn: parent; visible: parent.glyph !== ""; name: parent.glyph; size: 15; ink: parent.on ? Theme.t.onAccent : Theme.t.text } }
    component Round: Rectangle {   // a small round button in the header
        id: rb
        property string glyph: ""; property string tip: ""
        signal clicked()
        width: 34; height: 34; radius: 17; color: rh.containsMouse ? Theme.t.hover : "transparent"; border.width: 1; border.color: rh.containsMouse ? Theme.t.line : "transparent"
        Glyph { anchors.centerIn: parent; name: rb.glyph; size: 15 }
        MouseArea { id: rh; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: rb.clicked() }
        Rectangle { visible: rh.containsMouse && rb.tip !== ""; anchors { top: parent.bottom; topMargin: 4; horizontalCenter: parent.horizontalCenter }
            width: tipL.width + 14; height: 22; radius: 7; color: Theme.t.dark ? "#E61A1E23" : "#F2FFFFFF"; z: 5
            Label { id: tipL; anchors.centerIn: parent; text: rb.tip; font.pixelSize: 11 } }
    }
    // A connection: its switch (the dot) and what it's connected to; the words open its page of Settings.
    component Conn: Item {
        id: conn
        property string title; property string sub; property bool on: true; property string glyph: ""; property string page: ""
        signal toggled(bool on)
        width: parent ? parent.width : 140; height: 32
        Dot { id: dot; on: conn.on; glyph: conn.glyph; anchors.verticalCenter: parent.verticalCenter
            MouseArea { anchors.fill: parent; anchors.margins: -4; cursorShape: Qt.PointingHandCursor; onClicked: conn.toggled(!conn.on) } }
        Column { x: 40; width: parent.width - 40; anchors.verticalCenter: parent.verticalCenter
            Label { text: conn.title; font.weight: Font.DemiBold; font.pixelSize: 13 }
            Label { text: conn.sub; secondary: true; font.pixelSize: 11; width: parent.width; elide: Text.ElideRight } }
        MouseArea { x: 40; width: parent.width - 40; height: parent.height; cursorShape: Qt.PointingHandCursor; onClicked: Status.openSettings(conn.page) }
    }
    // A switch of its own: a wide one (a dot and its name) or, two to a row, a square one (the dot over its name)
    component QuickTile: Block {
        id: tg
        property string label; property bool on: false; property string glyph: ""; property bool square: false
        signal clicked()
        width: 153; height: square ? 76 : 52
        color: on ? cc.tileOn : (th.containsMouse ? Qt.lighter(Theme.t.hover, 1.25) : Theme.t.hover)
        Behavior on color { ColorAnimation { duration: 160 } }
        Dot { on: tg.on; glyph: tg.glyph; x: tg.square ? (tg.width - width) / 2 : 12; y: tg.square ? 9 : (tg.height - height) / 2 }
        Label { text: tg.label; font.weight: Font.DemiBold; font.pixelSize: tg.square ? 10 : 12; elide: Text.ElideRight
            wrapMode: tg.square ? Text.WordWrap : Text.NoWrap; maximumLineCount: tg.square ? 2 : 1; lineHeight: tg.square ? 0.92 : 1
            x: tg.square ? 3 : 52; width: tg.square ? tg.width - 6 : tg.width - 60; horizontalAlignment: tg.square ? Text.AlignHCenter : Text.AlignLeft
            y: tg.square ? (lineCount > 1 ? 43 : 50) : (tg.height - height) / 2 }
        MouseArea { id: th; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: tg.clicked() }
    }
    component Slider: Item {
        id: sl
        property string title; property real value; property string glyph: ""; property string page: ""
        signal moved(real v)
        signal glyphClicked()
        width: parent ? parent.width : 300; height: 54
        Label { x: 2; text: sl.title; font.pixelSize: 12; font.weight: Font.DemiBold }
        Label { anchors.right: parent.right; text: Math.round(sl.value * 100) + "%"; secondary: true; font.pixelSize: 11 }
        Rectangle {
            id: track; y: 22; width: parent.width; height: 30; radius: 15; color: Theme.t.dark ? "#2EFFFFFF" : "#24141E28"
            Rectangle { width: Math.max(30, parent.width * sl.value); height: parent.height; radius: 15; color: Theme.t.dark ? "#F2FFFFFF" : "#FFFFFF"
                border.width: Theme.t.dark ? 0 : 1; border.color: Theme.t.line
                Behavior on width { enabled: !drag.pressed; NumberAnimation { duration: 120 } } }
            Glyph { x: 8; anchors.verticalCenter: parent.verticalCenter; visible: sl.glyph !== ""; name: sl.glyph; size: 14; ink: "#1A1E23"
                MouseArea { anchors.fill: parent; anchors.margins: -6; cursorShape: Qt.PointingHandCursor; onClicked: sl.glyphClicked() } }
            MouseArea { id: drag; anchors.fill: parent; anchors.leftMargin: 30
                function to(m) { sl.moved(Math.max(0, Math.min(1, (m.x + 30) / track.width))) }
                onPositionChanged: function (m) { if (pressed) to(m) } onPressed: function (m) { to(m) } }
        }
    }
    // the notifications' history (Settings › Notifications › Keep a history): the last week, read when it's opened
    property bool historyOpen: false
    property var history: []
    readonly property bool keepsHistory: Settings.notifHistory !== false && Settings.notifHistory !== "false"
    onVisibleChanged: if (!visible) historyOpen = false
    // each app playing sound, with its own volume (under Sound): read every second and a half while this is open
    property bool appsOpen: false
    readonly property var appLevels: Status.appVolumes || []
    function appOf(v) {
        var a = Apps.all || [], want = [(v.app || "").toLowerCase(), (v.binary || "").toLowerCase(), (v.icon || "").toLowerCase()]
        for (var i = 0; i < a.length; i++) {
            var names = [(a[i].name || "").toLowerCase(), (a[i].id || "").toLowerCase(), (a[i].wm || "").toLowerCase()]
            for (var k = 0; k < want.length; k++) if (want[k] && names.indexOf(want[k]) >= 0) return a[i]
        }
        return null
    }
    Timer { interval: 1500; repeat: true; triggeredOnStart: true; running: cc.visible && cc.opacity > 0.5; onTriggered: Status.loadAppVolumes() }
    onAppLevelsChanged: if (appLevels.length === 0) appsOpen = false
    readonly property var net: Status.network
    readonly property var levels: Status.levels
    // what's running in the background: apps with a tray icon (Steam, Discord: their icon, their own menu), then apps
    // still running with no window (Mail watching the inbox), then tray icons of programs that aren't installed apps
    readonly property var background: {
        var wins = {}, all = Status.windows || []
        for (var i = 0; i < all.length; i++) if (all[i].name) wins[all[i].name] = true
        var apps = Apps.all || [], byName = {}
        for (var a = 0; a < apps.length; a++) byName[apps[a].name] = apps[a]
        var out = [], seen = {}, tray = Tray.items || []
        for (var t = 0; t < tray.length; t++) {
            var app = tray[t].app && byName[tray[t].app] ? byName[tray[t].app] : null
            var name = app ? app.name : (tray[t].title || "A program")
            if (seen[name]) continue
            seen[name] = true
            out.push({ name: name, app: app, tray: tray[t], windowed: !!wins[name] })
        }
        var run = Apps.running || []
        for (var j = 0; j < run.length; j++) {
            if (wins[run[j]] || seen[run[j]]) continue
            var b = byName[run[j]]
            if (b && !b.web) { out.push({ name: b.name, app: b, tray: null, windowed: false }); seen[b.name] = true }
        }
        return out
    }
    property var bgMenu: null              // {row, x, y, items}: the menu of one of them (its own, from its tray icon, then ours)
    function openRow(r) {
        if (r.tray && !r.tray.isMenu) { cc.done(); Tray.activate(r.tray.key, 0, 0) }
        else if (r.app) { cc.done(); Apps.launch(r.app.exec) }
    }
    readonly property var playing: {
        var all = [Live.main].concat(Live.bubbles || [])
        for (var i = 0; i < all.length; i++) if (all[i] && String(all[i].id || "").indexOf("mpris:") === 0) return all[i]
        return null
    }
    function hello() {
        var h = new Date().getHours(), first = (Me.name || "").trim().split(/\s+/)[0]
        var hi = h >= 5 && h < 12 ? "Good morning" : h >= 12 && h < 17 ? "Good afternoon" : h >= 17 && h < 23 ? "Good evening" : "Hello"
        return first ? hi + ", " + first : hi
    }

    MouseArea { visible: cc.bgMenu !== null; anchors.fill: parent; z: 9; acceptedButtons: Qt.AllButtons; onClicked: cc.bgMenu = null }
    Rectangle {
        objectName: "backgroundMenu"
        visible: cc.bgMenu !== null; z: 10; width: 230; height: bgMenuCol.height + 10; radius: 12
        color: Theme.t.dark ? "#F21E2228" : "#FAFFFFFF"; border.width: 1; border.color: Theme.t.line
        x: cc.bgMenu ? Math.max(8, Math.min(cc.bgMenu.x, cc.width - width - 8)) : 0; y: cc.bgMenu ? Math.max(8, Math.min(cc.bgMenu.y, cc.height - height - 8)) : 0
        // its tray menu's entries (one level of submenu shown in place, indented), then Open, Quit and Force Quit
        readonly property var entries: {
            if (!cc.bgMenu) return []
            var out = [], own = cc.bgMenu.items || [], r = cc.bgMenu.row
            for (var i = 0; i < own.length; i++) {
                var e = own[i]
                if (e.separator) { out.push({ kind: "sep" }); continue }
                if (e.children.length) {
                    out.push({ kind: "head", label: e.label })
                    for (var j = 0; j < e.children.length; j++) if (!e.children[j].separator)
                        out.push({ kind: "tray", id: e.children[j].id, label: e.children[j].label, enabled: e.children[j].enabled, check: e.children[j].check, checked: e.children[j].checked, indent: true })
                } else out.push({ kind: "tray", id: e.id, label: e.label, enabled: e.enabled, check: e.check, checked: e.checked, indent: false })
            }
            if (r.app) {
                if (out.length) out.push({ kind: "sep" })
                out.push({ kind: "ours", what: "open", label: "Open " + r.name, glyph: "window" })
                out.push({ kind: "ours", what: "quit", label: "Quit " + r.name, glyph: "x" })
                out.push({ kind: "ours", what: "force", label: "Force Quit", glyph: "trash" })
            } else if (!out.length && r.tray) out.push({ kind: "ours", what: "activate", label: "Open", glyph: "window" })
            return out
        }
        Column { id: bgMenuCol; x: 5; y: 5; width: parent.width - 10
            Repeater {
                model: parent.parent.entries
                Item { required property var modelData; width: bgMenuCol.width; height: modelData.kind === "sep" ? 9 : modelData.kind === "head" ? 24 : 32
                    Rectangle { visible: modelData.kind === "sep"; y: 4; width: parent.width; height: 1; color: Theme.t.line }
                    Label { visible: modelData.kind === "head"; x: 10; anchors.verticalCenter: parent.verticalCenter; text: modelData.label || ""; secondary: true; font.pixelSize: 11 }
                    Rectangle { visible: modelData.kind === "tray" || modelData.kind === "ours"; anchors.fill: parent; radius: 8
                        color: mh.containsMouse && modelData.enabled !== false ? Theme.t.hover : "transparent"
                        Glyph { visible: modelData.kind === "ours" || (modelData.check && modelData.checked); x: modelData.indent ? 18 : 8; anchors.verticalCenter: parent.verticalCenter
                            name: modelData.kind === "ours" ? modelData.glyph : "check"; size: 14; ink: modelData.what === "force" ? Theme.t.danger : Theme.t.text }
                        Label { x: (modelData.indent ? 18 : 8) + (modelData.kind === "ours" || modelData.check ? 24 : 2); width: parent.width - x - 8; anchors.verticalCenter: parent.verticalCenter
                            text: modelData.label || ""; font.pixelSize: 13; elide: Text.ElideRight; opacity: modelData.enabled === false ? 0.45 : 1
                            color: modelData.what === "force" ? Theme.t.danger : Theme.t.text }
                        MouseArea { id: mh; anchors.fill: parent; hoverEnabled: true; enabled: modelData.enabled !== false; cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                var r = cc.bgMenu.row, e = modelData
                                if (e.kind === "tray") Tray.click(r.tray.key, e.id)
                                else if (e.what === "open") { Apps.launch(r.app.exec); cc.done() }
                                else if (e.what === "activate") { Tray.activate(r.tray.key, 0, 0); cc.done() }
                                else Apps.quit(r.name, e.what === "force")
                                cc.bgMenu = null              // last: this entry goes with the menu
                            } } } } } }
    }
    Flickable {
        anchors { fill: parent; margins: 14 }
        contentHeight: col.height; clip: true; boundsBehavior: Flickable.StopAtBounds
        Column {
            id: col
            width: parent.width; spacing: 12

            // you, and three quick things
            Item { width: parent.width; height: 40
                Rectangle { id: face; width: 36; height: 36; radius: 18; anchors.verticalCenter: parent.verticalCenter; color: Theme.t.accent; clip: true
                    Label { anchors.centerIn: parent; visible: !Me.face; text: (Me.name || "?").charAt(0).toUpperCase(); color: Theme.t.onAccent; font.pixelSize: 16; font.weight: Font.DemiBold }
                    Image { anchors.fill: parent; visible: !!Me.face; source: Me.face || ""; fillMode: Image.PreserveAspectCrop; sourceSize: Qt.size(72, 72); asynchronous: true } }
                Column { x: 46; width: parent.width - 46 - tools.width - 8; anchors.verticalCenter: parent.verticalCenter
                    Label { width: parent.width; text: cc.hello(); font.pixelSize: 13; font.weight: Font.DemiBold; elide: Text.ElideRight }
                    Label { width: parent.width; secondary: true; font.pixelSize: 11; elide: Text.ElideRight
                        text: Status.battery.present ? "Battery " + Status.battery.percent + "%" + (Status.battery.charging ? ", charging" : "")
                                                     : Qt.formatDate(new Date(), "dddd d MMMM") } }
                Row { id: tools; anchors { right: parent.right; verticalCenter: parent.verticalCenter } spacing: 2
                    Round { glyph: "camera"; tip: "Screenshot"; onClicked: { cc.done(); Status.screenshot("choose") } }
                    Round { glyph: "lock"; tip: "Lock"; onClicked: { cc.done(); Status.power("lock") } }
                    Round { glyph: "gear"; tip: "Settings"; onClicked: { cc.done(); Status.openSettings("") } } } }

            Row {
                spacing: 10
                Block {
                    width: 153; height: Math.max(conns.height + 24, quick.height)
                    Column { id: conns; x: 12; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 24; spacing: 12
                        Conn { visible: cc.net.wifiDevice; title: "Wi‑Fi"; glyph: "wifi"; page: "network"; on: cc.net.wifiOn
                            sub: !cc.net.wifiOn ? "Off" : cc.net.wifiName ? cc.net.wifiName + (cc.net.kind === "wired" ? " · connected (wired is used)" : "") : "Not connected"
                            onToggled: function (on) { Status.setWifi(on) } }
                        Conn { visible: !cc.net.wifiDevice || cc.net.wired; title: cc.net.wired ? "Wired" : "Network"; glyph: cc.net.wired ? "ethernet" : "globe"; page: "network"
                            on: cc.net.wired || cc.net.kind !== "none"; sub: cc.net.wired ? (cc.net.wiredName || "Connected") : cc.net.kind === "none" ? "Not connected" : cc.net.name }
                        Conn { visible: Status.bluetooth.present; title: "Bluetooth"; glyph: "bluetooth"; page: "bluetooth"; on: Status.bluetooth.on
                            sub: Status.bluetooth.on ? "On" : "Off"; onToggled: function (on) { Status.setBluetooth(on) } } }
                }
                Column {
                    id: quick
                    spacing: 8
                    // The quick tiles you chose, in your order (Settings.quickTiles). Edit: − takes one off, a click
                    // moves it one place earlier, and the ones not shown can be added.
                    readonly property var all: ({
                        dnd: { label: "Do Not Disturb", glyph: "moon" }, night: { label: "Night light", glyph: "sun" }, dark: { label: "Dark", glyph: "contrast" },
                        captions: { label: "Live captions", glyph: "captions" }, mute: { label: "Mute", glyph: "mute" }, shot: { label: "Screenshot", glyph: "camera" },
                        lookup: { label: "Look Up", glyph: "search" }, saver: { label: "Screen saver", glyph: "image" } })
                    readonly property var shown: (Settings.quickTiles || []).filter(function (k) { return !!quick.all[k] && (k !== "night" || Status.nightLight.available) })
                    readonly property var addable: (Settings.quickTileKinds || []).filter(function (k) { return (Settings.quickTiles || []).indexOf(k) < 0 && (k !== "night" || Status.nightLight.available) })
                    function isOn(k) { return k === "dnd" ? Status.dnd : k === "night" ? Status.nightLight.on : k === "dark" ? Theme.t.dark : k === "captions" ? Settings.captions
                                              : k === "mute" ? !!cc.levels.muted : false }
                    function run(k) {
                        if (k === "dnd") Status.setDnd(!Status.dnd)
                        else if (k === "night") Status.setNightLight(!Status.nightLight.on)
                        else if (k === "dark") Theme.setDark(!Theme.t.dark)
                        else if (k === "captions") Settings.set("captions", Settings.captions ? "false" : "true")
                        else if (k === "mute") Status.setMuted(!cc.levels.muted)
                        else if (k === "shot") { cc.done(); Status.screenshot("choose") }
                        else if (k === "lookup") { cc.done(); Apps.launch("python3 /usr/share/huginn-apps/huginn_app.py lens") }
                        else if (k === "saver") { cc.done(); cc.saverWanted() }
                    }
                    function save(list) { Settings.set("quickTiles", list.join(",")) }
                    function earlier(k) { var l = (Settings.quickTiles || []).slice(), i = l.indexOf(k); if (i > 0) { l.splice(i, 1); l.splice(i - 1, 0, k); save(l) } }
                    Flow { width: 153; spacing: 9
                        Repeater { model: quick.shown
                            Item { id: qt; required property string modelData; width: 72; height: 76
                                QuickTile { square: true; width: 72; label: quick.all[qt.modelData].label; glyph: quick.all[qt.modelData].glyph; on: quick.isOn(qt.modelData)
                                    onClicked: cc.editTiles ? quick.earlier(qt.modelData) : quick.run(qt.modelData) }
                                Rectangle { visible: cc.editTiles; x: -5; y: -5; width: 20; height: 20; radius: 10; color: "#E5484D"; border.width: 2; border.color: "#FFFFFF"
                                    Rectangle { anchors.centerIn: parent; width: 8; height: 2; radius: 1; color: "#FFFFFF" }
                                    MouseArea { anchors.fill: parent; anchors.margins: -3; cursorShape: Qt.PointingHandCursor
                                        onClicked: quick.save((Settings.quickTiles || []).filter(function (x) { return x !== qt.modelData })) } } } } }
                    Flow { visible: cc.editTiles; width: 153; spacing: 5
                        Repeater { model: quick.addable
                            Rectangle { required property string modelData; width: addLabel.width + 26; height: 24; radius: 12; color: Theme.t.hover
                                Label { id: addLabel; x: 18; anchors.verticalCenter: parent.verticalCenter; text: quick.all[modelData].label; font.pixelSize: 11 }
                                Label { x: 7; anchors.verticalCenter: parent.verticalCenter; text: "+"; font.pixelSize: 12; font.weight: Font.Bold; color: Theme.t.accent }
                                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                    onClicked: if ((Settings.quickTiles || []).length < 8) quick.save((Settings.quickTiles || []).concat([modelData])) } } } }
                    Label { visible: cc.editTiles; width: 153; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 10; text: "Click a tile to move it earlier; − takes it off." }
                    Rectangle { width: tilesEdit.width + 20; height: 22; radius: 11; color: tilesHit.containsMouse ? Theme.t.hover : "transparent"; border.width: 1; border.color: Theme.t.line
                        Label { id: tilesEdit; anchors.centerIn: parent; text: cc.editTiles ? "Done" : "Edit tiles"; font.pixelSize: 11; secondary: !cc.editTiles }
                        MouseArea { id: tilesHit; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: cc.editTiles = !cc.editTiles } }
                }
            }

            Block { width: parent.width; height: levelsCol.height + 24
                Column { id: levelsCol; x: 12; y: 12; width: parent.width - 24; spacing: 8
                    Slider { visible: cc.levels.brightness >= 0; title: "Display"; glyph: "sun"; value: Math.max(0, cc.levels.brightness)
                        onMoved: function (v) { Status.setBrightness(Math.max(0.02, v)) } }
                    Slider { title: cc.levels.muted ? "Sound · muted" : "Sound"; glyph: cc.levels.muted ? "volumeoff" : cc.levels.volume < 0.4 ? "volumelow" : "volumehigh"
                        value: cc.levels.muted ? 0 : cc.levels.volume
                        onMoved: function (v) { Status.setVolume(v) } onGlyphClicked: Status.setMuted(!cc.levels.muted) }
                    // the apps playing sound: one line saying how many, which opens each with its own level
                    Rectangle { visible: cc.appLevels.length > 0; width: parent.width; height: 30; radius: 10
                        color: appsHit.containsMouse ? Theme.t.hover : "transparent"
                        Label { x: 4; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; secondary: true
                                text: cc.appLevels.length === 1 ? (cc.appLevels[0].app + " is playing sound") : (cc.appLevels.length + " apps playing sound") }
                        Glyph { anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter } name: "down"; size: 12
                                rotation: cc.appsOpen ? 180 : 0; Behavior on rotation { NumberAnimation { duration: 150 } } }
                        MouseArea { id: appsHit; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: cc.appsOpen = !cc.appsOpen } }
                    Column { visible: cc.appsOpen && cc.appLevels.length > 0; width: parent.width; spacing: 4
                        Repeater { model: cc.appsOpen ? cc.appLevels : []
                            Item { id: lv; required property var modelData; width: parent.width; height: 44
                                readonly property var app: cc.appOf(modelData)
                                readonly property real level: modelData.mute ? 0 : Math.min(1, modelData.volume / 100)
                                Item { x: 2; width: 28; height: 28; anchors.verticalCenter: parent.verticalCenter
                                    AppIcon { visible: !!lv.app; size: 28; name: lv.app ? lv.app.name : ""; glyph: lv.app ? lv.app.glyph || "" : ""
                                              image: lv.app ? lv.app.image || "" : ""; own: lv.app ? lv.app.own || "" : "" }
                                    Image { id: lvPic; visible: !lv.app && status === Image.Ready; anchors.fill: parent; sourceSize: Qt.size(56, 56); asynchronous: true
                                            source: !lv.app && lv.modelData.icon ? "image://sysicon/" + lv.modelData.icon : "" }
                                    Rectangle { visible: !lv.app && lvPic.status !== Image.Ready; anchors.fill: parent; radius: 8; color: Theme.t.group
                                        Label { anchors.centerIn: parent; text: (lv.modelData.app || "?").charAt(0).toUpperCase(); font.pixelSize: 12; font.weight: Font.DemiBold } }
                                    Rectangle {   // muted: a slash over its picture; a click on the picture mutes or unmutes it
                                        visible: lv.modelData.mute; anchors.fill: parent; radius: 8; color: Qt.rgba(0, 0, 0, 0.45)
                                        Glyph { anchors.centerIn: parent; name: "volumeoff"; size: 14; ink: "#FFFFFF" } }
                                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Status.setAppMuted(lv.modelData.index, !lv.modelData.mute) } }
                                Label { x: 40; y: 3; width: parent.width - 40 - 44; elide: Text.ElideRight; font.pixelSize: 12; font.weight: Font.DemiBold
                                        text: lv.app ? lv.app.name : lv.modelData.app }
                                Label { anchors { right: parent.right; rightMargin: 2 } y: 3; font.pixelSize: 11; secondary: true
                                        text: lv.modelData.mute ? "Muted" : lv.modelData.volume + "%" }
                                Rectangle { id: lvTrack; x: 40; y: 24; width: parent.width - 42; height: 14; radius: 7; color: Theme.t.dark ? "#2EFFFFFF" : "#24141E28"
                                    Rectangle { width: Math.max(14, parent.width * lv.level); height: parent.height; radius: 7
                                                color: lv.modelData.mute ? Theme.t.line : (Theme.t.dark ? "#F2FFFFFF" : "#FFFFFF")
                                                border.width: Theme.t.dark ? 0 : 1; border.color: Theme.t.line }
                                    MouseArea { anchors.fill: parent; anchors.margins: -6; cursorShape: Qt.PointingHandCursor
                                        function to(m) { Status.setAppVolume(lv.modelData.index, Math.round(100 * Math.max(0, Math.min(1, (m.x - 6) / lvTrack.width)))) }
                                        onPositionChanged: function (m) { if (pressed) to(m) } onPressed: function (m) { to(m) } } } } } } } }

            // what's playing
            Block { visible: cc.playing !== null; width: parent.width; height: 68
                Rectangle { x: 12; width: 44; height: 44; radius: 10; anchors.verticalCenter: parent.verticalCenter; color: Theme.t.hover; clip: true
                    Glyph { anchors.centerIn: parent; visible: art.status !== Image.Ready; name: "music"; size: 18 }
                    Image { id: art; anchors.fill: parent; source: cc.playing && cc.playing.art ? cc.playing.art : ""; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize: Qt.size(88, 88) } }
                Column { x: 66; width: parent.width - 66 - 112; anchors.verticalCenter: parent.verticalCenter
                    Label { width: parent.width; text: cc.playing ? cc.playing.title : ""; font.pixelSize: 13; font.weight: Font.DemiBold; elide: Text.ElideRight }
                    Label { width: parent.width; text: cc.playing ? cc.playing.sub : ""; secondary: true; font.pixelSize: 11; elide: Text.ElideRight } }
                Row { anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } spacing: 2
                    Repeater { model: [["prev", "previous"], [cc.playing && cc.playing.kind === "playing" ? "pause" : "play", "playpause"], ["next", "next"]]
                        Rectangle { required property var modelData; width: 32; height: 32; radius: 16; color: ph.containsMouse ? Theme.t.hover : "transparent"
                            Glyph { anchors.centerIn: parent; name: modelData[0]; size: 15 }
                            MouseArea { id: ph; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: if (cc.playing) Live.act(cc.playing.id, modelData[1]) } } } } }

            // what's running in the background, its tray menu, and quitting it
            Item { visible: cc.background.length > 0; width: parent.width; height: 20
                Label { x: 2; text: "Running in the background"; font.pixelSize: 12; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
                Label { anchors { right: parent.right; verticalCenter: parent.verticalCenter } text: "Right-click for more"; secondary: true; font.pixelSize: 11 } }
            Block { visible: cc.background.length > 0; width: parent.width; height: bgCol.height + 12
                objectName: "backgroundApps"
                Column { id: bgCol; x: 6; y: 6; width: parent.width - 12
                    Repeater { model: cc.background
                        Rectangle {
                            id: bgRow
                            required property var modelData
                            width: bgCol.width; height: 42; radius: 11; color: bgHit.containsMouse ? Theme.t.hover : "transparent"
                            Item { x: 6; width: 28; height: 28; anchors.verticalCenter: parent.verticalCenter
                                AppIcon { visible: !!bgRow.modelData.app; size: 28
                                    name: bgRow.modelData.name; glyph: bgRow.modelData.app ? bgRow.modelData.app.glyph || "" : ""
                                    image: bgRow.modelData.app ? bgRow.modelData.app.image || "" : ""; own: bgRow.modelData.app ? bgRow.modelData.app.own || "" : "" }
                                Image { id: trayPic; visible: !bgRow.modelData.app; anchors.fill: parent; sourceSize: Qt.size(56, 56); asynchronous: true
                                    source: !bgRow.modelData.tray ? "" : bgRow.modelData.tray.icon || (bgRow.modelData.tray.iconName ? "image://sysicon/" + bgRow.modelData.tray.iconName : "") }
                                Rectangle {   // no picture of its own: its first letter
                                    visible: !bgRow.modelData.app && trayPic.status !== Image.Ready; anchors.fill: parent; radius: 8; color: Theme.t.group
                                    Label { anchors.centerIn: parent; text: (bgRow.modelData.name || "?").charAt(0).toUpperCase(); font.pixelSize: 13; font.weight: Font.DemiBold } }
                                Rectangle {   // it wants you (Discord: a message)
                                    visible: !!bgRow.modelData.tray && bgRow.modelData.tray.status === "NeedsAttention"
                                    anchors { right: parent.right; top: parent.top; margins: -2 } width: 10; height: 10; radius: 5; color: Theme.t.accent
                                    border.width: 2; border.color: Theme.t.dark ? "#1E2228" : "#FFFFFF" } }
                            Column { x: 44; width: parent.width - 44 - 40; anchors.verticalCenter: parent.verticalCenter
                                Label { width: parent.width; text: bgRow.modelData.name; font.pixelSize: 13; font.weight: Font.DemiBold; elide: Text.ElideRight }
                                Label { width: parent.width; secondary: true; font.pixelSize: 11; elide: Text.ElideRight
                                    text: bgRow.modelData.tray && bgRow.modelData.tray.tooltip ? bgRow.modelData.tray.tooltip
                                        : ({ Mail: "Checking for new mail", Messages: "Waiting for messages" })[bgRow.modelData.name]
                                          || (bgRow.modelData.tray ? (bgRow.modelData.windowed ? "Open, and in the tray" : "In the tray") : "No window open") } }
                            MouseArea { id: bgHit; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton; cursorShape: Qt.PointingHandCursor
                                onClicked: function (m) {
                                    var r = bgRow.modelData
                                    if (m.button === Qt.RightButton || (r.tray && r.tray.isMenu && m.button === Qt.LeftButton)) {
                                        var p = mapToItem(cc, m.x, m.y)
                                        cc.bgMenu = { row: r, x: p.x, y: p.y, items: r.tray ? Tray.menu(r.tray.key) : [] }
                                    } else cc.openRow(r)
                                } }
                            Rectangle {   // quit, without the menu
                                visible: !!bgRow.modelData.app && (bgHit.containsMouse || quitHit.containsMouse)
                                anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } width: 26; height: 26; radius: 13
                                color: quitHit.containsMouse ? Theme.t.danger : Theme.t.hover
                                Glyph { anchors.centerIn: parent; name: "x"; size: 12; ink: quitHit.containsMouse ? "#FFFFFF" : Theme.t.text }
                                MouseArea { id: quitHit; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Apps.quit(bgRow.modelData.name, false) } }
                        } } } }

            // the realm and the app menus
            Block { width: parent.width; height: looks.height + 24
                Column { id: looks; x: 12; y: 12; width: parent.width - 24; spacing: 10
                    Item { width: parent.width; height: 16
                        Label { text: "Realm"; font.pixelSize: 12; font.weight: Font.DemiBold }
                        Label { anchors.right: parent.right; secondary: true; font.pixelSize: 11
                            text: { var r = (Theme.t.realms || []).filter(function (x) { return x.id === Theme.t.realm })[0]; return r ? r.label : "" } } }
                    Row {
                        spacing: 8
                        Repeater {
                            model: Theme.t.realms
                            Rectangle {
                                required property var modelData
                                readonly property bool chosen: Theme.t.realm === modelData.id
                                width: (looks.width - 8 * ((Theme.t.realms || []).length - 1)) / Math.max(1, (Theme.t.realms || []).length); height: 34; radius: 12
                                gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: modelData.a } GradientStop { position: 1; color: modelData.b } }
                                border.width: chosen ? 2 : 0; border.color: Theme.t.text
                                Rectangle { visible: parent.chosen; anchors.centerIn: parent; width: 20; height: 20; radius: 10; color: "#E6FFFFFF"
                                    Glyph { anchors.centerIn: parent; name: "check"; size: 12; ink: "#1A1E23" } }
                                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Theme.setRealm(modelData.id) }
                            }
                        }
                    }
                    Label { text: "App menus open"; font.pixelSize: 12; font.weight: Font.DemiBold }
                    Rectangle {   // segmented choice
                        width: parent.width; height: 30; radius: 10; color: Theme.t.dark ? "#30000000" : "#1F141E28"
                        Row {
                            anchors { fill: parent; margins: 2 }
                            Repeater {
                                model: [["one", "One menu"], ["row", "A row of menus"]]
                                Rectangle {
                                    required property var modelData
                                    readonly property bool on: Settings.menuStyle === modelData[0] || (modelData[0] === "one" && Settings.menuStyle === "dropdown") || (modelData[0] === "row" && Settings.menuStyle === "inline")
                                    width: parent.width / 2; height: parent.height; radius: 8
                                    color: on ? (Theme.t.dark ? "#38FFFFFF" : "#FFFFFF") : "transparent"
                                    Label { anchors.centerIn: parent; text: modelData[1]; font.pixelSize: 12; font.weight: parent.on ? Font.DemiBold : Font.Normal }
                                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Settings.set("menuStyle", modelData[0]) }
                                }
                            }
                        }
                    } } }

            // what came
            Item { width: parent.width; height: 20
                Label { x: 2; text: cc.historyOpen ? "Notifications · the last week" : "Notifications"; font.pixelSize: 12; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
                Row { anchors { right: parent.right; verticalCenter: parent.verticalCenter } spacing: 6
                    Rectangle { visible: cc.keepsHistory; width: histL.width + 18; height: 22; radius: 11; color: hst.containsMouse || cc.historyOpen ? Theme.t.hover : "transparent"; border.width: 1; border.color: Theme.t.line
                        Label { id: histL; anchors.centerIn: parent; text: cc.historyOpen ? "Back" : "History"; font.pixelSize: 11 }
                        MouseArea { id: hst; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                            onClicked: { if (!cc.historyOpen) cc.history = Status.notificationHistory(); cc.historyOpen = !cc.historyOpen } } }
                    Rectangle { visible: cc.historyOpen ? cc.history.length > 0 : Status.notifications.length > 0; width: clearL.width + 18; height: 22; radius: 11
                        color: clr.containsMouse ? Theme.t.hover : "transparent"; border.width: 1; border.color: Theme.t.line
                        Label { id: clearL; anchors.centerIn: parent; text: cc.historyOpen ? "Clear history" : "Clear all"; font.pixelSize: 11 }
                        MouseArea { id: clr; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                            onClicked: { if (cc.historyOpen) { Status.clearHistory(); cc.history = [] } else Status.clearNotifications() } } } } }
            Column { visible: cc.historyOpen; width: parent.width; spacing: 6
                Block { visible: cc.history.length === 0; width: parent.width; height: 52
                    Glyph { x: 14; anchors.verticalCenter: parent.verticalCenter; name: "history"; size: 16; ink: Theme.t.text_secondary }
                    Label { x: 40; width: parent.width - 54; anchors.verticalCenter: parent.verticalCenter; secondary: true; font.pixelSize: 12; text: "No notifications in the last week." } }
                Repeater { model: cc.historyOpen ? cc.history : []
                    Column { required property var modelData; required property int index; width: col.width; spacing: 6
                        Label { visible: index === 0 || cc.history[index - 1].day !== modelData.day; x: 4; topPadding: index === 0 ? 0 : 6
                            text: modelData.day; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold }
                        Block { width: parent.width; height: hc.height + 18
                            Column { id: hc; x: 14; y: 9; width: parent.width - 28; spacing: 2
                                Row { width: parent.width; spacing: 6
                                    Label { text: modelData.app; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold }
                                    Label { text: modelData.time; secondary: true; font.pixelSize: 11 } }
                                Label { text: modelData.summary; font.weight: Font.DemiBold; font.pixelSize: 12; width: parent.width; elide: Text.ElideRight }
                                Label { visible: modelData.body !== ""; text: modelData.body; secondary: true; font.pixelSize: 12; width: parent.width; wrapMode: Text.WordWrap; maximumLineCount: 3; elide: Text.ElideRight } } } } } }
            Block { visible: !cc.historyOpen && Status.notifications.length === 0; width: parent.width; height: 52
                Glyph { x: 14; anchors.verticalCenter: parent.verticalCenter; name: Status.dnd ? "moon" : "bell"; size: 16; ink: Theme.t.text_secondary }
                Label { x: 40; width: parent.width - 54; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                    text: Status.dnd ? "Do Not Disturb is on: they wait here quietly." : "Nothing new." } }
            Repeater {
                model: cc.historyOpen ? [] : Status.notifications
                Block { required property var modelData; width: col.width; height: nc.height + 22
                    Column { id: nc; x: 14; y: 11; width: parent.width - 28; spacing: 2
                        Row { width: parent.width; spacing: 6
                            Label { text: modelData.app; secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold }
                            Label { visible: modelData.more > 0; text: "+" + modelData.more; secondary: true; font.pixelSize: 11 }
                            Label { text: modelData.ago; secondary: true; font.pixelSize: 11 } }
                        Label { text: modelData.summary; font.weight: Font.DemiBold; font.pixelSize: 12; width: parent.width; elide: Text.ElideRight }
                        Label { visible: modelData.body !== ""; text: modelData.body; secondary: true; font.pixelSize: 12; width: parent.width; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight } } }
            }
        }
    }
}
