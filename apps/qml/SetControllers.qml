import QtQuick

// Controllers: the game controllers connected now (looked at again every two seconds while this page shows), how
// each is connected and its battery, and a tester that lights each button, stick and trigger as it moves, read
// straight from the controller (huginn_pads.py). Pairing a wireless one is in Bluetooth.
Column {
    id: pg
    objectName: "controllersPage"
    width: parent ? parent.width : 600; spacing: 18
    readonly property var pads: (Backend.controllers.pads || [])
    readonly property var tester: Backend.padTester
    readonly property var st: tester ? tester.state : ({})
    property var testing: null              // the pad being tested
    Timer { interval: 2000; repeat: true; running: pg.visible; onTriggered: Backend.load("controllers") }
    onVisibleChanged: if (!visible && testing) { tester.stop(); testing = null }
    // the tested one went away
    onPadsChanged: if (testing && !pads.some(function (p) { return p.id === testing.id })) { tester.stop(); testing = null }

    function battery(p) {
        if (p.battery < 0) return ""
        return p.battery + "%" + (p.charging ? ", charging" : "")
    }
    function kindName(k) { return k === "sony" ? "PlayStation" : k === "xbox" ? "Xbox" : k === "nintendo" ? "Nintendo" : k === "steam" ? "Steam" : k === "8bitdo" ? "8BitDo" : "" }

    SetCard { title: "Connected"
        note: pg.pads.length ? "Steam may take a controller over while it's open (Steam Input) and set its buttons per game; the test below reads it as it is." : ""
        SetRow { visible: pg.pads.length === 0; glyph: "gamepad"; title: "No controller connected"
            sub: "Plug one in with its cable, or pair it in Bluetooth: hold its pairing button (Create and PS together on a DualSense, the small pair button on top of an Xbox controller) until its light flashes."
            chevron: true; onClicked: win.page = "bluetooth" }
        Repeater { model: pg.pads
            SetRow { required property var modelData
                objectName: "pad_" + modelData.id; glyph: "gamepad"; title: modelData.name
                sub: [pg.kindName(modelData.kind), modelData.conn, pg.battery(modelData)].filter(Boolean).join("  ·  ")
                Btn { objectName: "test_" + modelData.id; text: pg.testing && pg.testing.id === modelData.id ? "Testing" : "Test"
                    enabled: !(pg.testing && pg.testing.id === modelData.id)
                    onClicked: { pg.testing = modelData; Backend.testPad(modelData.path) } } } } }

    SetCard { visible: pg.testing !== null; title: pg.testing ? "Testing " + pg.testing.name : ""
        note: pg.st.error ? pg.st.error : "Press the buttons and move the sticks and triggers: each part lights as it moves. A stick that drifts shows its dot off the middle at rest."
        Item { width: parent.width; height: 290
            Item { id: v; width: 560; height: 280; anchors.horizontalCenter: parent.horizontalCenter; y: 6
                readonly property string kind: pg.testing ? pg.testing.kind : "other"
                readonly property var pressed: pg.st.pressed || []
                readonly property var axes: pg.st.axes || ({})
                function on(n) { return pressed.indexOf(n) >= 0 }
                function ax(n) { return axes[n] !== undefined ? axes[n] : 0 }
                // the face buttons' marks and colours by maker (positions are the kernel's: south, east, north, west)
                readonly property var face: kind === "sony"
                    ? { south: ["✕", "#7C9CF5"], east: ["○", "#E5484D"], north: ["△", "#3CC8B4"], west: ["□", "#E07AC8"] }
                    : kind === "nintendo"
                    ? { south: ["B", "#9AA3AF"], east: ["A", "#9AA3AF"], north: ["X", "#9AA3AF"], west: ["Y", "#9AA3AF"] }
                    : { south: ["A", "#3FB950"], east: ["B", "#E5484D"], north: ["Y", "#E0A33A"], west: ["X", "#4C8BF5"] }
                readonly property var names: kind === "sony" ? { lb: "L1", rb: "R1", lt: "L2", rt: "R2", select: "Create", start: "Options", home: "PS", ls: "L3", rs: "R3" }
                    : kind === "nintendo" ? { lb: "L", rb: "R", lt: "ZL", rt: "ZR", select: "−", start: "+", home: "Home", ls: "LS", rs: "RS" }
                    : kind === "xbox" ? { lb: "LB", rb: "RB", lt: "LT", rt: "RT", select: "View", start: "Menu", home: "Xbox", ls: "LS", rs: "RS" }
                    : { lb: "LB", rb: "RB", lt: "LT", rt: "RT", select: "Select", start: "Start", home: "Home", ls: "LS", rs: "RS" }

                // the body
                Rectangle { x: 40; y: 54; width: 480; height: 200; radius: 90; color: Theme.t.hover; border.width: 1; border.color: Theme.t.menu_border }
                // triggers (how far, 0 to 1) and bumpers
                Trigger { objectName: "padLT"; x: 70; y: 0; name: v.names.lt; amount: Math.max(v.ax("lt"), v.on("lt") ? 1 : 0) }
                Trigger { objectName: "padRT"; x: 390; y: 0; name: v.names.rt; amount: Math.max(v.ax("rt"), v.on("rt") ? 1 : 0) }
                Part { x: 70; y: 32; width: 100; height: 20; radius: 8; lit: v.on("lb"); text: v.names.lb }
                Part { x: 390; y: 32; width: 100; height: 20; radius: 8; lit: v.on("rb"); text: v.names.rb }
                // the d-pad: its buttons, or the hat axes some pads use instead
                Item { x: 92; y: 150; width: 84; height: 84
                    Part { x: 28; y: 0; width: 28; height: 30; radius: 6; lit: v.on("up") || v.ax("haty") < 0; text: "▲" }
                    Part { x: 28; y: 54; width: 28; height: 30; radius: 6; lit: v.on("down") || v.ax("haty") > 0; text: "▼" }
                    Part { x: 0; y: 28; width: 30; height: 28; radius: 6; lit: v.on("left") || v.ax("hatx") < 0; text: "◀" }
                    Part { x: 54; y: 28; width: 30; height: 28; radius: 6; lit: v.on("right") || v.ax("hatx") > 0; text: "▶" } }
                // sticks: where they point, and their click
                Stick { objectName: "padLS"; x: 104; y: 74; name: v.names.ls; dx: v.ax("lx"); dy: v.ax("ly"); click: v.on("ls") }
                Stick { objectName: "padRS"; x: 330; y: 154; name: v.names.rs; dx: v.ax("rx"); dy: v.ax("ry"); click: v.on("rs") }
                // face buttons
                Item { x: 380; y: 70; width: 96; height: 96
                    Face { objectName: "padSouth"; x: 34; y: 64; mark: v.face.south[0]; tint: v.face.south[1]; lit: v.on("south") }
                    Face { x: 68; y: 32; mark: v.face.east[0]; tint: v.face.east[1]; lit: v.on("east") }
                    Face { x: 34; y: 0; mark: v.face.north[0]; tint: v.face.north[1]; lit: v.on("north") }
                    Face { x: 0; y: 32; mark: v.face.west[0]; tint: v.face.west[1]; lit: v.on("west") } }
                // the middle three
                Part { x: 214; y: 92; width: 50; height: 20; radius: 10; lit: v.on("select"); text: v.names.select; small: true }
                Part { x: 296; y: 92; width: 50; height: 20; radius: 10; lit: v.on("start"); text: v.names.start; small: true }
                Part { x: 258; y: 128; width: 44; height: 28; radius: 14; lit: v.on("home"); text: v.names.home; small: true }
            } }
        SetRow { title: "Done testing"; Btn { objectName: "padDone"; text: "Done"; onClicked: { pg.tester.stop(); pg.testing = null } } } }

    SetCard { title: "Pairing and Steam"
        SetRow { title: "Pair a wireless controller"; sub: "In Bluetooth"; glyph: "bluetooth"; chevron: true; onClicked: win.page = "bluetooth" }
        SetRow { title: "Game Mode"; sub: "Steam's big-screen interface, made for a controller: in Games or the start menu"; glyph: "gamepad" } }

    // ------------------------------------------------------------ the drawn controller's parts
    component Part: Rectangle {
        property bool lit: false
        property string text: ""
        property bool small: false
        color: lit ? Theme.t.accent : Theme.t.menu_bg
        border.width: 1; border.color: lit ? Theme.t.accent : Theme.t.menu_border
        Label { anchors.centerIn: parent; text: parent.text; font.pixelSize: parent.small ? 9 : 11; font.weight: Font.DemiBold
            color: parent.lit ? "white" : Theme.t.text }
    }
    component Face: Rectangle {
        property string mark: ""
        property color tint: Theme.t.text
        property bool lit: false
        width: 30; height: 30; radius: 15
        color: lit ? tint : Theme.t.menu_bg
        border.width: 1.5; border.color: tint
        Label { anchors.centerIn: parent; text: parent.mark; font.pixelSize: 13; font.weight: Font.Bold; color: parent.lit ? "white" : parent.tint }
    }
    component Stick: Item {
        id: stick
        property string name: ""
        property real dx: 0
        property real dy: 0
        property bool click: false
        width: 64; height: 64
        Rectangle { anchors.fill: parent; radius: 32; color: Theme.t.menu_bg; border.width: 1; border.color: stick.click ? Theme.t.accent : Theme.t.menu_border }
        Rectangle { width: 1; height: parent.height - 16; anchors.centerIn: parent; color: Theme.t.menu_border }
        Rectangle { height: 1; width: parent.width - 16; anchors.centerIn: parent; color: Theme.t.menu_border }
        Rectangle { width: 22; height: 22; radius: 11; color: stick.click ? Theme.t.accent : Theme.t.text
            x: stick.width / 2 - 11 + stick.dx * 21; y: stick.height / 2 - 11 + stick.dy * 21 }
        Label { anchors.top: parent.bottom; anchors.topMargin: 2; anchors.horizontalCenter: parent.horizontalCenter
            text: stick.name + (Math.abs(stick.dx) > 0.02 || Math.abs(stick.dy) > 0.02 ? "  " + stick.dx.toFixed(2) + ", " + stick.dy.toFixed(2) : "")
            font.pixelSize: 9; secondary: true }
    }
    component Trigger: Item {
        id: trig
        property string name: ""
        property real amount: 0
        width: 100; height: 26
        Rectangle { anchors.fill: parent; radius: 8; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border; clip: true
            Rectangle { width: parent.width * Math.max(0, Math.min(1, trig.amount)); height: parent.height; color: Theme.t.accent; radius: 8 } }
        Label { anchors.centerIn: parent; text: trig.name + (trig.amount > 0.01 ? "  " + Math.round(trig.amount * 100) + "%" : ""); font.pixelSize: 11
            font.weight: Font.DemiBold; color: trig.amount > 0.5 ? "white" : Theme.t.text }
    }
}
