import QtQuick

// Clock, "dial": a real dial; the modes switch in the island the light comes from.
GlassWindow {
    id: win
    title: "Clock"; width: 820; height: 600; glow: "bottom"; padTop: 60; padBottom: 66
    property string page: startPage || "World Clock"
    function setPage(p) { page = p }
    property real hAngle: 0
    property real mAngle: 0
    property real sAngle: 0
    property var cities: Backend.world()
    property string now: ""
    property string today: ""
    // stopwatch
    property bool running: false
    property real elapsed: 0
    property real since: 0
    property var laps: []
    // timer
    property int setMinutes: 5
    property real left: 0
    property real until: 0
    property bool counting: false
    property bool rang: false
    property real total: 0                 // the whole length of the timer that's running (it grows with +1 min)
    property int setSeconds: 0             // a length typed in (0: the chosen minutes)
    readonly property int lengthMs: (setSeconds > 0 ? setSeconds : setMinutes * 60) * 1000
    // sheets: adding a city, an alarm being made or changed
    property var sheet: null               // { kind: "city" } | { kind: "alarm", id, time, days, label, why }
    property var found: []
    function findCities(text) { found = Backend.findCities(text) }
    function newAlarm() { page = "Alarms"; sheet = { kind: "alarm", id: "", time: "07:00", days: [], label: "", why: "" } }
    function addCity() { page = "World Clock"; sheet = { kind: "city" }; findCities("") }
    function longFmt(ms) { var t = Math.max(0, Math.round(ms / 1000)), h = Math.floor(t / 3600), m = Math.floor(t / 60) % 60, sec = t % 60
        return (h ? h + ":" : "") + (m < 10 ? "0" : "") + m + ":" + (sec < 10 ? "0" : "") + sec }
    Connections { target: Backend; function onChanged() { win.cities = Backend.world() } }
    // The dock's live island shows the timer while it runs (a ring counting down) and rings there when it's done;
    // its buttons (Pause, +1 min, Cancel, Stop) work from there too.
    readonly property string liveKey: rang ? "rang" : counting ? "on:" + until + ":" + total : left > 0 ? "paused:" + Math.round(left) : "off"
    onLiveKeyChanged: {
        var plus = { id: "add60", label: "+1 min" }, cancel = { id: "cancel", label: "Cancel", glyph: "x" }
        if (rang) LiveIsland.report("timer", { kind: "alarm", title: "Timer", glyph: "bell",
            actions: [{ id: "stop", label: "Stop", glyph: "stop", tone: "danger" }, { id: "again", label: "Again", glyph: "refresh" }] })
        else if (counting) LiveIsland.report("timer", { kind: "timer", title: "Timer", ends: until, total: total, paused: false,
            actions: [plus, { id: "pause", label: "Pause", glyph: "pause", tone: "primary" }, cancel] })
        else if (left > 0) LiveIsland.report("timer", { kind: "timer", title: "Timer", left: left, total: total, paused: true,
            actions: [plus, { id: "resume", label: "Resume", glyph: "play", tone: "primary" }, cancel] })
        else LiveIsland.end("timer")
    }
    function startTimer(ms) { rang = false; total = ms; until = Date.now() + ms; left = ms; counting = true }
    Connections { target: LiveIsland
        function onAction(key, what) {
            if (key !== "timer") return
            if (what === "pause" && win.counting) { win.left = win.until - Date.now(); win.counting = false }
            else if (what === "resume" && win.left > 0) { win.until = Date.now() + win.left; win.counting = true }
            else if (what === "add60") { if (win.counting) win.until += 60000; else win.left += 60000; win.total += 60000 }
            else if (what === "cancel" || what === "stop") { win.counting = false; win.left = 0; win.rang = false }
            else if (what === "again") win.startTimer(win.lengthMs)
        } }
    function fmt(ms, tenths) { var t = Math.max(0, ms), m = Math.floor(t / 60000), s = Math.floor(t / 1000) % 60; return (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s + (tenths ? "." + Math.floor(t / 100) % 10 : "") }
    Timer { interval: 1000; running: true; repeat: true; triggeredOnStart: true; onTriggered: { var d = new Date(); win.now = Qt.formatTime(d, "HH:mm:ss"); win.today = Qt.formatDate(d, "dddd, MMMM d"); win.sAngle = d.getSeconds() * 6; win.mAngle = d.getMinutes() * 6 + d.getSeconds() / 10; win.hAngle = (d.getHours() % 12) * 30 + d.getMinutes() / 2; if (d.getSeconds() === 0 || win.cities.length === 0) win.cities = Backend.world() } }
    Timer { interval: 50; running: win.running || win.counting; repeat: true
        onTriggered: { if (win.running) win.elapsed = Date.now() - win.since; if (win.counting) { win.left = win.until - Date.now(); if (win.left <= 0) { win.counting = false; win.left = 0; win.rang = true } } } }
    islands: [
        Island { anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 14 }
            Repeater { model: [["World Clock", "clock"], ["Alarms", "bell"], ["Stopwatch", "play"], ["Timer", "history"]]
                Seg { required property var modelData; icon: modelData[1]; on: win.page === modelData[0]; onClicked: win.page = modelData[0]
                    text: modelData[0] + (modelData[0] === "Timer" && win.counting ? "  ·  " + win.fmt(win.left, false) : "") } } }
    ]
    component Hand: Rectangle { id: hand; property real angle: 0; property real len: 40; x: 80 - width / 2; y: 80 - len; height: len; radius: width / 2; antialiasing: true
        transform: Rotation { origin.x: hand.width / 2; origin.y: hand.len; angle: hand.angle } }
    component Big: Label { font.pixelSize: 72; font.weight: Font.Light; font.family: Theme.t.font; anchors.horizontalCenter: parent.horizontalCenter }
    Flickable { visible: win.page === "World Clock"; x: 28; y: 10; width: parent.width - 56; height: parent.height - 10; contentHeight: worldCol.height + 16; clip: true
      Column { id: worldCol; width: parent.width; spacing: 18
        Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 36
            Rectangle { width: 160; height: 160; radius: 80; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine   // the dial
                Repeater { model: 12; Rectangle { required property int index; x: 79; y: 7; width: 2; height: index % 3 === 0 ? 11 : 5; color: index % 3 === 0 ? Theme.t.text : Theme.t.text_secondary; antialiasing: true
                    transform: Rotation { origin.x: 1; origin.y: 73; angle: index * 30 } } }
                Hand { width: 5; len: 44; angle: win.hAngle; color: Theme.t.text }
                Hand { width: 3; len: 62; angle: win.mAngle; color: Theme.t.text }
                Hand { width: 1.5; len: 68; angle: win.sAngle; color: Theme.t.accent }
                Rectangle { anchors.centerIn: parent; width: 10; height: 10; radius: 5; color: Theme.t.accent } }
            Column { anchors.verticalCenter: parent.verticalCenter
                Label { text: win.now; font.pixelSize: 64; font.weight: Font.Light } Label { text: win.today; secondary: true; font.pixelSize: 15 } } }
        Grid { columns: 2; spacing: 12; width: parent.width
            Repeater { model: win.cities
                Card { required property var modelData; width: (parent.width - 12) / 2; height: 68
                    Rectangle { x: 14; anchors.verticalCenter: parent.verticalCenter; width: 10; height: 10; radius: 5; color: modelData.night ? Theme.t.glowB : "#FFB340" }
                    Label { x: 36; y: 14; text: modelData.city; font.weight: Font.DemiBold } Label { x: 36; y: 36; text: modelData.note; secondary: true; font.pixelSize: 11 }
                    Label { anchors { right: parent.right; rightMargin: cityHover.hovered ? 46 : 16; verticalCenter: parent.verticalCenter } text: modelData.time; font.pixelSize: 26; font.weight: Font.Light
                        Behavior on anchors.rightMargin { NumberAnimation { duration: 120 } } }
                    HoverHandler { id: cityHover }
                    Pressable { visible: cityHover.hovered; anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } width: 28; height: 28; radius: 14
                        color: hovered ? Theme.t.pressed : Theme.t.hover; onClicked: Backend.removeCity(modelData.zone)
                        Glyph { anchors.centerIn: parent; name: "x"; size: 13 } } } }
            Pressable { width: (parent.width - 12) / 2; height: 68; radius: 16; color: hovered ? Theme.t.hover : "transparent"; border.width: 1; border.color: Theme.t.islandLine
                onClicked: win.addCity()
                Row { anchors.centerIn: parent; spacing: 8
                    Glyph { name: "plus"; size: 14; anchors.verticalCenter: parent.verticalCenter } Label { text: "Add a City"; secondary: true; anchors.verticalCenter: parent.verticalCenter } } } } } }
    // ---- alarms: rung by the desktop, whether or not Clock is open
    Flickable { visible: win.page === "Alarms"; anchors.horizontalCenter: parent.horizontalCenter; y: 10; width: Math.min(parent.width - 56, 520); height: parent.height - 20
        contentHeight: alarmCol.height + 20; clip: true
        Column { id: alarmCol; width: parent.width; spacing: 10
            Repeater { model: Backend.alarms
                Card { id: alarmCard; required property var modelData; width: alarmCol.width; height: 76
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                        onClicked: win.sheet = { kind: "alarm", id: alarmCard.modelData.id, time: alarmCard.modelData.time, days: alarmCard.modelData.days, label: alarmCard.modelData.label, why: "" } }
                    Label { x: 18; y: 10; text: modelData.time; font.pixelSize: 34; font.weight: Font.Light; opacity: modelData.on ? 1 : 0.45 }
                    Label { x: 20; y: 52; width: parent.width - 110; elide: Text.ElideRight; secondary: true; font.pixelSize: 11
                        text: [modelData.label, modelData.daysWords, modelData.on ? (modelData.snoozed ? "Snoozed, " : "Rings ") + modelData.next : "Off"].filter(Boolean).join("  ·  ") }
                    Toggle { anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter } on: modelData.on
                        onToggled: function (v) { Backend.setAlarmOn(alarmCard.modelData.id, v) } } } }
            Label { visible: Backend.alarms.length === 0; width: parent.width; topPadding: 60; horizontalAlignment: Text.AlignHCenter; secondary: true; wrapMode: Text.WordWrap
                text: "No alarms yet. An alarm rings on this computer while it's on and you're signed in, whether or not Clock is open." }
            Btn { anchors.horizontalCenter: parent.horizontalCenter; primary: true; text: "New Alarm"; onClicked: win.newAlarm() }
            Label { visible: Backend.alarms.length > 0; width: parent.width; horizontalAlignment: Text.AlignHCenter; secondary: true; font.pixelSize: 11; wrapMode: Text.WordWrap
                text: "Alarms ring while the computer is on and you're signed in. A computer that's asleep stays asleep." } } }
    Column { visible: win.page === "Stopwatch"; anchors.horizontalCenter: parent.horizontalCenter; y: 40; width: Math.min(parent.width - 56, 420); spacing: 22
        Big { text: win.fmt(win.elapsed, true) }
        Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 10
            Btn { width: 110; height: 36; text: win.running ? "Lap" : "Reset"; onClicked: { if (win.running) { var l = win.laps.slice(); l.unshift(win.elapsed); win.laps = l } else { win.elapsed = 0; win.laps = [] } } }
            Btn { width: 110; height: 36; primary: !win.running; danger: win.running; text: win.running ? "Stop" : "Start"; onClicked: { if (!win.running) win.since = Date.now() - win.elapsed; win.running = !win.running } } }
        Column { width: parent.width
            Repeater { model: win.laps
                Item { required property real modelData; required property int index; width: parent.width; height: 34
                    Rectangle { width: parent.width; height: 1; color: Theme.t.separator }
                    Label { anchors.verticalCenter: parent.verticalCenter; text: "Lap " + (win.laps.length - index); secondary: true } Label { anchors { right: parent.right; verticalCenter: parent.verticalCenter } text: win.fmt(modelData, true); font.family: Theme.t.fontMono } } } } }
    Column { visible: win.page === "Timer"; anchors.horizontalCenter: parent.horizontalCenter; y: 40; width: Math.min(parent.width - 56, 420); spacing: 22
        Big { text: win.counting || win.left > 0 ? win.longFmt(win.left) : win.longFmt(win.lengthMs); color: win.rang ? Theme.t.danger : Theme.t.text }
        Label { visible: win.rang; text: "Time's up"; color: Theme.t.danger; font.weight: Font.DemiBold; anchors.horizontalCenter: parent.horizontalCenter }
        Row { visible: !win.counting && win.left <= 0; anchors.horizontalCenter: parent.horizontalCenter; spacing: 8
            Repeater { model: [1, 5, 10, 15, 30, 60]; Btn { required property int modelData; pill: true; primary: win.setSeconds === 0 && win.setMinutes === modelData; text: modelData + " min"
                onClicked: { win.setMinutes = modelData; win.setSeconds = 0; lengthBox.text = ""; win.rang = false } } } }
        TextBox { id: lengthBox; visible: !win.counting && win.left <= 0; anchors.horizontalCenter: parent.horizontalCenter; width: 260
            placeholder: "Or type one: 25, 1:30, 2h 15m, 45s"
            onEdited: win.setSeconds = Backend.timerSeconds(text)
            onAccepted: if (win.setSeconds > 0) { win.rang = false; win.startTimer(win.lengthMs) } }
        Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 10
            Btn { width: 110; height: 36; text: "Cancel"; visible: win.counting || win.left > 0; onClicked: { win.counting = false; win.left = 0; win.rang = false } }
            Btn { width: 110; height: 36; primary: !win.counting; text: win.counting ? "Pause" : (win.left > 0 ? "Resume" : "Start")
                onClicked: { win.rang = false; if (win.counting) { win.counting = false } else if (win.left > 0) { win.until = Date.now() + win.left; win.counting = true } else win.startTimer(win.lengthMs) } } }
        Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12; text: "The timer runs while Clock is open, shows in the dock's live island and rings there when it's done. For something that rings with Clock closed, set an alarm." } }
    // while Alarms shows: "Rings in 3 h" stays right, and an alarm that rang shows as it is now
    Timer { interval: 20000; repeat: true; running: win.page === "Alarms" && win.sheet === null; onTriggered: Backend.reread() }

    // ---- sheets
    Item { anchors.fill: parent; z: 20; visible: win.sheet !== null
        Rectangle { anchors { fill: parent; topMargin: -win.padTop; bottomMargin: -win.padBottom } radius: win.r; color: "#66000000"
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; hoverEnabled: true; onClicked: win.sheet = null; onWheel: function (w) { w.accepted = true } } }
        // a city for the world clock
        Rectangle { visible: !!win.sheet && win.sheet.kind === "city"; anchors.centerIn: parent; width: 380; height: Math.min(parent.height - 20, 440); radius: 18
            color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border; clip: true
            onVisibleChanged: if (visible) { cityBox.text = ""; cityBox.focusIn() }
            MouseArea { anchors.fill: parent }
            Label { x: 22; y: 18; text: "Add a City"; font.pixelSize: 16; font.weight: Font.DemiBold }
            TextBox { id: cityBox; x: 22; y: 50; width: parent.width - 44; placeholder: "City or region"; onEdited: win.findCities(text)
                Keys.onEscapePressed: win.sheet = null
                onAccepted: if (win.found.length) { var c = win.found[0]; Backend.addCity(c.city, c.zone); win.sheet = null } }
            Flickable { x: 12; y: 96; width: parent.width - 24; height: parent.height - 152; contentHeight: foundCol.height; clip: true
                Column { id: foundCol; width: parent.width
                    Repeater { model: win.found
                        Pressable { required property var modelData; width: foundCol.width; height: 34; radius: 9
                            onClicked: { var c = modelData, be = Backend, w = win; be.addCity(c.city, c.zone); w.sheet = null }
                            Label { x: 10; anchors.verticalCenter: parent.verticalCenter; text: modelData.city }
                            Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: modelData.region; secondary: true; font.pixelSize: 11 } } }
                    Label { visible: win.found.length === 0; width: parent.width; topPadding: 30; horizontalAlignment: Text.AlignHCenter; secondary: true; text: "No place by that name" } } }
            Btn { anchors { right: parent.right; bottom: parent.bottom; margins: 14 } text: "Cancel"; onClicked: win.sheet = null } }
        // an alarm, new or changed
        Rectangle { id: alarmSheet; visible: !!win.sheet && win.sheet.kind === "alarm"; anchors.centerIn: parent; width: 400; height: 300; radius: 18
            color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
            property var days: []
            readonly property bool isNew: !win.sheet || !win.sheet.id
            onVisibleChanged: if (visible) { timeBox.text = win.sheet.time; labelBox.text = win.sheet.label; days = win.sheet.days.slice(); timeBox.focusIn(); timeBox.input.selectAll() }
            function save() {
                var why = Backend.saveAlarm(win.sheet.id, timeBox.text, days, labelBox.text)
                if (why === "") win.sheet = null
                else win.sheet = { kind: "alarm", id: win.sheet.id, time: timeBox.text, days: days, label: labelBox.text, why: why }
            }
            MouseArea { anchors.fill: parent }
            Label { x: 22; y: 18; text: alarmSheet.isNew ? "New Alarm" : "Alarm"; font.pixelSize: 16; font.weight: Font.DemiBold }
            TextBox { id: timeBox; x: 22; y: 52; width: 120; placeholder: "7:30"; onAccepted: alarmSheet.save(); Keys.onEscapePressed: win.sheet = null }
            TextBox { id: labelBox; x: 152; y: 52; width: parent.width - 174; placeholder: "What it's for (if you like)"; onAccepted: alarmSheet.save(); Keys.onEscapePressed: win.sheet = null }
            Label { x: 22; y: 104; text: "Repeat"; secondary: true; font.pixelSize: 11 }
            Row { x: 22; y: 124; spacing: 6
                Repeater { model: ["M", "T", "W", "T", "F", "S", "S"]
                    Pressable { required property string modelData; required property int index; width: 40; height: 40; radius: 20
                        readonly property bool on: alarmSheet.days.indexOf(index) >= 0
                        color: on ? Theme.t.accent : (hovered ? Theme.t.pressed : Theme.t.group); border.width: 1; border.color: Theme.t.islandLine
                        onClicked: { var d = alarmSheet.days.slice(), i = d.indexOf(index); if (i >= 0) d.splice(i, 1); else d.push(index); alarmSheet.days = d }
                        Label { anchors.centerIn: parent; text: modelData; font.weight: Font.DemiBold; color: parent.on ? Theme.t.onAccent : Theme.t.text } } } }
            Label { x: 22; y: 174; secondary: true; font.pixelSize: 11
                text: alarmSheet.days.length === 0 ? "Rings once, then turns itself off." : alarmSheet.days.length === 7 ? "Rings every day." : "Rings on the days chosen." }
            Label { x: 22; y: 198; width: parent.width - 44; elide: Text.ElideRight; color: Theme.t.danger; font.pixelSize: 12; text: win.sheet ? (win.sheet.why || "") : "" }
            Btn { visible: !alarmSheet.isNew; anchors { left: parent.left; bottom: parent.bottom; margins: 16 } danger: true; text: "Delete"
                onClicked: { Backend.removeAlarm(win.sheet.id); win.sheet = null } }
            Row { anchors { right: parent.right; bottom: parent.bottom; margins: 16 } spacing: 8
                Btn { text: "Cancel"; onClicked: win.sheet = null } Btn { primary: true; text: alarmSheet.isNew ? "Add" : "Save"; onClicked: alarmSheet.save() } } }
    }
}
