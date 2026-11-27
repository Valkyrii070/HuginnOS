import QtQuick

// Software Update: the state in one big card (up to date, or what's waiting and the button that does it all),
// then what's waiting grouped by where it comes from, then automatic updates and Huginn's own version.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property bool have: typeof Updates !== "undefined"
    readonly property var items: have ? Updates.items : []
    readonly property var visibleItems: items.filter(function (i) { return !i.runtime })
    readonly property int security: items.filter(function (i) { return i.security }).length
    readonly property bool working: have && Updates.phase === "installing"
    readonly property bool checking: have && Updates.phase === "checking"
    readonly property bool problem: have && !checking && !working && (Updates.problem || "") !== ""
    property bool allSystem: false
    readonly property var groups: [
        { kind: "system", title: "System", sub: "Ubuntu's packages: the kernel, drivers, the browser engine and every library", glyph: "cpu", tile: "#1E40AF" },
        { kind: "app", title: "Apps", sub: "From Flathub", glyph: "apps", tile: "#0A8071" },
        { kind: "os", title: "Huginn OS", sub: "The desktop, every Huginn app and the system's own files", glyph: "desktop", tile: "#B4491F" },
        { kind: "huginn", title: "Huginn", sub: "The browser, from its own repository", glyph: "globe", tile: "#5A3FE0" },
        { kind: "firmware", title: "Firmware", sub: "This computer's own firmware and devices (needs a restart)", glyph: "bolt", tile: "#C46A00" } ]
    Rectangle { width: parent.width; height: 150; radius: Theme.t.radiusCard; color: Theme.t.group; border.width: 1; border.color: Theme.t.separator; clip: true
        Rectangle { x: parent.width - 220; y: -60; width: 300; height: 300; radius: 150; opacity: 0.22
            gradient: Gradient { GradientStop { position: 0; color: pg.visibleItems.length ? "#4C8DFF" : "#27C281" } GradientStop { position: 1; color: "transparent" } } }
        Rectangle { x: 24; width: 72; height: 72; radius: 36; anchors.verticalCenter: parent.verticalCenter
            color: pg.visibleItems.length || pg.working || pg.checking ? Qt.rgba(0.3, 0.55, 1, 0.18) : pg.problem ? Qt.rgba(0.96, 0.62, 0.04, 0.18) : Qt.rgba(0.15, 0.76, 0.5, 0.18)
            Glyph { id: bigMark; anchors.centerIn: parent; name: pg.visibleItems.length || pg.working || pg.checking ? "refresh" : pg.problem ? "warning" : "check"; size: 38; ink: pg.visibleItems.length || pg.working || pg.checking ? "#4C8DFF" : pg.problem ? "#E8A10C" : "#27C281"
                // turns the way its arrow points (anticlockwise), and comes to rest upright when the work is done
                RotationAnimation on rotation { id: turning; running: pg.working || pg.checking; loops: Animation.Infinite; from: 360; to: 0; duration: 1400
                    onRunningChanged: if (!running) bigMark.rotation = 0 } } }      // (an animation has no parent: by its id)
        Column { x: 116; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 116 - 200; spacing: 4
            Label { font.pixelSize: 21; font.weight: Font.Light
                text: !pg.have ? "Software Update isn't available" : pg.checking ? "Looking for updates…" : pg.working ? "Updating…" : pg.visibleItems.length ? pg.visibleItems.length + (pg.visibleItems.length === 1 ? " update is ready" : " updates are ready") : pg.problem ? "Couldn't look for every update" : "Everything is up to date" }
            Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true
                text: !pg.have ? "" : pg.working ? Updates.line : pg.visibleItems.length ? (pg.security ? pg.security + " fix" + (pg.security === 1 ? "es a" : "") + " security problem" + (pg.security === 1 ? "" : "s") + ". " : "") + "Last looked " + Updates.checked.toLowerCase() + "." : pg.problem ? Updates.problem + " Try Check Now again." : "Last looked " + Updates.checked.toLowerCase() + "." }
            Meter { visible: pg.working; width: parent.width; value: pg.have ? Updates.progress : 0; fill: "#4C8DFF" } }
        Column { anchors { right: parent.right; rightMargin: 22; verticalCenter: parent.verticalCenter } spacing: 8
            Btn { visible: pg.have && pg.visibleItems.length > 0 && !pg.working; primary: true; text: "Update All"; onClicked: Updates.install("all") }
            Btn { visible: pg.have && !pg.working; text: pg.checking ? "Looking…" : "Check Now"; enabled: !pg.checking; onClicked: Updates.look(true) }
            Btn { visible: pg.working; text: "Stop"; onClicked: Updates.stop() } } }
    Rectangle { visible: pg.have && Updates.restart; width: parent.width; height: 58; radius: Theme.t.radiusCard; color: Qt.rgba(0.96, 0.62, 0.04, 0.16); border.width: 1; border.color: Qt.rgba(0.96, 0.62, 0.04, 0.5)
        Glyph { x: 18; anchors.verticalCenter: parent.verticalCenter; name: "refresh"; size: 20; ink: "#E8A10C" }
        Label { x: 50; anchors.verticalCenter: parent.verticalCenter; text: "Restart to finish updating: the new system parts start being used then." }
        Btn { anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter } text: "Restart"; onClicked: win.confirm("Restart now?", "Save your work first: open apps close.", "Restart", function () { Updates.restartNow() }, false) } }
    Repeater { model: pg.groups
        SetCard { required property var modelData
            readonly property var mine: pg.visibleItems.filter(function (i) { return i.kind === modelData.kind })
            visible: mine.length > 0; title: modelData.title
            SetRow { title: modelData.title + " · " + mine.length + (mine.length === 1 ? " update" : " updates"); sub: modelData.sub; glyph: modelData.glyph; tile: modelData.tile
                Btn { text: "Update"; enabled: !pg.working; onClicked: Updates.install(modelData.kind) } }
            Repeater { model: modelData.kind === "system" && !pg.allSystem ? mine.slice(0, 5) : mine
                SetRow { required property var modelData; title: modelData.name
                    sub: (modelData.from ? modelData.from + " → " : "") + modelData.version + (modelData.note ? " · " + modelData.note : "")
                    Row { spacing: 8
                        Rectangle { visible: !!modelData.security; height: 20; width: sec.width + 14; radius: 6; color: Qt.rgba(0.85, 0.2, 0.25, 0.16); anchors.verticalCenter: parent.verticalCenter
                            Label { id: sec; anchors.centerIn: parent; text: "Security"; color: Theme.t.danger; font.pixelSize: 10; font.weight: Font.DemiBold } }
                        Btn { visible: modelData.kind === "app"; text: "Update"; enabled: !pg.working; onClicked: Updates.install(modelData.id) } } } }
            SetRow { visible: modelData.kind === "system" && mine.length > 5; title: pg.allSystem ? "Show fewer" : "Show all " + mine.length; chevron: true; onClicked: pg.allSystem = !pg.allSystem } } }
    SetCard { title: "Automatic updates"; note: "Apps and Huginn update by themselves. System updates and Huginn OS itself are downloaded and go in the next time you restart, so nothing changes under a program you're using."
        SetRow { title: "Keep this computer up to date by itself"; glyph: "refresh"; tile: "#1E40AF"; Toggle { on: Settings.autoUpdate; onToggled: function (v) { Settings.set("autoUpdate", v ? "true" : "false"); if (pg.have) Updates.osSetAuto(v) } } } }
    // Huginn OS itself: which version this is, one fetched and waiting for the restart, what it changes, going back
    SetCard { id: osCard; objectName: "osCard"; visible: pg.have; title: "Huginn OS"
        readonly property var os: pg.have ? Updates.os : ({})
        note: !os.known ? "This system was installed before Huginn OS could update itself. Install the newest image once: after that the desktop, the apps and the system's own files arrive here, with no new installation."
              : os.live ? "This is Huginn OS running from the installation drive. An installed system keeps itself up to date."
              : "The desktop, every Huginn app, the look and the system's own files, from the same place the system was built from. A new version is fetched and checked in the background and put in place when the computer starts, before you sign in, so nothing changes under an app you're using."
        SetRow { visible: !!osCard.os.known; title: "Version"; sub: osCard.os.applied && osCard.os.applied.undone ? "You went back to this version" : osCard.os.applied && osCard.os.applied.date === osCard.os.date ? "Updated by Software Update" : "The version that came with the system"
            Label { text: (osCard.os.date || "") + (osCard.os.commit ? " · " + osCard.os.commit : ""); secondary: true; font.family: Theme.t.fontMono } }
        SetRow { objectName: "osStaged"; visible: !!(osCard.os.staged && osCard.os.staged.commit); title: "Ready: " + (osCard.os.staged ? osCard.os.staged.date + " · " + osCard.os.staged.commit : "")
            sub: osCard.os.staged && osCard.os.staged.news && osCard.os.staged.news.length ? osCard.os.staged.news.slice(0, 4).join("  ·  ") : (osCard.os.staged ? osCard.os.staged.title || "" : "")
            Row { spacing: 8
                Btn { text: "Finish Now"; enabled: !pg.working; onClicked: win.confirm("Put Huginn OS in place now?", "Open Huginn apps keep running the old version until you open them again, and the desktop until you sign out. Restarting instead does it all at once.", "Finish Now", function () { Updates.osFinishNow() }) }
                Btn { primary: true; text: "Restart"; onClicked: win.confirm("Restart now?", "Save your work first: open apps close.", "Restart", function () { Updates.restartNow() }) } } }
        SetRow { visible: !!(osCard.os.applied && osCard.os.applied.kept && osCard.os.applied.kept.length); title: "Left as you changed them"; sub: osCard.os.applied && osCard.os.applied.kept ? osCard.os.applied.kept.join(", ") : "" }
        SetRow { visible: !!osCard.os.problem; title: "The last try didn't work"; sub: osCard.os.problem || "" }
        SetRow { objectName: "osBack"; visible: !!osCard.os.canGoBack; title: "Go back to the version before"; sub: "If the newest one gives you trouble. It isn't taken again by itself."
            Btn { text: "Go Back"; enabled: !pg.working; onClicked: win.confirm("Go back to the Huginn OS before this one?", "The desktop, the apps and the system's own files go back to how they were before the last update. Your files and settings aren't touched.", "Go Back", function () { Updates.osGoBack() }) } } }
    SetCard { visible: pg.have; title: "Huginn"
        SetRow { title: "Version"; sub: pg.have ? (Updates.huginn.yours ? "Updated by Software Update" : "The version that came with the system") : ""
            Label { text: pg.have ? Updates.huginn.date + " · " + Updates.huginn.commit : ""; secondary: true; font.family: Theme.t.fontMono } }
        SetRow { visible: pg.have && Updates.huginn.canGoBack; title: "Go back to the version before"; sub: "If the newest one gives you trouble"
            Btn { text: "Go Back"; onClicked: Updates.goBack() } } }
    // Restore points: a copy of the system (not your files) before each update, to go back to here or from the
    // start-up menu (huginn-snapshot). Only on a computer Huginn OS was installed on, which puts the system on btrfs.
    readonly property var restore: have ? Updates.restore : ({})
    SetCard { visible: pg.have && !!pg.restore.available; title: "Restore points"
        note: "Before every update, Huginn OS keeps a copy of the system as it was: the apps, drivers and settings, not your files. If an update gives you trouble, go back to one here, or pick \"Huginn OS restore points\" in the start-up menu if the computer won't start. Your files in your home folder stay as they are."
        SetRow { visible: (pg.restore.pending || 0) > 0; title: "Restart to finish going back"; sub: "The system will be as it was then. What you have now is kept, in case you want it back."; glyph: "refresh"; tile: "#C46A00"
            Btn { primary: true; text: "Restart"; onClicked: win.confirm("Restart now?", "Save your work first: open apps close.", "Restart", function () { Updates.restartNow() }, false) } }
        SetRow { visible: (pg.restore.undone || 0) > 0 && !(pg.restore.pending > 0); title: "This computer went back to restore point " + (pg.restore.undone || ""); sub: "Updates you install from now on make new restore points as usual."; glyph: "check"; tile: "#0A8071" }
        Repeater { model: pg.restore.points || []
            SetRow { required property var modelData
                title: modelData.when; sub: modelData.reason + (modelData.mine ? " · kept until you remove it" : "")
                glyph: modelData.mine ? "pin" : "clock"; tile: modelData.mine ? "#5A3FE0" : "#475569"
                Row { spacing: 8
                    Btn { text: "Go Back to This"; enabled: !pg.restore.busy && !(pg.restore.pending > 0)
                        onClicked: win.confirm("Go back to " + modelData.when.toLowerCase() + "?", "The system goes back to how it was then, after a restart: apps installed or updated since are gone or older again. Your files aren't touched, and what you have now is kept in case you want it back.", "Go Back", function () { Updates.undoTo(modelData.n) }, true) }
                    Btn { visible: modelData.mine; text: "Remove"; enabled: !pg.restore.busy
                        onClicked: win.confirm("Remove this restore point?", modelData.reason + ", " + modelData.when.toLowerCase() + ". You can't go back to it after this.", "Remove", function () { Updates.forgetPoint(modelData.n) }, true) } } } }
        SetRow { visible: (pg.restore.points || []).length === 0; title: "No restore points yet"; sub: "The first one is made before the next update." }
        SetRow { title: pg.restore.busy === "making" ? "Making a restore point…" : "Make a restore point now"; sub: "Before you change something big yourself. Kept until you remove it."; glyph: "plus"; tile: "#1E40AF"
            Btn { text: "Make One"; enabled: !pg.restore.busy; onClicked: Updates.makeRestorePoint() } }
        SetRow { visible: (pg.restore.leftovers || []).length > 0; title: "What going back left behind"; sub: "The system as it was before you went back (" + (pg.restore.leftovers || []).length + "). Remove it once everything works, to free the space."; glyph: "trash"; tile: "#8A3B3B"
            Btn { text: "Remove"; enabled: !pg.restore.busy; onClicked: Updates.tidyRestore() } } }
}
