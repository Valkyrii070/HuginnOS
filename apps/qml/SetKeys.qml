import QtQuick

// Keyboard Shortcuts: Huginn's own, each of which can have other keys or none; your own, opening an app or running a
// command; and the few that stay as they are. While new keys are being pressed the desktop's shortcuts wait, so
// pressing Super+E here is taken as Super+E and doesn't open Files.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property var k: Backend.keys
    property string listening: ""            // the shortcut whose keys are being pressed; "own" for a new one of your own
    property string ownRun: ""
    property string ownName: ""
    readonly property var groups: { var out = []; (k.items || []).forEach(function (r) { if (out.indexOf(r.group) < 0) out.push(r.group) }); return out }
    Component.onDestruction: if (listening) Backend.listenForKeys(false)

    function cap(name) {
        return ({ period: ".", comma: ",", minus: "−", equal: "=", plus: "+", slash: "/", semicolon: ";", apostrophe: "'", grave: "`", bracketleft: "[",
                  bracketright: "]", backslash: "\\", Left: "←", Right: "→", Up: "↑", Down: "↓", Space: "Space", KP_Add: "+ (keypad)", KP_Subtract: "− (keypad)",
                  KP_0: "0 (keypad)", Prior: "Page Up", Next: "Page Down", Return: "Enter" })[name]
            || ({ period: ".", comma: ",", minus: "−", equal: "=", plus: "+", slash: "/", semicolon: ";", apostrophe: "'", grave: "`", bracketleft: "[",
                  bracketright: "]", backslash: "\\", space: "Space", kp_add: "+ (keypad)", kp_subtract: "− (keypad)", kp_0: "0 (keypad)" })[name.toLowerCase()] || name
    }
    function caps(combo) { return combo ? combo.split("+").map(cap) : [] }
    function listen(id) { listening = id; Backend.listenForKeys(true); catcher.forceActiveFocus() }
    function stop() { listening = ""; Backend.listenForKeys(false) }
    function keyName(e) {
        var q = e.key
        if (q >= Qt.Key_A && q <= Qt.Key_Z) return String.fromCharCode(q)
        if (q >= Qt.Key_0 && q <= Qt.Key_9) return String.fromCharCode(q)
        if (q >= Qt.Key_F1 && q <= Qt.Key_F24) return "F" + (q - Qt.Key_F1 + 1)
        var named = {}
        named[Qt.Key_Left] = "Left"; named[Qt.Key_Right] = "Right"; named[Qt.Key_Up] = "Up"; named[Qt.Key_Down] = "Down"
        named[Qt.Key_Space] = "space"; named[Qt.Key_Tab] = "Tab"; named[Qt.Key_Return] = "Return"; named[Qt.Key_Enter] = "Return"; named[Qt.Key_Print] = "Print"
        named[Qt.Key_Home] = "Home"; named[Qt.Key_End] = "End"; named[Qt.Key_PageUp] = "Prior"; named[Qt.Key_PageDown] = "Next"; named[Qt.Key_Delete] = "Delete"
        named[Qt.Key_Insert] = "Insert"; named[Qt.Key_Period] = "period"; named[Qt.Key_Comma] = "comma"; named[Qt.Key_Minus] = "minus"; named[Qt.Key_Equal] = "equal"
        named[Qt.Key_Slash] = "slash"; named[Qt.Key_Semicolon] = "semicolon"; named[Qt.Key_Apostrophe] = "apostrophe"; named[Qt.Key_QuoteLeft] = "grave"
        named[Qt.Key_BracketLeft] = "bracketleft"; named[Qt.Key_BracketRight] = "bracketright"; named[Qt.Key_Backslash] = "backslash"; named[Qt.Key_Pause] = "Pause"
        named[Qt.Key_ScrollLock] = "Scroll_Lock"; named[Qt.Key_Plus] = "plus"; named[Qt.Key_Greater] = "period"; named[Qt.Key_Less] = "comma"
        return named[q] || ""
    }

    // takes the keys while listening (nothing else has the keyboard then)
    Item { id: catcher; width: 1; height: 1
        Keys.onPressed: function (e) {
            e.accepted = true
            if (!pg.listening) return
            if ([Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_Super_L, Qt.Key_Super_R, Qt.Key_AltGr].indexOf(e.key) >= 0) return   // wait for the key itself
            var mods = []
            if (e.modifiers & Qt.ControlModifier) mods.push("Ctrl")
            if (e.modifiers & Qt.AltModifier) mods.push("Alt")
            if (e.modifiers & Qt.ShiftModifier) mods.push("Shift")
            if (e.modifiers & Qt.MetaModifier) mods.push("Super")
            if (e.key === Qt.Key_Escape && !mods.length) { pg.stop(); return }
            if (e.key === Qt.Key_Backspace && !mods.length) { if (pg.listening !== "own") Backend.setShortcut(pg.listening, ""); pg.stop(); return }
            var name = pg.keyName(e)
            if (!name) return
            var plain = !mods.length || (mods.length === 1 && mods[0] === "Shift")
            if (plain && !/^F\d+$|^Print$|^Pause$|^Scroll_Lock$/.test(name)) { win.say("Hold Super, Ctrl or Alt with it, so typing that key still types it."); return }
            var combo = mods.concat([name]).join("+")
            if (pg.listening === "own") Backend.addOwnShortcut(pg.ownRun, pg.ownName, combo)
            else Backend.setShortcut(pg.listening, combo)
            pg.stop()
        }
        onActiveFocusChanged: if (!activeFocus && pg.listening) pg.stop()
    }

    component Keycaps: Row {
        property var keys: []
        spacing: 3
        Repeater { model: parent.keys
            Rectangle { required property string modelData; height: 24; width: Math.max(24, t.width + 14); radius: 6; anchors.verticalCenter: parent.verticalCenter
                color: Theme.t.dark ? "#22FFFFFF" : "#10141E28"; border.width: 1; border.color: Theme.t.separator
                Label { id: t; anchors.centerIn: parent; text: modelData; font.pixelSize: 11; font.weight: Font.DemiBold } } }
    }
    component Listening: Label { text: "Press the new keys…  Esc: as it was  ·  Backspace: off"; color: Theme.t.accent; font.pixelSize: 12 }

    Repeater { model: pg.groups
        SetCard { required property string modelData; title: modelData
            Repeater { model: (pg.k.items || []).filter(function (r) { return r.group === modelData })
                SetRow { required property var modelData; title: modelData.label
                    Row { spacing: 8
                        Listening { visible: pg.listening === modelData.id; anchors.verticalCenter: parent.verticalCenter }
                        Repeater { model: pg.listening === modelData.id ? [] : modelData.keys.slice(0, 2)
                            Keycaps { required property string modelData; keys: pg.caps(modelData); anchors.verticalCenter: parent.verticalCenter } }
                        Label { visible: pg.listening !== modelData.id && modelData.keys.length === 0; text: "Off"; secondary: true; anchors.verticalCenter: parent.verticalCenter }
                        Seg { text: "Change"; on: pg.listening === modelData.id; onClicked: pg.listening === modelData.id ? pg.stop() : pg.listen(modelData.id) }
                        Seg { visible: modelData.changed; text: "Reset"; onClicked: Backend.resetShortcut(modelData.id) } } } } } }

    SetCard { title: "Your own"
        Repeater { model: pg.k.own || []
            SetRow { required property var modelData; title: modelData.name; sub: modelData.run.indexOf("app:") === 0 ? "Opens the app" : modelData.run; picture: modelData.icon || ""
                Row { spacing: 8
                    Keycaps { keys: pg.caps(modelData.keys); anchors.verticalCenter: parent.verticalCenter }
                    Seg { icon: "trash"; tip: "Remove this shortcut"; onClicked: Backend.removeOwnShortcut(modelData.run) } } } }
        SetRow { title: "Open an app"; sub: "Choose the app, then press its keys"
            Row { spacing: 8
                Listening { visible: pg.listening === "own" && pg.ownRun.indexOf("app:") === 0; anchors.verticalCenter: parent.verticalCenter }
                SetPick { text: "Choose…"
                    onClicked: win.pick("A shortcut to open", (pg.k.apps || []).map(function (a) { return { id: a.id, label: a.name, icon: a.icon } }), "",
                                        function (v) { var a = pg.k.apps.filter(function (x) { return x.id === v })[0]; pg.ownRun = "app:" + v; pg.ownName = a ? a.name : v; pg.listen("own") }) } } }
        SetRow { title: "Run a command"; sub: "For example: steam, or flatpak run com.discordapp.Discord"
            Row { spacing: 8
                Listening { visible: pg.listening === "own" && pg.ownRun.indexOf("app:") !== 0; anchors.verticalCenter: parent.verticalCenter }
                TextBox { id: cmd; visible: !(pg.listening === "own" && pg.ownRun.indexOf("app:") !== 0); width: 220; height: 30; placeholder: "Command"
                    onAccepted: if (text.trim()) { pg.ownRun = text.trim(); pg.ownName = text.trim().split(" ")[0]; pg.listen("own"); text = "" } }
                Seg { text: "Keys…"; onClicked: if (cmd.text.trim()) { pg.ownRun = cmd.text.trim(); pg.ownName = cmd.text.trim().split(" ")[0]; pg.listen("own"); cmd.text = "" } } } } }

    SetCard { title: "Always the same"
        Repeater { model: pg.k.fixed || []
            SetRow { required property var modelData; title: modelData.label
                Keycaps { keys: modelData.keys.split("+").map(pg.cap) } } }
        SetRow { title: "Put Huginn's shortcuts back as they came"; Seg { text: "Reset All"; onClicked: Backend.resetAllShortcuts() } } }
}
