import QtQuick
import QtQuick.Shapes

// One slide as Backend.slides gives it, drawn at its own size (1920 or 1440 by 1080 units) and scaled to the width
// it is given: the background, the design's frame, then every item where it is. Static: editing happens over it.
Item {
    id: face
    property var slide: ({ items: [], frameItems: [], bg: ({}) })
    property var look: Backend.look
    property real slideW: Backend.slideW
    property string hideText: ""            // the item being typed in: its text is the editor's
    property bool hints: false              // editing: empty placeholders say what goes in them
    property bool live: false               // presenting: builds start hidden
    property int step: 0                    // presenting: how many builds have come in
    property bool forward: true             // presenting: builds animate only going forward
    property var preview: ({})              // a drag in progress: id → {x, y, w, h, rot}
    readonly property real k: width / slideW
    readonly property var bg: slide && slide.bg ? slide.bg : (look ? look.bg : ({}))
    height: width * 1080 / slideW; clip: true

    function revealed(id) {
        if (!live || !slide || !slide.buildSeq) return 9999
        var n = 0, seq = slide.buildSeq
        for (var i = 0; i < Math.min(step, seq.length); i++) if (seq[i][0] === id) n++
        return n
    }

    Rectangle { anchors.fill: parent; color: face.bg.color || "#FFFFFF"; visible: !face.bg.from }
    Rectangle { anchors.fill: parent; visible: !!face.bg.from
        gradient: Gradient { orientation: (face.bg.angle || 0) % 180 === 0 ? Gradient.Horizontal : Gradient.Vertical
            GradientStop { position: 0; color: face.bg.from || "#FFFFFF" } GradientStop { position: 1; color: face.bg.to || face.bg.from || "#FFFFFF" } } }
    Image { anchors.fill: parent; visible: !!face.bg.url; source: face.bg.url || ""; fillMode: Image.PreserveAspectCrop; asynchronous: true; smooth: true }
    Rectangle { visible: face.look && face.look.deco === "orb"; width: face.width * 0.5; height: width; radius: width / 2; x: face.width * 0.68; y: -face.height * 0.45
        color: face.look && face.look.accents ? face.look.accents[0] : "transparent"; opacity: 0.10 }

    Item { width: face.slideW; height: 1080; scale: face.k; transformOrigin: Item.TopLeft
        Repeater { model: face.slide && face.slide.frameItems ? face.slide.frameItems : []; delegate: Bit {} }
        Repeater { model: face.slide ? face.slide.items : []; delegate: Bit {} } }

    component Bit: Item {
        id: bit
        required property var modelData
        readonly property var it: modelData
        readonly property var pv: face.preview[it.id]
        readonly property real iw: pv ? pv.w : it.w
        readonly property real ih: pv ? pv.h : it.h
        readonly property var steps: it.build || []
        readonly property int count: steps.length ? face.revealed(it.id) : 0
        readonly property bool wholeBuild: steps.length === 1 && steps[0] < 0
        readonly property bool shown: !face.live || !wholeBuild || count > 0
        readonly property string anim: it.anim ? it.anim.kind : ""
        readonly property int ms: it.anim && it.anim.ms ? it.anim.ms : 500
        x: pv ? pv.x : it.x; y: pv ? pv.y : it.y; width: iw; height: Math.max(ih, 0.01)
        rotation: pv && pv.rot !== undefined ? pv.rot : (it.rot || 0)
        opacity: shown ? 1 : 0
        Behavior on opacity { enabled: face.live && face.forward && bit.anim !== "appear"; NumberAnimation { duration: bit.ms; easing.type: Easing.OutCubic } }
        transform: [ Translate { y: bit.shown || bit.anim !== "rise" ? 0 : 60
                        Behavior on y { enabled: face.live && face.forward; NumberAnimation { duration: bit.ms; easing.type: Easing.OutCubic } } },
                     Scale { origin.x: bit.width / 2; origin.y: bit.height / 2; xScale: bit.shown || bit.anim !== "zoom" ? 1 : 0.6; yScale: xScale
                        Behavior on xScale { enabled: face.live && face.forward; NumberAnimation { duration: bit.ms; easing.type: Easing.OutCubic } } } ]

        Shape { anchors.fill: parent; visible: bit.it.kind === "shape"; preferredRendererType: Shape.CurveRenderer
            readonly property bool line: bit.it.shape === "line" || bit.it.shape === "arrowline"
            ShapePath { fillColor: parent.line ? "transparent" : (bit.it.fillHex || "transparent")
                strokeColor: parent.line ? (bit.it.lineHex || bit.it.fillHex || "#000000") : (bit.it.lineHex && bit.it.lineW ? bit.it.lineHex : "transparent")
                strokeWidth: parent.line ? (bit.it.lineW || 3) : (bit.it.lineW || 0); capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
                PathSvg { path: bit.pv ? Backend.shapePath(bit.it.shape || "rect", bit.iw, bit.ih, !!bit.it.flipH, !!bit.it.flipV) : (bit.it.path || "") } }
            ShapePath { fillColor: bit.it.shape === "arrowline" ? (bit.it.lineHex || bit.it.fillHex || "#000000") : "transparent"; strokeColor: "transparent"
                PathSvg { path: bit.it.shape === "arrowline" && !bit.pv ? (bit.it.head || "") : "" } } }
        Image { anchors.fill: parent; visible: bit.it.kind === "picture" || bit.it.kind === "table" || bit.it.kind === "chart"
            source: bit.it.kind === "picture" || bit.it.kind === "table" || bit.it.kind === "chart" ? (bit.it.url || "") : ""
            fillMode: Image.Stretch; asynchronous: true; smooth: true; mipmap: true }
        // the text: the item's own, a hint in an empty placeholder, or (presenting) as far as its paragraphs have been built
        Item { id: words; anchors.fill: parent; visible: face.hideText !== bit.it.id && bit.it.html !== undefined
            readonly property real fit: bit.it.fit || 1
            readonly property bool stepped: face.live && !!bit.it.stepHtml
            property int was: 0
            Connections { target: bit; enabled: !!bit.it.stepHtml
                function onCountChanged() { if (face.live && face.forward && bit.count > words.was) { overText.opacity = 0; reveal.restart() } else { words.was = bit.count; overText.opacity = 1 } } }
            NumberAnimation { id: reveal; target: overText; property: "opacity"; from: 0; to: 1; duration: bit.ms; easing.type: Easing.OutCubic
                onFinished: words.was = bit.count }
            Text { id: underText; visible: words.stepped && overText.opacity < 1; x: 14.4; y: overText.y; width: overText.width; scale: overText.scale; transformOrigin: Item.TopLeft
                textFormat: Text.RichText; wrapMode: Text.Wrap; text: words.stepped ? bit.it.stepHtml[Math.min(words.was, bit.it.stepHtml.length - 1)] : "" }
            Text { id: overText; x: 14.4; width: (bit.iw - 28.8) / parent.fit; scale: parent.fit; transformOrigin: Item.TopLeft
                textFormat: Text.RichText; wrapMode: Text.Wrap
                opacity: bit.it.empty && face.hints ? 0.42 : 1
                text: parent.stepped ? bit.it.stepHtml[Math.min(bit.count, bit.it.stepHtml.length - 1)]
                    : bit.it.empty ? (face.hints && bit.it.hint ? bit.it.hint : "") : (bit.it.html || "")
                y: bit.it.valign === "middle" ? (bit.ih - contentHeight * parent.fit) / 2 : bit.it.valign === "bottom" ? bit.ih - 7.2 - contentHeight * parent.fit : 7.2 } }
        // the theme's accent under a title
        Rectangle { visible: bit.it.role === "title" && !!face.look && (face.look.deco === "orb" || face.look.deco === "bar") && !!face.slide
                             && (face.slide.layout === "content" || face.slide.layout === "two" || face.slide.layout === "titleonly")
            x: 14.4; y: bit.ih + 4; width: 112; height: 8; radius: 4; color: face.look && face.look.accents ? face.look.accents[0] : "transparent" }
    }
}
