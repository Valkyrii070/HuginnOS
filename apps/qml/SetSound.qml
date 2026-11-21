import QtQuick

// Sound: where sound goes and comes from, how loud, and each app playing right now.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property var s: Backend.sound
    readonly property var out: (s.outputs || []).filter(function (e) { return e.default })[0] || null
    readonly property var mic: (s.inputs || []).filter(function (e) { return e.default })[0] || null
    SetCard { visible: pg.s.available === false
        SetRow { title: "Sound can't be changed here"; sub: "pactl isn't installed (it comes with pulseaudio-utils), so PipeWire can't be reached."; glyph: "volume" } }
    SetCard { visible: pg.out !== null; title: "Output"
        SetRow { title: "Play sound through"; sub: pg.out ? pg.out.port : ""
            SetPick { text: pg.out ? pg.out.label : ""; onClicked: win.pick("Play sound through", pg.s.outputs.map(function (e) { return { id: e.name, label: e.label, sub: e.port } }), pg.out.name,
                                                                         function (v) { Backend.setDefaultDevice("outputs", v) }) } }
        SetRow { title: "Volume"
            Row { spacing: 10
                Seg { icon: pg.out && pg.out.mute ? "x" : "volume"; tip: pg.out && pg.out.mute ? "Unmute" : "Mute"; onClicked: Backend.setMute("outputs", pg.out.name, !pg.out.mute) }
                SetSlider { width: 260; anchors.verticalCenter: parent.verticalCenter; value: pg.out ? pg.out.volume / 100 : 0; highText: pg.out ? Math.round(live * 100) + "%" : ""
                    onMoved: function (v) { Backend.setVolume("outputs", pg.out.name, Math.round(v * 100)) } }
                Seg { icon: "play"; tip: "Play a test sound"; onClicked: Backend.testSound() } } } }
    SetCard { visible: pg.mic !== null; title: "Input"
        SetRow { title: "Listen through"; sub: pg.mic ? pg.mic.port : ""
            SetPick { text: pg.mic ? pg.mic.label : ""; onClicked: win.pick("Listen through", pg.s.inputs.map(function (e) { return { id: e.name, label: e.label, sub: e.port } }), pg.mic.name,
                                                                         function (v) { Backend.setDefaultDevice("inputs", v) }) } }
        SetRow { title: "Input level"
            Row { spacing: 10
                Seg { icon: pg.mic && pg.mic.mute ? "x" : "mic"; tip: pg.mic && pg.mic.mute ? "Unmute" : "Mute"; onClicked: Backend.setMute("inputs", pg.mic.name, !pg.mic.mute) }
                SetSlider { width: 260; anchors.verticalCenter: parent.verticalCenter; value: pg.mic ? pg.mic.volume / 100 : 0; highText: pg.mic ? Math.round(live * 100) + "%" : ""
                    onMoved: function (v) { Backend.setVolume("inputs", pg.mic.name, Math.round(v * 100)) } } } } }
    SetCard { id: alerts; title: "Alerts"; note: "The alert sound is what an app's bell plays (a terminal's beep, a question that needs an answer). Accessibility can flash the screen instead."
        readonly property var fx: pg.s.effects || ({})
        readonly property var names: { var o = {}; (pg.s.alerts || []).forEach(function (a) { o[a.id] = a.label }); return o }
        SetRow { title: "Alert sound"; glyph: "bell"; tile: "#C2185B"
            Row { spacing: 8
                SetPick { objectName: "alertPick"; text: alerts.names[alerts.fx.alert || "bell"] || "Bell"
                    onClicked: win.pick("Alert sound", (pg.s.alerts || []).map(function (a) { return { id: a.id, label: a.label } }), (pg.s.effects || {}).alert || "bell",
                                        function (v) { Backend.setSoundEffect("alert", v) }) }
                Seg { icon: "play"; tip: "Play it"; onClicked: Backend.tryAlert((pg.s.effects || {}).alert || "bell") } } }
        SetRow { title: "Alert volume"
            SetSlider { width: 240; glyphLeft: "volume"; value: (pg.s.effects || {}).alertVolume !== undefined ? pg.s.effects.alertVolume : 0.7
                onMoved: function (v) { Backend.setSoundEffect("alertVolume", Math.round(v * 100) / 100) } } }
        SetRow { title: "A click when the volume keys change it"; sub: "So you hear how loud it is"
            Toggle { on: (pg.s.effects || {}).volumeFeedback !== false; onToggled: function (v) { Backend.setSoundEffect("volumeFeedback", v) } } }
        SetRow { title: "Notification sounds"; sub: "Which apps make a sound is in Notifications"; chevron: true; onClicked: win.go("notifications") } }
    SetCard { visible: pg.s.available !== false; title: "Apps playing now"; note: (pg.s.apps || []).length ? "Each app's own volume, on top of the main one." : "Nothing is playing sound right now."
        Repeater { model: pg.s.apps || []
            SetRow { required property var modelData; title: modelData.app; sub: modelData.what; glyph: "music"; tile: "#C2185B"
                Row { spacing: 10
                    Seg { icon: modelData.mute ? "x" : "volume"; onClicked: Backend.setAppMute(modelData.index, !modelData.mute) }
                    SetSlider { width: 200; anchors.verticalCenter: parent.verticalCenter; value: modelData.volume / 100; onMoved: function (v) { Backend.setAppVolume(modelData.index, Math.round(v * 100)) } } } } } }
}
