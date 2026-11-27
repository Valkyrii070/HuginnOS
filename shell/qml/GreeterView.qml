import QtQuick
import QtQuick.Effects

// What Huginn's sign-in screen shows on one screen. The realm's live wallpaper moves behind everything. On the main
// screen: a quiet bar along the top, a greeting and the time, and the dock, which is where you sign in. Your picture,
// your name and your password sit in the dock where your apps will be; other people are beside them, then sleep,
// restart and shut down.
//
// When the password is right the dock wakes: the password becomes a line of light, the dock clears to your picture,
// places for your apps light up from the middle outwards, and the time blooms in the realm's colours and is gone.
// Then this screen leaves (Host.done) and your desktop takes its place.
//
// A wrong password shakes the field and says so. After several, the service makes you wait, and the wait counts down.
FocusScope {
    id: view
    property bool main: true
    // the lock screen (huginn_locker.py) is this same screen: only you in the dock, Sleep and no Restart or Shut Down
    // (they'd close what you have open), and no session to choose
    readonly property bool locking: Host.locking === true
    readonly property string realm: Host.realm
    readonly property var realms: ({
        aurora:     { tintA: "#0F2624", tintB: "#17192C", glowA: "#3DD6B5", glowB: "#7B61FF", accent: "#43D9B8", onAccent: "#062321", deep: "#16302F" },
        bifrost:    { tintA: "#1D1932", tintB: "#2A1727", glowA: "#8E7BFF", glowB: "#FF7AB8", accent: "#A995FF", onAccent: "#150F33", deep: "#2E2558" },
        muspelheim: { tintA: "#2C1912", tintB: "#1F1718", glowA: "#FF8A4C", glowB: "#FFC857", accent: "#FF8C50", onAccent: "#2A0F05", deep: "#3A1D12" },
        niflheim:   { tintA: "#12212F", tintB: "#171A20", glowA: "#7CC4FF", glowB: "#CFEAFF", accent: "#7CC4FF", onAccent: "#071828", deep: "#14283A" } })
    readonly property var own: realms[realm] || realms.aurora
    readonly property color ink: "#F5F7FA"
    readonly property color soft: Qt.rgba(0.96, 0.97, 0.98, 0.80)
    readonly property string face: "Inter"

    // who is chosen, and what's going on
    property int sel: 0
    readonly property var people: Host.people
    readonly property var who: people.length ? people[Math.min(sel, people.length - 1)] : null
    property string session: "huginn"
    property string phase: "idle"            // idle | checking | wake
    property string message: ""
    property int waitLeft: 0
    property date now: new Date()
    readonly property bool busy: phase !== "idle"
    // their sign-in widgets (Settings › Sign-In Screen): with any, the time moves left and the widgets take the right
    readonly property var tiles: who && who.widgets ? who.widgets : []
    readonly property real k: Math.max(0.8, Math.min(1.5, Math.min(width / 1440, height / 900)))
    readonly property bool withTiles: main && tiles.length > 0 && width >= 1000
    // two columns of cells, filled row by row: a wide widget takes two cells across, a tall one two down
    function pack(list) {
        var used = [], out = []
        function free(r, c) { return !used[r * 2 + c] }
        for (var i = 0; i < list.length; i++) {
            var w = list[i].size === "wide" ? 2 : 1, h = list[i].size === "tall" ? 2 : 1, done = false
            for (var r = 0; r < 12 && !done; r++) for (var c = 0; c + w <= 2 && !done; c++) {
                var ok = true
                for (var dr = 0; dr < h; dr++) for (var dc = 0; dc < w; dc++) if (!free(r + dr, c + dc)) ok = false
                if (ok) { for (dr = 0; dr < h; dr++) for (dc = 0; dc < w; dc++) used[(r + dr) * 2 + c + dc] = true
                          out.push({ row: r, col: c, w: w, h: h }); done = true }
            }
        }
        return out
    }

    function initials(full) {
        var parts = String(full || "").trim().split(/\s+/).filter(function (p) { return p.length })
        if (!parts.length) return "?"
        return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase()
    }
    readonly property bool twelve: /a/i.test(Qt.locale().timeFormat(Locale.ShortFormat).replace(/'[^']*'/g, ""))
    function clockText(big) {
        if (!twelve) return Qt.formatTime(now, "HH:mm")
        return big ? Qt.formatTime(now, "h:mm ap").replace(/\s?[ap]m$/i, "") : Qt.formatTime(now, "h:mm AP")
    }
    function first(full) { return String(full || "").trim().split(/\s+/)[0] || "" }
    function greeting() {
        var h = now.getHours()
        return h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"
    }
    function choose(i) {
        if (busy || i === sel) return
        sel = i; pw.text = ""; message = ""; waitLeft = 0
        pw.forceActiveFocus()
    }
    function submit() {
        if (busy || waitLeft > 0 || !Host.up) return
        var name = who ? who.name : nameBox.text.trim()
        if (name === "") { nameBox.forceActiveFocus(); return }
        phase = "checking"; message = ""
        Host.signIn(name, pw.text, session)
    }
    onPeopleChanged: {
        for (var i = 0; i < people.length; i++) if (people[i].name === Host.last) { sel = i; break }
        if (sel >= people.length) sel = 0
    }
    Connections { target: Host
        function onChanged() { if (view.phase === "idle") view.session = Host.lastSession || "huginn" }
        function onAnswered(ok, why, wait) {
            if (view.phase !== "checking") return
            pw.text = ""
            if (ok) { view.phase = "wake"; wake.start(); return }
            view.phase = "idle"; view.message = why; view.waitLeft = wait
            if (why !== "") shake.restart()
            pw.forceActiveFocus()
        } }
    Timer { interval: 1000; running: true; repeat: true; onTriggered: {
            view.now = new Date()
            if (view.waitLeft > 0) {
                view.waitLeft--
                view.message = view.waitLeft === 0 ? "" : view.waitLeft >= 90 ? "Too many tries. Wait " + Math.round(view.waitLeft / 60) + " minutes."
                                                   : "Too many tries. Wait " + view.waitLeft + (view.waitLeft === 1 ? " second." : " seconds.")
            } } }

    // ------------------------------------------------------------------------------------------------ the wallpaper
    Item {
        id: sky
        anchors.fill: parent
        Rectangle { anchors.fill: parent
            gradient: Gradient { GradientStop { position: 0; color: Qt.darker(view.own.tintB, 1.5) } GradientStop { position: 1; color: Qt.darker(view.own.tintA, 1.25) } } }
        Loader { id: wall; anchors.fill: parent; active: Host.liveDir !== ""; source: Host.liveDir + "LiveWallpaper.qml"
            onLoaded: item.realm = view.realm }
    }
    // the foot of the screen a little darker, so the dock reads on any sky
    Rectangle { visible: view.main; anchors { left: parent.left; right: parent.right; bottom: parent.bottom } height: parent.height * 0.28; opacity: view.phase === "wake" ? 0 : 1
        Behavior on opacity { NumberAnimation { duration: 500 } }
        gradient: Gradient { GradientStop { position: 0; color: "transparent" } GradientStop { position: 1; color: Qt.rgba(0.03, 0.03, 0.06, 0.55) } } }

    component Glass: Rectangle {
        id: glass
        color: Qt.rgba(0.08, 0.08, 0.13, frost.status === Loader.Ready ? 0.36 : 0.62)
        border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.16)
        Loader { id: frost; z: -1; anchors.fill: parent
            active: wall.status === Loader.Ready && wall.item !== null && !wall.item.still
            source: "GreeterFrost.qml"
            onLoaded: { item.behind = sky; item.radius = Qt.binding(function () { return glass.radius })
                item.area = Qt.binding(function () { return Qt.rect(glass.x, glass.y, glass.width, glass.height) }) } }   // islands sit on the view, like the wallpaper
    }
    // someone's picture: theirs if they have one, else their initials on the realm's colour
    component Face: Item {
        id: f
        property var person: null
        property bool ring: false
        Rectangle { anchors.fill: parent; radius: width / 2; color: f.ring ? view.own.deep : Qt.rgba(1, 1, 1, 0.12)
            border.width: f.ring ? 2 : 1; border.color: f.ring ? view.own.accent : Qt.rgba(1, 1, 1, 0.22) }
        Text { anchors.centerIn: parent; visible: pic.status !== Image.Ready; text: view.initials(f.person ? f.person.full : ""); color: view.ink
            font { family: view.face; pixelSize: Math.round(f.width * 0.34); weight: Font.DemiBold } }
        Image { id: pic; anchors { fill: parent; margins: f.ring ? 3 : 1 } source: f.person ? f.person.face : ""; sourceSize: Qt.size(192, 192)
            fillMode: Image.PreserveAspectCrop; asynchronous: true; visible: false; layer.enabled: true }
        Rectangle { id: round; anchors.fill: pic; radius: width / 2; visible: false; layer.enabled: true }
        MultiEffect { anchors.fill: pic; visible: pic.status === Image.Ready; source: pic; maskEnabled: true; maskSource: round }
    }
    // the few line icons this screen needs, drawn here so it depends on nothing else
    component Mark: Canvas {
        id: mk
        property string name: ""
        property color tint: view.ink
        property real weight: 2
        width: 20; height: 20
        onTintChanged: requestPaint()
        readonly property var paths: ({ go: "M5 12h14M13 6l6 6-6 6", sleep: "M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z",
                                        restart: "M4 12a8 8 0 1 0 2.5-5.8M4 4v5h5", off: "M12 3v9M6.5 6.5a8 8 0 1 0 11 0" })
        onPaint: {
            var c = getContext("2d"), k = width / 24
            c.reset(); c.scale(k, k); c.strokeStyle = tint; c.lineWidth = weight; c.lineCap = "round"; c.lineJoin = "round"
            c.path = paths[name] || ""
            c.stroke()
        }
    }
    component RoundButton: Rectangle {
        id: rb
        property string mark: ""
        property string say: ""
        signal pressed()
        width: 48; height: 48; radius: 16
        color: area.pressed ? Qt.rgba(1, 1, 1, 0.24) : area.containsMouse ? Qt.rgba(1, 1, 1, 0.18) : Qt.rgba(1, 1, 1, 0.11)
        Accessible.role: Accessible.Button; Accessible.name: say
        Mark { anchors.centerIn: parent; name: rb.mark }
        MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; enabled: !view.busy; onClicked: rb.pressed() }
        Rectangle { visible: area.containsMouse; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.top; bottomMargin: 10 }
            width: tip.width + 20; height: 28; radius: 9; color: Qt.rgba(0.05, 0.05, 0.09, 0.9); border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.14)
            Text { id: tip; anchors.centerIn: parent; text: rb.say; color: view.ink; font { family: view.face; pixelSize: 12; weight: Font.Medium } } }
    }

    // --------------------------------------------------------------------------------------------------- the top bar
    Glass { visible: view.main; x: 20; y: 16; height: 44; radius: 22; width: brand.width + 36
        Text { id: brand; anchors.centerIn: parent; text: "HUGINN OS"; color: view.ink; font { family: view.face; pixelSize: 13; weight: Font.DemiBold; letterSpacing: 2 } } }
    Glass { visible: view.main; anchors { right: parent.right; rightMargin: 20 } y: 16; height: 44; radius: 22; width: status.width + 36
        Row { id: status; anchors.centerIn: parent; spacing: 16
            // which session: only when there's a choice (Game Mode installed); click to change
            Text { visible: Host.sessions.length > 1; anchors.verticalCenter: parent.verticalCenter; color: sessArea.containsMouse ? view.ink : view.soft
                font { family: view.face; pixelSize: 13; weight: Font.Medium }
                // (the desktop is "Desktop" here: the system's own name is already at the other end of the bar)
                text: { if (view.session === "huginn") return "Desktop"
                    for (var i = 0; i < Host.sessions.length; i++) if (Host.sessions[i].id === view.session) return Host.sessions[i].name; return "Desktop" }
                MouseArea { id: sessArea; anchors { fill: parent; margins: -12 } hoverEnabled: true; cursorShape: Qt.PointingHandCursor; enabled: !view.busy
                    onClicked: { var ids = Host.sessions.map(function (s) { return s.id }); view.session = ids[(ids.indexOf(view.session) + 1) % ids.length] } } }
            Text { visible: Host.battery >= 0; anchors.verticalCenter: parent.verticalCenter; text: Host.battery + "%"; color: view.ink; font { family: view.face; pixelSize: 13; weight: Font.Medium } }
            Text { anchors.verticalCenter: parent.verticalCenter; color: view.ink; font { family: view.face; pixelSize: 13; weight: Font.Medium }
                text: view.now.toLocaleDateString(Qt.locale(), "ddd d MMM") + "   " + view.clockText(false) } } }

    // ------------------------------------------------------------------------------------- the greeting and the time
    Column {
        id: clock
        visible: view.main
        x: view.withTiles ? Math.round(88 * view.k) : Math.round((parent.width - width) / 2)
        y: view.withTiles ? Math.round(tileBox.y - 12 * view.k) : Math.round(parent.height * 0.25)
        spacing: 6
        Text { id: greet; x: view.withTiles ? 0 : Math.round((clock.width - width) / 2); color: Qt.rgba(0.96, 0.96, 0.99, 0.88)
            font { family: view.face; pixelSize: Math.max(16, Math.round(view.height * 0.022)); weight: Font.Medium }
            text: view.phase === "wake" ? "Welcome back" + (view.who ? ", " + view.first(view.who.full) : "") : view.greeting() + (view.who ? ", " + view.first(view.who.full) : "") }
        Item { id: timeBox; x: view.withTiles ? -120 : Math.round((clock.width - width) / 2); width: timeText.width + 240; height: timeText.height + 80
            property real glow: 0       // 0…1: the realm's light coming up around the digits
            property real melt: 0       // 0…1: dissolving
            opacity: 1 - melt
            scale: 1 + 0.08 * melt
            Text { id: timeText; anchors.centerIn: parent; color: view.ink; text: view.clockText(true)
                font { family: view.face; pixelSize: Math.round(view.height * (view.withTiles ? 0.2 : 0.166)); weight: Font.Light; letterSpacing: -4 } }
            // (drawn in software, where the effect can't be: the time simply fades and grows a little)
            layer.enabled: view.phase === "wake" && GraphicsInfo.api !== GraphicsInfo.Software
            layer.effect: MultiEffect { autoPaddingEnabled: false
                blurEnabled: true; blurMax: 64; blur: timeBox.melt
                brightness: 0.25 * timeBox.glow
                shadowEnabled: true; shadowColor: view.own.glowA; shadowBlur: 1.0; shadowOpacity: timeBox.glow; shadowScale: 1 + 0.05 * timeBox.glow
                shadowHorizontalOffset: 0; shadowVerticalOffset: 0 } }
    }

    // ----------------------------------------------------------------------------------------------------- the widgets
    Item {
        id: tileBox
        visible: view.withTiles
        readonly property real cw: Math.round(280 * view.k)
        readonly property real ch: Math.round(150 * view.k)
        readonly property real gap: Math.round(16 * view.k)
        readonly property var places: view.pack(view.tiles)
        readonly property real room: dock.y - 24 * view.k - y               // down to just above the dock (and what it says)
        width: cw * 2 + gap
        height: room
        x: parent.width - width - Math.round(88 * view.k)
        y: Math.round(Math.max(84, parent.height * 0.15))
        Repeater { model: view.tiles
            GreeterTile { required property var modelData; required property int index
                readonly property var at: tileBox.places[index] || { row: 0, col: 0, w: 1, h: 1 }
                widget: modelData; now: view.now; battery: Host.battery; k: view.k; behind: sky; liveBehind: frostOk; locking: view.locking
                x: at.col * (tileBox.cw + tileBox.gap); y: at.row * (tileBox.ch + tileBox.gap)
                width: at.w * tileBox.cw + (at.w - 1) * tileBox.gap; height: at.h * tileBox.ch + (at.h - 1) * tileBox.gap
                visible: y + height <= tileBox.room } }       // more than fits: left off rather than under the dock
    }
    readonly property bool frostOk: wall.status === Loader.Ready && wall.item !== null && !wall.item.still

    // -------------------------------------------------------------------------------------------- what the service said
    Glass { visible: view.main && (view.message !== "" || !Host.up); anchors { horizontalCenter: dock.horizontalCenter; bottom: dock.top; bottomMargin: 14 }
        height: 36; radius: 18; width: said.width + 36
        Text { id: said; anchors.centerIn: parent; color: view.ink; font { family: view.face; pixelSize: 13; weight: Font.Medium }
            text: !Host.up ? "Starting up…" : view.message } }

    // ------------------------------------------------------------------------------------------------------- the dock
    Glass {
        id: dock
        visible: view.main
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 28 }
        width: Math.min(780, parent.width - 40); height: 80; radius: 28
        property real line: 0            // the light along its top edge: 0…1 across, then fading
        property real lineFade: 1

        // signing in
        Item { id: ask; anchors.fill: parent; opacity: 1
            Row { id: side; anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter } spacing: 12
                Repeater { model: view.people
                    Item { required property var modelData; required property int index; visible: index !== view.sel && shown < 4; width: visible ? 52 : 0; height: 52
                        readonly property int shown: index - (index > view.sel ? 1 : 0)          // the first four others fit
                        Face { anchors.fill: parent; person: modelData }
                        Accessible.role: Accessible.Button; Accessible.name: "Sign in as " + modelData.full
                        MouseArea { id: other; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: view.choose(index) }
                        Rectangle { visible: other.containsMouse; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.top; bottomMargin: 12 }
                            width: otherName.width + 20; height: 28; radius: 9; color: Qt.rgba(0.05, 0.05, 0.09, 0.9); border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.14)
                            Text { id: otherName; anchors.centerIn: parent; text: modelData.full; color: view.ink; font { family: view.face; pixelSize: 12; weight: Font.Medium } } } } }
                Rectangle { visible: view.people.length > 1; width: 1; height: 40; color: Qt.rgba(1, 1, 1, 0.2); anchors.verticalCenter: parent.verticalCenter }
                RoundButton { mark: "sleep"; say: "Sleep"; onPressed: Host.power("sleep") }
                RoundButton { visible: !view.locking; mark: "restart"; say: "Restart"; onPressed: Host.power("restart") }
                RoundButton { visible: !view.locking; mark: "off"; say: "Shut Down"; onPressed: Host.power("off") }
            }
            Rectangle { id: pill; height: 56; radius: 28; y: 12
                property real nudge: 0
                x: 14 + nudge; width: side.x - 12 - 14
                color: Qt.rgba(1, 1, 1, 0.10); border.width: 1; border.color: pw.activeFocus || nameBox.activeFocus ? view.own.accent : Qt.rgba(1, 1, 1, 0.3)
                SequentialAnimation { id: shake
                    NumberAnimation { target: pill; property: "nudge"; to: -10; duration: 50 }
                    NumberAnimation { target: pill; property: "nudge"; to: 9; duration: 70 }
                    NumberAnimation { target: pill; property: "nudge"; to: -6; duration: 70 }
                    NumberAnimation { target: pill; property: "nudge"; to: 4; duration: 60 }
                    NumberAnimation { target: pill; property: "nudge"; to: 0; duration: 60 } }
                Face { id: me; x: 4; y: 4; width: 48; height: 48; person: view.who; ring: true }
                Text { id: myName; visible: view.who !== null; anchors.verticalCenter: parent.verticalCenter; x: 64; text: view.who ? view.who.full : ""
                    width: Math.min(implicitWidth, pill.width * 0.4); elide: Text.ElideRight; color: view.ink; font { family: view.face; pixelSize: 15; weight: Font.DemiBold } }
                // nobody listed (every account hidden, or none yet): a name is typed
                TextInput { id: nameBox; visible: view.who === null; anchors.verticalCenter: parent.verticalCenter; x: 64; width: pill.width * 0.32; clip: true
                    color: view.ink; selectionColor: view.own.accent; font { family: view.face; pixelSize: 15; weight: Font.DemiBold }
                    Accessible.name: "Name"; KeyNavigation.tab: pw; onAccepted: pw.forceActiveFocus()
                    Text { visible: nameBox.text === ""; text: "Name"; color: Qt.rgba(0.96, 0.96, 0.99, 0.62); font: nameBox.font } }
                Item { id: field; anchors { left: view.who !== null ? myName.right : nameBox.right; leftMargin: 14; right: go.left; rightMargin: 8; verticalCenter: parent.verticalCenter } height: 44
                    TextInput { id: pw; objectName: "password"; anchors.fill: parent; verticalAlignment: TextInput.AlignVCenter; clip: true; focus: true
                        echoMode: TextInput.Password; passwordCharacter: "●"; passwordMaskDelay: 0
                        color: view.ink; selectionColor: view.own.accent; font { family: view.face; pixelSize: 15 }
                        enabled: !view.busy && view.waitLeft === 0; opacity: view.phase === "idle" ? 1 : 0
                        inputMethodHints: Qt.ImhHiddenText | Qt.ImhSensitiveData | Qt.ImhNoAutoUppercase | Qt.ImhNoPredictiveText
                        Accessible.name: "Password"; Accessible.passwordEdit: true
                        onAccepted: view.submit()
                        Keys.onEscapePressed: text = ""
                        Keys.onPressed: function (e) {
                            if (text !== "" || view.people.length < 2) return
                            if (e.key === Qt.Key_Left) { view.choose((view.sel + view.people.length - 1) % view.people.length); e.accepted = true }
                            else if (e.key === Qt.Key_Right) { view.choose((view.sel + 1) % view.people.length); e.accepted = true }
                        } }
                    Text { visible: pw.text === "" && view.phase === "idle"; anchors.verticalCenter: parent.verticalCenter; color: Qt.rgba(0.96, 0.96, 0.99, 0.62)
                        font { family: view.face; pixelSize: 15 }
                        text: view.waitLeft > 0 ? "Wait…" : "Password" }
                    // checking, and then right: the password is a line of the realm's light
                    Rectangle { id: light; anchors.verticalCenter: parent.verticalCenter; height: 2; radius: 1; color: view.own.accent
                        width: view.phase === "idle" ? 0 : parent.width; opacity: view.phase === "idle" ? 0 : 1
                        Behavior on width { NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
                        SequentialAnimation on opacity { running: view.phase === "checking"; loops: Animation.Infinite
                            NumberAnimation { to: 0.45; duration: 500 } NumberAnimation { to: 1; duration: 500 } } }
                }
                Rectangle { id: go; anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter } width: 44; height: 44; radius: 22
                    color: view.own.accent; opacity: view.waitLeft > 0 || !Host.up ? 0.45 : goArea.pressed ? 0.8 : 1
                    Accessible.role: Accessible.Button; Accessible.name: "Sign in"
                    Mark { anchors.centerIn: parent; name: "go"; tint: view.own.onAccent; weight: 2.4; width: 18; height: 18 }
                    MouseArea { id: goArea; anchors.fill: parent; cursorShape: Qt.PointingHandCursor; enabled: !view.busy; onClicked: view.submit() } }
            }
        }

        // waking: your picture in the middle, places for your apps lighting up either side
        Row { id: woke; anchors.centerIn: parent; spacing: 10; visible: view.phase === "wake"
            property real t: 0                                    // 0…1 through the lighting-up
            Repeater { model: 11
                Item { required property int index; readonly property bool mid: index === 5
                    readonly property int far: Math.abs(index - 5)             // 0 (you) … 5 (the ends)
                    readonly property real lit: Math.max(0, Math.min(1, woke.t * 6.5 - far))
                    width: mid ? meWide : 52; height: 56; anchors.verticalCenter: parent.verticalCenter
                    property real meWide: 64
                    Rectangle { visible: !parent.mid; anchors.centerIn: parent; width: 52; height: 52; radius: 14; opacity: parent.lit; scale: 0.7 + 0.3 * parent.lit
                        color: Qt.rgba(1, 1, 1, 0.16); border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.24) }
                    Item { visible: parent.mid; anchors.centerIn: parent; width: 56; height: 56; opacity: wokeMe.opacity
                        Rectangle { anchors.centerIn: parent; width: 76; height: 76; radius: 38; color: view.own.accent; opacity: 0.28 }
                        Face { anchors.fill: parent; person: view.who; ring: true } } } }
            Item { id: wokeMe; opacity: 0 }                              // (just holds the picture's fade)
        }
        // the line of light along the dock's top edge
        Rectangle { anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: -1 } height: 2; radius: 1; color: view.own.accent
            width: (parent.width - 120) * dock.line; opacity: dock.lineFade * (dock.line > 0 ? 1 : 0)
            Rectangle { anchors.centerIn: parent; width: parent.width; height: 14; radius: 7; color: view.own.accent; opacity: 0.25 } }
    }

    // ------------------------------------------------------------------------------------------------------ the wake
    SequentialAnimation {
        id: wake
        ParallelAnimation {
            NumberAnimation { target: ask; property: "opacity"; to: 0; duration: 220; easing.type: Easing.InCubic }
            SequentialAnimation { PauseAnimation { duration: 140 } NumberAnimation { target: wokeMe; property: "opacity"; from: 0; to: 1; duration: 220 } }
            SequentialAnimation { PauseAnimation { duration: 120 } NumberAnimation { target: dock; property: "line"; from: 0; to: 1; duration: 420; easing.type: Easing.OutCubic } }
            SequentialAnimation { PauseAnimation { duration: 300 } NumberAnimation { target: woke; property: "t"; from: 0; to: 1; duration: 520 } }
            SequentialAnimation { PauseAnimation { duration: 260 }
                NumberAnimation { target: timeBox; property: "glow"; from: 0; to: 1; duration: 300; easing.type: Easing.OutCubic }
                NumberAnimation { target: timeBox; property: "melt"; from: 0; to: 1; duration: 420; easing.type: Easing.InCubic } }
            SequentialAnimation { PauseAnimation { duration: 620 } NumberAnimation { target: greet; property: "opacity"; to: 0; duration: 360 } }
            SequentialAnimation { PauseAnimation { duration: 200 } NumberAnimation { target: tileBox; property: "opacity"; to: 0; duration: 420; easing.type: Easing.InCubic } }
            SequentialAnimation { PauseAnimation { duration: 700 } NumberAnimation { target: dock; property: "lineFade"; to: 0; duration: 380 } }
        }
        PauseAnimation { duration: 120 }
        ScriptAction { script: Host.done() }
    }
}
