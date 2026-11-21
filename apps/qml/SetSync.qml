import QtQuick

// Sync: Notes, Reminders and Huginn OS's settings across your computers, in one group with what Huginn (the browser)
// syncs: Favorites, the Reading List, passwords and open tabs. Through a folder you choose; everything in it sealed.
// (huginn_sync.py: SyncSettings as "Sync")
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property bool have: typeof Sync !== "undefined"
    readonly property var st: have ? Sync.status : ({})
    readonly property bool on: !!st.on
    readonly property string busy: have ? Sync.busy : ""
    readonly property var others: (st.devices || []).filter(function (d) { return !d.this })
    property string folder: ""
    property string shownKey: ""
    property bool joining: false
    function ago(t) {
        if (!t) return "not yet"
        var s = Math.max(0, Date.now() / 1000 - t)
        if (s < 60) return "just now"
        if (s < 3600) return Math.round(s / 60) + (Math.round(s / 60) === 1 ? " minute ago" : " minutes ago")
        if (s < 86400) return Math.round(s / 3600) + (Math.round(s / 3600) === 1 ? " hour ago" : " hours ago")
        return Math.round(s / 86400) + (Math.round(s / 86400) === 1 ? " day ago" : " days ago")
    }
    function chooseFolder(then) {
        if (typeof Picker === "undefined") return
        Picker.openFolder("Choose a sync folder", function (paths) { if (paths.length) then(paths[0]) })
    }
    Connections { target: pg.have ? Sync : null; function onSaid(text, bad) { win.say(text, bad) } }

    // the state in one card
    Rectangle { width: parent.width; height: 150; radius: Theme.t.radiusCard; color: Theme.t.group; border.width: 1; border.color: Theme.t.separator; clip: true
        Rectangle { x: parent.width - 220; y: -60; width: 300; height: 300; radius: 150; opacity: 0.22
            gradient: Gradient { GradientStop { position: 0; color: pg.st.error ? "#E8A10C" : pg.on ? "#27C281" : "#4C8DFF" } GradientStop { position: 1; color: "transparent" } } }
        Rectangle { x: 24; width: 72; height: 72; radius: 36; anchors.verticalCenter: parent.verticalCenter
            color: pg.st.error ? Qt.rgba(0.96, 0.62, 0.04, 0.18) : pg.on ? Qt.rgba(0.15, 0.76, 0.5, 0.18) : Qt.rgba(0.3, 0.55, 1, 0.18)
            Glyph { id: mark; anchors.centerIn: parent; name: pg.st.error ? "warning" : pg.busy === "syncing" ? "refresh" : "cloud"; size: 38
                ink: pg.st.error ? "#E8A10C" : pg.on ? "#27C281" : "#4C8DFF"
                RotationAnimation on rotation { running: pg.busy === "syncing" || pg.busy === "joining"; loops: Animation.Infinite; from: 360; to: 0; duration: 1400
                    onRunningChanged: if (!running) mark.rotation = 0 } } }
        Column { x: 116; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 116 - 190; spacing: 4
            Label { font.pixelSize: 21; font.weight: Font.Light
                text: !pg.on ? "Sync between your computers" : pg.st.error ? "Sync needs a look" : pg.others.length ? "In step with " + pg.others.length + (pg.others.length === 1 ? " other device" : " other devices") : "Waiting for your other devices" }
            Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true
                text: !pg.on ? "Notes, Reminders and Huginn OS's settings, with Huginn's Favorites, Reading List, passwords and open tabs. Through a folder you choose, sealed so only your devices can read it. No account."
                      : pg.st.error ? pg.st.error : "Last synced " + pg.ago(pg.st.lastSync) + ". It syncs by itself every few minutes." } }
        Btn { visible: pg.on; anchors { right: parent.right; rightMargin: 22; verticalCenter: parent.verticalCenter }
            text: pg.busy === "syncing" ? "Syncing…" : "Sync Now"; enabled: !pg.busy; onClicked: Sync.syncNow() } }

    // ---------------------------------------------------------------- not set up: start, or join
    SetCard { visible: !pg.on; title: "Start syncing"
        note: "Pick a folder that reaches your other computers: one Syncthing, Nextcloud or Dropbox keeps in step, a network share, or a USB stick you carry. Each device only ever writes its own file there, sealed with your group's key."
        SetRow { title: pg.folder || "No folder chosen"; sub: pg.folder ? "The sync folder" : "Choose where your devices meet"; glyph: "folder"; tile: "#0A8071"
            Row { spacing: 8
                Btn { text: "Choose…"; onClicked: pg.chooseFolder(function (p) { pg.folder = p }) }
                Btn { primary: true; text: pg.busy === "joining" && !pg.joining ? "Starting…" : "Start Syncing"; enabled: pg.folder !== "" && !pg.busy
                    onClicked: { pg.joining = false; Sync.setUp(pg.folder) } } } } }
    SetCard { visible: !pg.on; title: "Join your other devices"
        note: "Already syncing somewhere? On that device, open Settings › Sync (or Huginn's Sync settings) and show the pairing key, then paste it here. Choose the same sync folder as it uses."
        Item { width: parent.width; height: 58
            TextBox { id: keyBox; x: 16; width: parent.width - 32 - joinBtn.width - 10; height: 34; anchors.verticalCenter: parent.verticalCenter; mono: true; placeholder: "HB1-… or HB2-…" }
            Btn { id: joinBtn; anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter }
                text: pg.busy === "joining" && pg.joining ? "Joining…" : "Join"; enabled: keyBox.text.trim().length > 20 && pg.folder !== "" && !pg.busy
                onClicked: { pg.joining = true; Sync.join(keyBox.text, pg.folder) } } }
        SetRow { visible: pg.folder === ""; title: "Choose the sync folder first"; sub: "The one the other device uses, as it appears on this computer"; glyph: "folder"; tile: "#475569"
            Btn { text: "Choose…"; onClicked: pg.chooseFolder(function (p) { pg.folder = p }) } } }

    // ---------------------------------------------------------------- set up
    SetCard { visible: pg.on; title: "What syncs"
        note: "Huginn, the browser, syncs its part while it's open (and picks up a change here the next time it starts). Each device chooses for itself."
        Repeater { model: [
                { id: "notes", title: "Notes", sub: "Everything in Documents › Notes. A note changed on two computers at once keeps both versions.", glyph: "doc", tile: "#C98A00" },
                { id: "reminders", title: "Reminders", sub: "Your reminders and lists", glyph: "check", tile: "#E5484D" },
                { id: "settings", title: "Huginn OS's settings", sub: "Look, the Dock, the bar, the clock and more. Not this computer's screens or hardware.", glyph: "gear", tile: "#475569" },
                { id: "bookmarks", title: "Favorites", sub: "From Huginn, the browser", glyph: "star", tile: "#1E40AF" },
                { id: "reading", title: "Reading List", sub: "From Huginn, the browser", glyph: "book", tile: "#5A3FE0" },
                { id: "passwords", title: "Passwords", sub: "From Huginn: sealed again with a key in your password vault, so they sync while it's unlocked", glyph: "key", tile: "#0A8071" },
                { id: "tabs", title: "Open tabs", sub: "See the other devices' tabs in Huginn", glyph: "window", tile: "#2563EB" } ]
            SetRow { required property var modelData; title: modelData.title; sub: modelData.sub; glyph: modelData.glyph; tile: modelData.tile
                Toggle { on: (pg.st.collections || []).indexOf(modelData.id) >= 0 || (pg.st.browser || []).indexOf(modelData.id) >= 0
                    onToggled: function (v) { Sync.setCollection(modelData.id, v) } } } } }
    SetCard { visible: pg.on; title: "Devices"
        Repeater { model: pg.st.devices || []
            SetRow { required property var modelData
                title: modelData.name + (modelData.this ? " (this computer)" : "")
                sub: (modelData.what.indexOf("system") >= 0 ? (modelData.what.indexOf("browser") >= 0 ? "Huginn OS and the browser" : "Huginn OS") : "Huginn, the browser") + " · last synced " + pg.ago(modelData.seen)
                glyph: modelData.what.indexOf("system") >= 0 ? "laptop" : "globe"; tile: modelData.this ? "#27C281" : "#475569" } }
        SetRow { visible: (pg.st.devices || []).length === 0; title: "No devices yet"; sub: "They show here once they've synced through the folder" } }
    SetCard { visible: pg.on; title: "Add a device"
        note: "On the new device, choose the same sync folder and paste this key in Settings › Sync, or in Huginn's Sync settings. Anyone with the key can join your group, so keep it to yourself. It's kept " + (pg.st.keyWhere || "on this computer") + "."
        SetRow { visible: pg.shownKey === ""; title: "Pairing key"; sub: "Shows the key for this group"; glyph: "key"; tile: "#5A3FE0"
            Btn { text: "Show Key"; onClicked: pg.shownKey = Sync.pairingKey() } }
        Item { visible: pg.shownKey !== ""; width: parent.width; height: keyText.height + 28
            TextEdit { id: keyText; x: 16; y: 14; width: parent.width - 32 - copyBtn.width - 12; readOnly: true; selectByMouse: true; wrapMode: TextEdit.WrapAnywhere
                text: pg.shownKey; color: Theme.t.text; font.family: Theme.t.fontMono; font.pixelSize: 13; selectionColor: Theme.t.accent }
            Btn { id: copyBtn; anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter } text: "Copy"
                onClicked: { keyText.selectAll(); keyText.copy(); keyText.deselect(); win.say("Copied the pairing key.", false) } } } }
    SetCard { visible: pg.on; title: "Sync folder"
        SetRow { title: pg.st.folder || "None"; sub: "Where your devices meet"; glyph: "folder"; tile: "#0A8071"
            Btn { text: "Change…"; enabled: !pg.busy; onClicked: pg.chooseFolder(function (p) { Sync.setFolder(p) }) } }
        SetRow { visible: (pg.st.kept || []).length > 0; title: "Notes kept from both computers"; sub: (pg.st.kept || []).join(", "); glyph: "doc"; tile: "#C98A00" } }
    SetCard { visible: pg.on
        SetRow { title: "Stop syncing on this computer"; sub: "What's here stays. The other devices keep syncing without it."; glyph: "x"; tile: "#8A3B3B"
            Btn { text: "Stop Syncing"; enabled: !pg.busy
                onClicked: win.confirm("Stop syncing on this computer?", "Your notes, reminders and settings stay as they are here. To sync again, you'll need the pairing key from another device.", "Stop Syncing", function () { Sync.leave() }, true) } } }
}
