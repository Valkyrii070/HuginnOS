import QtQuick

// Calculator, "whole island": the app is one rounded island with its own light.
GlassWindow {
    id: win
    title: "Calculator"; width: 340; height: sci ? 700 : 580; minimumWidth: 300; minimumHeight: sci ? 600 : 480; corner: 24; glow: "centre"; glowY: 0.16; padTop: 58
    property string sum: ""
    property string answer: ""
    property bool showHistory: false
    property bool sci: false                     // the scientific keys, above the others
    function toggleHistory() { showHistory = !showHistory }
    function toggleScientific() { sci = !sci }
    function copyAnswer() { var a = answer !== "" && !/[a-z]/i.test(answer) ? answer : live; if (a) { Backend.copy(a); toast.say("Copied " + a) } }
    function pasteSum() { var t = Backend.pasted(); if (t) { if (answer !== "") { sum = ""; answer = "" } sum += t } }
    readonly property string live: answer === "" ? Backend.preview(sum) : ""
    readonly property int padTopY: sci ? 238 : 118
    function press(k) {
        if (k === "C") { sum = ""; answer = "" }
        else if (k === "⌫") { if (answer !== "") { answer = "" } else sum = sum.replace(/(a?sin\(|a?cos\(|a?tan\(|ln\(|log\(|abs\(|.)$/, "") }
        else if (k === "=") { if (sum !== "") answer = Backend.solve(sum) }
        else if (k === "x²") press("^2")
        else if (k === "1/x") { if (answer !== "" && !/[a-z]/i.test(answer)) { sum = "1÷(" + answer.replace(/,/g, "") + ")"; answer = "" } else sum = "1÷(" + sum + ")" }
        else {
            // after an answer: a digit or a function starts a new sum, an operator carries on from the answer
            if (answer !== "") { sum = /^[0-9.(√πe]|^[a-z]/.test(k) || /[a-z]/i.test(answer) ? "" : answer.replace(/,/g, ""); answer = "" }
            sum += k
        }
    }
    toolbar: [ Seg { icon: "numbers"; tip: "Scientific keys"; on: win.sci; onClicked: win.sci = !win.sci },
               Seg { icon: "clock"; tip: "Earlier sums"; on: win.showHistory; onClicked: win.showHistory = !win.showHistory } ]
    Item { anchors.fill: parent; focus: true
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 12 } }
        Keys.onPressed: function (e) {
            var map = { "*": "×", "/": "÷", "-": "−" }, t = e.text
            if (e.modifiers & Qt.ControlModifier) {
                if (e.key === Qt.Key_C) win.copyAnswer(); else if (e.key === Qt.Key_V) win.pasteSum(); else return
                e.accepted = true; return
            }
            if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter || t === "=") win.press("=")
            else if (e.key === Qt.Key_Backspace) win.press("⌫")
            else if (e.key === Qt.Key_Escape) { if (win.showHistory) win.showHistory = false; else win.press("C") }
            else if ("0123456789.+()%^!".indexOf(t) >= 0 && t !== "") win.press(t)
            else if (map[t]) win.press(map[t])
            else if (t === "p") win.press("π")
            else if (/^[a-z]$/.test(t)) win.press(t)          // sin( and the rest can be typed
        }
        Label { x: 16; y: 14; width: parent.width - 32; horizontalAlignment: Text.AlignRight; text: win.sum || "0"; secondary: win.answer !== ""; font.pixelSize: win.answer !== "" ? 16 : 30; font.weight: Font.Light; elide: Text.ElideLeft }
        Label { x: 16; y: 58; width: parent.width - 32; horizontalAlignment: Text.AlignRight; elide: Text.ElideLeft
            text: win.answer !== "" ? win.answer : (win.live !== "" && win.live !== win.sum ? "= " + win.live : ""); font.pixelSize: win.answer !== "" ? (win.answer.length > 14 ? 20 : 34) : 16; font.weight: Font.Light; color: win.answer !== "" ? Theme.t.text : Theme.t.text_secondary }
        // the scientific keys (the toolbar's button, or View in the menu)
        Row { visible: win.sci; x: 12; y: 104; spacing: 6
            Repeater { model: [[true, "Deg"], [false, "Rad"]]
                Pressable { required property var modelData; width: 46; height: 24; radius: 12
                    color: Backend.degrees === modelData[0] ? Theme.t.accent : (hovered ? Theme.t.pressed : Theme.t.group); onClicked: Backend.setDegrees(modelData[0])
                    Label { anchors.centerIn: parent; text: modelData[1]; font.pixelSize: 11; font.weight: Font.DemiBold; color: Backend.degrees === modelData[0] ? Theme.t.onAccent : Theme.t.text } } } }
        Grid { id: sciPad; visible: win.sci; x: 12; y: 136; columns: 6; spacing: 6; width: parent.width - 24
            readonly property real cell: (width - 30) / 6
            Repeater { model: [["sin", "sin("], ["cos", "cos("], ["tan", "tan("], ["π", "π"], ["e", "e"], ["⌫", "⌫"],
                               ["ln", "ln("], ["log", "log("], ["√", "√("], ["xʸ", "^"], ["x²", "x²"], ["n!", "!"]]
                Pressable { required property var modelData; width: sciPad.cell; height: 42; radius: 12
                    color: hovered ? Theme.t.pressed : Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
                    onClicked: win.press(modelData[1])
                    Label { anchors.centerIn: parent; text: modelData[0]; font.pixelSize: 14; color: Theme.t.accent } } } }
        Grid { id: pad; x: 12; y: win.padTopY; columns: 4; spacing: 8; width: parent.width - 24
            readonly property real cell: (width - 24) / 4
            Repeater { model: ["C", "(", ")", "÷", "7", "8", "9", "×", "4", "5", "6", "−", "1", "2", "3", "+", "0", ".", "%", "="]
                Pressable { required property string modelData; width: pad.cell; height: (win.height - 58 - win.padTopY - 14 - 32) / 5; radius: 14
                    readonly property bool op: "÷×−+".indexOf(modelData) >= 0
                    color: modelData === "=" ? Theme.t.accent : (hovered ? Theme.t.pressed : (op || "C()%".indexOf(modelData) >= 0 ? Theme.t.hover : Theme.t.group)); border.width: 1; border.color: Theme.t.islandLine
                    onClicked: win.press(modelData)
                    Label { anchors.centerIn: parent; text: modelData; font.pixelSize: 20; color: modelData === "=" ? Theme.t.onAccent : (parent.op ? Theme.t.accent : Theme.t.text) } } } }
        Rectangle { visible: win.showHistory; anchors { fill: parent; margins: 10; topMargin: 0 } radius: 16; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.islandLine; clip: true
            Label { visible: Backend.history.length === 0; anchors.centerIn: parent; text: "Sums you finish appear here"; secondary: true }
            Btn { visible: Backend.history.length > 0; z: 2; anchors { right: parent.right; bottom: parent.bottom; margins: 10 } text: "Clear"; onClicked: Backend.clearHistory() }
            Flickable { anchors.fill: parent; contentHeight: hist.height + 50; clip: true
                Column { id: hist; width: parent.width
                    Repeater { model: Backend.history
                        Pressable { required property var modelData; width: hist.width; height: 54; radius: 0; onClicked: { win.sum = modelData.result.replace(/,/g, ""); win.answer = ""; win.showHistory = false }
                            Label { x: 16; y: 8; text: modelData.sum; secondary: true; font.pixelSize: 12 } Label { x: 16; y: 26; text: "= " + modelData.result; font.pixelSize: 16 }
                            Rectangle { anchors.bottom: parent.bottom; x: 16; width: parent.width - 16; height: 1; color: Theme.t.separator } } } } } }
    }
}
