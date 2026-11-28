import QtQuick

// Printers & Scanners: the printers this computer can print to (network printers appear by themselves), which one
// apps use first, adding one by its address, and the scanners. Printing and scanning themselves are Print & Scan's.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property var p: Backend.printers
    readonly property bool looking: Backend.busy.indexOf("printers") >= 0
    SetCard { visible: pg.p.available === false
        SetRow { title: "Printing isn't available here"; sub: "CUPS, the system's printing service, isn't installed."; glyph: "printer" } }
    SetCard { visible: pg.p.available !== false; title: "Printers"
        note: (pg.p.printers || []).length ? "Printers on your network that need no driver (nearly all made since 2015) appear by themselves while they're switched on."
                                          : pg.looking ? "Looking for printers…" : "No printers yet. Switch one on and it appears here by itself, or add one by its address."
        Repeater { model: pg.p.printers || []
            SetRow { required property var modelData; title: modelData.label; glyph: "printer"; tile: modelData.ok ? "#0EA5E9" : "#9AA4B2"
                sub: (modelData.default ? "Used first · " : "") + modelData.state
                Row { spacing: 8
                    Btn { visible: !modelData.default; text: "Use First"; onClicked: Backend.makeDefaultPrinter(modelData.name) }
                    Seg { icon: "trash"; tip: "Remove"; onClicked: { var n = modelData.name, l = modelData.label
                        win.confirm("Remove “" + l + "”?", "A printer on the network may come back by itself while it's switched on.", "Remove", function () { Backend.removePrinter(n) }) } } } } }
        SetRow { title: "Add a printer by its address…"; sub: "For one on another network, or one that doesn't announce itself"; chevron: true
            onClicked: win.ask("Add a printer", "Its address is on the printer's own screen or its network page.", [{ key: "a", label: "Address", placeholder: "192.168.1.40 or printer.local" },
                                                                                                                   { key: "n", label: "Name (optional)" }], "Add",
                               function (v) { Backend.addPrinter(v.a, v.n) }) }
        SetRow { title: "Print queue"; sub: (pg.p.jobs || 0) ? pg.p.jobs + (pg.p.jobs === 1 ? " page waiting to print" : " things waiting to print") : "Nothing waiting to print"; chevron: true
            onClicked: Backend.openApp("print") } }
    SetCard { visible: pg.p.available !== false; title: "Scanners"
        note: (pg.p.scanners || []).length ? "" : pg.looking ? "Looking for scanners…" : "No scanner found. Most printers with a scanner show up here when they're switched on."
        Repeater { model: pg.p.scanners || []
            SetRow { required property var modelData; title: modelData.name; glyph: "scanner"; tile: "#14B8A6"
                Btn { text: "Scan…"; onClicked: Backend.openApp("scan") } } }
        SetRow { title: pg.looking ? "Looking…" : "Look again"; chevron: !pg.looking; onClicked: Backend.load("printers") } }
}
