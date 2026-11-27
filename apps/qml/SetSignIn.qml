import QtQuick

// Settings › Sign-In Screen: widgets beside the time on the sign-in screen (none, to begin with), your own ways for it
// (greeted by name, where the time sits, the wake), and how it looks for everyone (realm, who the dock shows, light
// by day: those ask for an administrator's password).
// A picture of the sign-in screen on top, with your widgets where they'll be: drag one onto another's place to
// change the order. Below, each widget: whether it may show before you sign in, its size, Remove; and Add a Widget.
// They're yours (~/.config/huginn/signin-widgets.json), and this page is the only place they're changed: nobody at the
// sign-in screen can. The sign-in screen shows them from its next start (huginn_signin_widgets.py).
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property var s: Backend.signin
    readonly property var widgets: s.widgets || []
    readonly property var catalog: s.catalog || []
    readonly property var preview: s.preview || ({})
    readonly property int most: s.most || 6
    readonly property var remaining: catalog.filter(function (c) { return !widgets.some(function (w) { return w.kind === c.id }) })
    readonly property var realms: [["aurora", "Aurora"], ["bifrost", "Bifröst"], ["muspelheim", "Muspelheim"], ["niflheim", "Niflheim"]]
    readonly property var realmColours: ({ aurora: ["#0F2624", "#17192C", "#3DD6B5", "#7B61FF", "#43D9B8"], bifrost: ["#1D1932", "#2A1727", "#8E7BFF", "#FF7AB8", "#A995FF"],
                                           muspelheim: ["#2C1912", "#1F1718", "#FF8A4C", "#FFC857", "#FF8C50"], niflheim: ["#12212F", "#171A20", "#7CC4FF", "#CFEAFF", "#7CC4FF"] })
    readonly property var rc: realmColours[s.realm] || realmColours.aurora
    readonly property var opts: s.options || ({ greet: false, clock: "centre", wake: true })
    readonly property bool shared: s.canChangeRealm !== false
    function others() { var o = s.others || []; return o.length === 0 ? "Nobody else has an account here" : o.length === 1 ? o[0] : o.slice(0, -1).join(", ") + " and " + o[o.length - 1] }

    function info(kind) {
        for (var i = 0; i < catalog.length; i++) if (catalog[i].id === kind) return catalog[i]
        for (var j = 0; j < widgets.length; j++) if (widgets[j].kind === kind)       // an app's widget whose app has gone
            return { label: widgets[j].name || kind, sub: "Its app isn't installed any more", sizes: ["small", "wide", "tall"] }
        return { label: kind, sub: "", sizes: ["small"] }
    }
    function save(list) { Backend.setSigninWidgets(JSON.stringify(list)) }
    function copy() { return widgets.map(function (w) { var o = {}; for (var k in w) o[k] = w[k]; return o }) }
    function change(i, what) { var l = copy(); for (var k in what) l[i][k] = what[k]; save(l) }
    function remove(i) { var l = copy(); l.splice(i, 1); save(l) }
    function add(kind) { var c = info(kind), l = copy(); l.push({ kind: kind, size: c.size, before: c.before }); save(l) }
    function move(from, to) { if (from === to) return; var l = copy(); var w = l.splice(from, 1)[0]; l.splice(to, 0, w); save(l) }
    // the same packing as the sign-in screen's (shell/qml/GreeterView.qml): two columns, filled row by row
    function pack(list) {
        var used = [], out = []
        for (var i = 0; i < list.length; i++) {
            var w = list[i].size === "wide" ? 2 : 1, h = list[i].size === "tall" ? 2 : 1, done = false
            for (var r = 0; r < 12 && !done; r++) for (var c = 0; c + w <= 2 && !done; c++) {
                var ok = true
                for (var dr = 0; dr < h; dr++) for (var dc = 0; dc < w; dc++) if (used[(r + dr) * 2 + c + dc]) ok = false
                if (ok) { for (dr = 0; dr < h; dr++) for (dc = 0; dc < w; dc++) used[(r + dr) * 2 + c + dc] = true
                          out.push({ row: r, col: c, w: w, h: h }); done = true }
            }
        }
        return out
    }
    // what a widget would say now (the same words as the sign-in screen's, shortened)
    function line(w) {
        if (!w.before) return ["", "Private until you sign in"]
        var d = preview[w.kind] || {}
        if (w.kind === "today") { var e = (d.events || [])[0]; return e ? [e.title, e.time || ""] : d.events ? ["Nothing coming up", ""] : ["Your next event", "From Calendar"] }
        if (w.kind === "weather") return d.temp ? [d.temp + (d.words ? " and " + d.words.toLowerCase() : ""), d.high ? "High of " + d.high : ""] : ["No forecast yet", "Open Weather once"]
        if (w.kind === "pc") { var l = []; if (d.update) l.push(d.update); if (d.downloads > 0) l.push(d.downloads + (d.downloads === 1 ? " download" : " downloads") + " finished")
                               return [l[0] || "All quiet", l[1] || (l.length ? "" : "Nothing needs you")] }
        if (w.kind === "music") return d.title ? [d.title, d.sub || ""] : ["Nothing played yet", ""]
        if (w.kind.indexOf("app:") === 0) return d.big || d.rows ? [d.big || (d.rows && d.rows.length ? d.rows[0][1] : ""), d.small || ""] : ["Nothing yet", "The app fills it in"]
        return ["", ""]
    }

    // ----------------------------------------------------------------------------------------- the picture of it
    Rectangle {
        id: stage
        width: parent.width; height: Math.round(width * 900 / 1440); radius: 16; clip: true
        readonly property real k: width / 1440
        readonly property var places: pg.pack(pg.widgets)
        readonly property bool tiles: pg.widgets.length > 0
        readonly property bool atLeft: tiles || pg.opts.clock === "left"
        readonly property bool byDay: pg.s.light === true        // (shown light: what it looks like by day)
        gradient: Gradient { GradientStop { position: 0; color: stage.byDay ? "#DCE4EA" : Qt.darker(pg.rc[1], 1.5) } GradientStop { position: 1; color: stage.byDay ? "#B9C4CD" : Qt.darker(pg.rc[0], 1.25) } }
        border.width: 1; border.color: Theme.t.islandLine
        Rectangle { x: -stage.width * 0.1; y: stage.height * 0.3; width: stage.width * 1.3; height: stage.height * 0.18; radius: height / 2; rotation: -12; color: pg.rc[2]; opacity: 0.22 }
        Rectangle { x: -stage.width * 0.05; y: stage.height * 0.44; width: stage.width * 1.2; height: stage.height * 0.12; radius: height / 2; rotation: -12; color: pg.rc[3]; opacity: 0.16 }
        // the bar
        Rectangle { x: 20 * stage.k; y: 16 * stage.k; height: 44 * stage.k; width: 128 * stage.k; radius: height / 2; color: Qt.rgba(0.08, 0.08, 0.13, 0.6); border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.14)
            Text { anchors.centerIn: parent; text: "HUGINN OS"; color: "white"; font.pixelSize: Math.max(6, 13 * stage.k); font.weight: Font.DemiBold; font.letterSpacing: 1 } }
        // the time: in the middle, or at the left (beside the widgets, or as you chose)
        Column {
            x: stage.atLeft ? 88 * stage.k : (stage.width - width) / 2
            y: stage.tiles ? 120 * stage.k : stage.height * 0.25
            Text { objectName: "previewGreeting"; x: stage.atLeft ? 0 : (parent.width - width) / 2; text: "Good morning" + (pg.opts.greet && pg.s.me ? ", " + pg.s.me : "")
                color: stage.byDay ? Qt.rgba(0.08, 0.09, 0.12, 0.8) : Qt.rgba(1, 1, 1, 0.85); font.pixelSize: Math.max(7, 20 * stage.k) }
            Text { text: "9:41"; color: stage.byDay ? "#15171E" : "white"; font.pixelSize: (stage.tiles ? 180 : 150) * stage.k; font.weight: Font.Light }
        }
        // the widgets, where they'll be; drag one to another's place
        Item {
            id: grid
            x: stage.width - width - 88 * stage.k; y: 135 * stage.k
            readonly property real cw: 280 * stage.k
            readonly property real ch: 150 * stage.k
            readonly property real gap: 16 * stage.k
            width: cw * 2 + gap; height: stage.height - y - 140 * stage.k
            Repeater { model: pg.widgets
                Rectangle { id: t; objectName: "previewTile"
                    required property var modelData; required property int index
                    readonly property var at: stage.places[index] || { row: 0, col: 0, w: 1, h: 1 }
                    readonly property var words: pg.line(modelData)
                    function home() { x = Qt.binding(function () { return t.at.col * (grid.cw + grid.gap) })
                                      y = Qt.binding(function () { return t.at.row * (grid.ch + grid.gap) }) }
                    Component.onCompleted: home()
                    width: at.w * grid.cw + (at.w - 1) * grid.gap; height: at.h * grid.ch + (at.h - 1) * grid.gap
                    visible: y + height <= grid.height + 2 || drag.drag.active
                    z: drag.drag.active ? 10 : 0; opacity: drag.drag.active ? 0.85 : 1
                    radius: 24 * stage.k; color: Qt.rgba(0.08, 0.08, 0.13, 0.62); border.width: drag.containsMouse ? 1.5 : 1
                    border.color: drag.containsMouse ? pg.rc[4] : Qt.rgba(1, 1, 1, 0.16)
                    Text { x: 22 * stage.k; y: 18 * stage.k; text: pg.info(modelData.kind).label.toUpperCase(); color: Qt.rgba(1, 1, 1, 0.75)
                        font.pixelSize: Math.max(6, 12 * stage.k); font.weight: Font.DemiBold; font.letterSpacing: 1 }
                    Column { x: 22 * stage.k; width: parent.width - 44 * stage.k; anchors { bottom: parent.bottom; bottomMargin: 16 * stage.k } spacing: 2
                        Text { visible: t.words[0] !== ""; width: parent.width; elide: Text.ElideRight; text: t.words[0]; color: "white"; font.pixelSize: Math.max(8, 24 * stage.k); font.weight: Font.Medium }
                        Text { width: parent.width; elide: Text.ElideRight; text: t.words[1]; color: Qt.rgba(1, 1, 1, 0.75); font.pixelSize: Math.max(6, 13 * stage.k) } }
                    MouseArea { id: drag; anchors.fill: parent; hoverEnabled: true; cursorShape: drag.drag.active ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                        drag.target: t; drag.threshold: 4
                        onReleased: {
                            if (!drag.drag.active && Math.abs(t.x - t.at.col * (grid.cw + grid.gap)) < 4 && Math.abs(t.y - t.at.row * (grid.ch + grid.gap)) < 4) return
                            // dropped: the place whose middle is nearest takes it
                            var cx = t.x + t.width / 2, cy = t.y + t.height / 2, best = t.index, bd = 1e9
                            for (var i = 0; i < stage.places.length; i++) {
                                var p = stage.places[i], px = p.col * (grid.cw + grid.gap) + (p.w * grid.cw + (p.w - 1) * grid.gap) / 2
                                var py = p.row * (grid.ch + grid.gap) + (p.h * grid.ch + (p.h - 1) * grid.gap) / 2
                                var dd = (px - cx) * (px - cx) + (py - cy) * (py - cy)
                                if (dd < bd) { bd = dd; best = i }
                            }
                            t.home()
                            pg.move(t.index, best)
                        } } } }
        }
        // the dock you sign in with
        Rectangle { anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 28 * stage.k }
            width: 780 * stage.k; height: 80 * stage.k; radius: 28 * stage.k; color: Qt.rgba(0.08, 0.08, 0.13, 0.6); border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.16)
            Rectangle { x: 14 * stage.k; anchors.verticalCenter: parent.verticalCenter; width: 430 * stage.k; height: 56 * stage.k; radius: height / 2
                color: Qt.rgba(1, 1, 1, 0.1); border.width: 1; border.color: pg.rc[4]
                Rectangle { x: 4 * stage.k; anchors.verticalCenter: parent.verticalCenter; width: 48 * stage.k; height: width; radius: width / 2; color: Qt.darker(pg.rc[4], 3); border.width: 1.5; border.color: pg.rc[4] } }
            Row { anchors { right: parent.right; rightMargin: 14 * stage.k; verticalCenter: parent.verticalCenter } spacing: 12 * stage.k
                Repeater { model: 3; Rectangle { width: 48 * stage.k; height: width; radius: 16 * stage.k; color: Qt.rgba(1, 1, 1, 0.11) } } } }
        Text { visible: !stage.tiles; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 130 * stage.k }
            text: pg.opts.clock === "left" ? "No widgets: the time sits at the left" : "No widgets: the time stays in the middle"
            color: stage.byDay ? Qt.rgba(0.08, 0.09, 0.12, 0.7) : Qt.rgba(1, 1, 1, 0.7); font.pixelSize: 12 }
    }
    Label { text: pg.widgets.length > 1 ? "Drag a widget onto another's place to change the order." : "Add a widget and it appears beside the time."
        secondary: true; font.pixelSize: 12; topPadding: -10 }

    // ------------------------------------------------------------------------------------------------- the widgets
    SetCard { title: "Widgets"
        note: "Before sign-in on: the widget shows what your desktop last saw, so anyone at this computer can read it. Off: it shows its name and a lock, nothing more. Only you can change any of this, here, once you've signed in. Apps can bring widgets of their own: they're in Add a widget."
        Repeater { model: pg.widgets
            SetRow { required property var modelData; required property int index; objectName: "widgetRow"
                title: pg.info(modelData.kind).label; sub: pg.info(modelData.kind).sub
                Row { spacing: 10
                    Label { text: "Before sign-in"; secondary: true; font.pixelSize: 11; anchors.verticalCenter: parent.verticalCenter }
                    Toggle { objectName: "beforeToggle"; on: modelData.before; anchors.verticalCenter: parent.verticalCenter; onToggled: function (v) { pg.change(index, { before: v }) } }
                    SetChoice { visible: pg.info(modelData.kind).sizes.length > 1; anchors.verticalCenter: parent.verticalCenter; each: 54
                        options: pg.info(modelData.kind).sizes.map(function (z) { return [z, z.charAt(0).toUpperCase() + z.slice(1)] })
                        value: modelData.size; onPicked: function (v) { pg.change(index, { size: v }) } }
                    Btn { text: "Remove"; anchors.verticalCenter: parent.verticalCenter; onClicked: pg.remove(index) } } } }
        SetRow { visible: pg.remaining.length > 0 && pg.widgets.length < pg.most; objectName: "addWidget"
            title: "Add a widget"; sub: pg.remaining.map(function (c) { return c.label }).join(", "); glyph: "plus"; chevron: true
            onClicked: win.pick("Add a Widget", pg.remaining.map(function (c) { return { id: c.id, label: c.label, sub: c.sub } }), "", function (v) { pg.add(String(v)) }) }
    }

    // ------------------------------------------------------------------------------------------- before sign-in
    SetCard { title: "Before sign-in"; note: "Who the dock shows is the same for everyone who uses this computer, so changing it asks for an administrator's password."
        SetRow { title: "Greet me by name"; sub: "“Good morning" + (pg.s.me ? ", " + pg.s.me : "") + "” instead of “Good morning”. Anyone at the computer reads it."
            Toggle { objectName: "greetToggle"; on: pg.opts.greet === true; onToggled: function (v) { Backend.setSigninOption("greet", v ? "true" : "false") } } }
        SetRow { title: "Who the dock shows"
            sub: pg.s.people === "none" ? "No one: everyone types their name, then their password"
                 : pg.s.people === "last" ? "Whoever signed in last; anyone else chooses Someone else and types their name"
                 : "Everyone: " + (pg.s.me || "you") + (pg.s.others && pg.s.others.length ? ", " + pg.others() : "")
            SetChoice { objectName: "peopleChoice"; enabled: pg.shared; each: 74; options: [["all", "Everyone"], ["last", "Last"], ["none", "No one"]]; value: pg.s.people || "all"
                onPicked: function (v) { if (v !== (pg.s.people || "all")) Backend.setSigninShared("people", v) } } } }

    // ---------------------------------------------------------------------------------------------------- the look
    SetCard { title: "Look"; note: "The realm and light by day are the same for everyone who uses this computer, so changing them asks for an administrator's password."
        SetRow { title: "Realm"; sub: "The living wallpaper behind the sign-in screen"
            SetPick { enabled: pg.shared
                text: { for (var i = 0; i < pg.realms.length; i++) if (pg.realms[i][0] === pg.s.realm) return pg.realms[i][1]; return "Aurora" }
                onClicked: win.pick("Sign-In Screen Realm", pg.realms.map(function (r) { return { id: r[0], label: r[1] } }), pg.s.realm, function (v) { Backend.setSigninRealm(String(v)) }) } }
        SetRow { title: "Light by day"; sub: "Light from sunrise to sunset here, dark at night"
            Toggle { objectName: "dayToggle"; enabled: pg.shared; on: pg.s.light === true; onToggled: function (v) { Backend.setSigninShared("day", v ? "on" : "off") } } }
        SetRow { title: "The time"; sub: pg.widgets.length ? "With widgets it sits at the left, beside them" : "Where it sits when you have no widgets"
            SetChoice { objectName: "clockChoice"; enabled: pg.widgets.length === 0; each: 74; options: [["centre", "Centre"], ["left", "Left"]]; value: pg.widgets.length ? "left" : pg.opts.clock
                onPicked: function (v) { Backend.setSigninOption("clock", v) } } } }

    // ------------------------------------------------------------------------------------------------ waking up
    SetCard { title: "Waking up"; note: pg.s.still ? "Reduce Motion is on in Accessibility, so the wake is a plain fade." : "With Reduce Motion on in Accessibility, the wake is a plain fade."
        SetRow { title: "Play the wake when I sign in"; sub: "The dock fills with places for your apps and the time blooms away. Off: the sign-in screen simply fades."
            Toggle { objectName: "wakeToggle"; enabled: !pg.s.still; on: pg.opts.wake !== false && !pg.s.still; onToggled: function (v) { Backend.setSigninOption("wake", v ? "true" : "false") } } } }
}
