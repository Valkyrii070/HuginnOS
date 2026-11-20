import QtQuick
import QtQuick.Particles
import QtMultimedia

// A live wallpaper someone made (Settings › Appearance › Wallpaper › Make one), from its wallpaper.json:
//
//   base      "scene": a realm's scene (one of the shaders here) in colours of their own
//             "picture": a picture of theirs, drifting slowly or breathing (a slow zoom), or still
//             "video": a video of theirs, looping without sound
//   effects   on top, any of: snow, rain, stars, fireflies, lights (out of focus), leaves, embers
//   amount    how many (0…1); pace: how fast everything goes (0.25…3); shade: darkens the base (0…0.6)
//   effectColour  the effects' colour ("" for each one's own)
//
// `moving` false pauses everything where it is (Reduce Motion, a window filling the screen, the setting off); the
// desktop, the Settings preview and anything else show it through this one file.
Item {
    id: cw
    property var spec: ({})
    property url folder: ""                 // the wallpaper's own folder (its picture or video is in it), ending in /
    property bool moving: true
    property real time: 30.0
    readonly property string base: spec.base || "scene"
    readonly property real pace: Math.max(0.1, Math.min(3, Number(spec.pace || 1)))
    readonly property real amount: Math.max(0, Math.min(1, spec.amount === undefined ? 0.5 : Number(spec.amount)))
    readonly property var effects: spec.effects || []
    readonly property real k: Math.max(0.25, height / 1080)          // particle sizes follow the screen's height
    readonly property bool gpu: [GraphicsInfo.OpenGL, GraphicsInfo.Vulkan, GraphicsInfo.Metal, GraphicsInfo.Direct3D11,
                                 GraphicsInfo.Direct3D12].indexOf(GraphicsInfo.api) >= 0
    readonly property var colours: spec.colours || ({})
    function has(e) { return effects.indexOf(e) >= 0 }
    function tint(own) { return spec.effectColour ? spec.effectColour : own }
    function file(name) { var f = spec.folder || folder; return name && String(f) !== "" ? (String(f) + name) : "" }
    clip: true

    FrameAnimation {
        running: cw.visible && cw.moving
        onTriggered: cw.time += Math.min(frameTime, 0.1) * cw.pace
    }

    // ------------------------------------------------------------------------- the base
    Rectangle {      // under everything: the colours themselves (also all there is without a graphics card)
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0; color: cw.colours.tintA || "#0F2624" }
            GradientStop { position: 0.55; color: Qt.darker(cw.colours.tintB || "#17192C", 1.15) }
            GradientStop { position: 1; color: cw.colours.tintB || "#17192C" }
        }
    }
    ShaderEffect {
        id: shader
        anchors.fill: parent
        visible: cw.base === "scene" && cw.gpu && status !== ShaderEffect.Error
        fragmentShader: cw.base === "scene" ? Qt.resolvedUrl((cw.spec.scene || "aurora") + ".frag.qsb") : ""
        property real time: cw.time
        property real day: 0
        property size res: Qt.size(width, height)
        property color tintA: cw.colours.tintA || "#0F2624"
        property color tintB: cw.colours.tintB || "#17192C"
        property color glowA: cw.colours.glowA || "#3DD6B5"
        property color glowB: cw.colours.glowB || "#7B61FF"
    }
    Image {
        id: picture
        visible: cw.base === "picture"
        source: cw.base === "picture" ? cw.file(cw.spec.file) : ""
        width: parent.width; height: parent.height
        fillMode: Image.PreserveAspectCrop
        asynchronous: true; cache: false; smooth: true; mipmap: true
        sourceSize: Qt.size(Math.min(3840, cw.width * 1.3), Math.min(2400, cw.height * 1.3))
        readonly property string motion: cw.spec.motion || "drift"
        readonly property real t: cw.time
        scale: motion === "drift" ? 1.12 : motion === "breathe" ? 1.045 + 0.04 * Math.sin(t * 0.11) : 1
        x: motion === "drift" ? Math.sin(t * 0.043) * cw.width * 0.05 : 0
        y: motion === "drift" ? Math.cos(t * 0.031) * cw.height * 0.04 : 0
    }
    MediaPlayer {
        id: player
        source: cw.base === "video" ? cw.file(cw.spec.file) : ""
        loops: MediaPlayer.Infinite
        videoOutput: video
        playbackRate: Math.max(0.25, Math.min(2, cw.pace))
        onSourceChanged: if (source != "") { play(); if (!cw.moving) pause() }
    }
    Connections { target: cw; function onMovingChanged() { if (cw.base !== "video") return; if (cw.moving) player.play(); else player.pause() } }
    VideoOutput {
        id: video
        anchors.fill: parent
        visible: cw.base === "video"
        fillMode: VideoOutput.PreserveAspectCrop
    }
    Rectangle { anchors.fill: parent; color: "#000000"; opacity: Math.max(0, Math.min(0.7, Number(cw.spec.shade || 0))) }

    // ------------------------------------------------------------------------- the effects
    // At the start the effects are already under way (each emitter starts from the past, `startTime`), and they run a
    // moment even when they're to be still, so there's something to hold still.
    property bool primed: false
    Timer { interval: 500; running: true; onTriggered: cw.primed = true }
    ParticleSystem {
        id: sys
        anchors.fill: parent
        paused: cw.primed && (!cw.moving || !cw.visible)
        running: cw.effects.length > 0
    }
    readonly property real n: cw.amount * cw.width / 1920 * cw.height / 1080      // how many, for this much screen
    // an effect turned off goes at once (its particles fade out instead of living out their time)
    Repeater { model: ["snow", "rain", "stars", "fireflies", "lights", "leaves", "embers"]
        Age { required property string modelData; system: sys; groups: [modelData]; enabled: !cw.has(modelData); once: true; lifeLeft: 300 } }

    // snow: soft flakes drifting down, swaying
    ImageParticle { system: sys; groups: ["snow"]; source: Qt.resolvedUrl("sprites/flake.png"); color: cw.tint("#FFFFFF"); alpha: 0.9; alphaVariation: 0.4; entryEffect: ImageParticle.Fade }
    Emitter { system: sys; group: "snow"; enabled: cw.has("snow"); startTime: lifeSpan + lifeSpanVariation; width: cw.width * 1.2; x: -cw.width * 0.1; y: -30; height: 1
        emitRate: Math.max(2, 70 * cw.n) * cw.pace; lifeSpan: 1000 * cw.height / (45 * cw.k) / cw.pace + 4000; lifeSpanVariation: 2000
        size: 7 * cw.k; sizeVariation: 6 * cw.k
        velocity: PointDirection { y: 48 * cw.k * cw.pace; yVariation: 22 * cw.k * cw.pace; x: 6 * cw.k; xVariation: 14 * cw.k } }
    Wander { system: sys; groups: ["snow"]; xVariance: 40 * cw.k; pace: 30 * cw.pace }

    // rain: long thin streaks, fast and a little slanted
    ImageParticle { system: sys; groups: ["rain"]; source: Qt.resolvedUrl("sprites/drop.png"); color: cw.tint("#C8DCF5"); alpha: 0.55; alphaVariation: 0.25 }
    Emitter { system: sys; group: "rain"; enabled: cw.has("rain"); startTime: lifeSpan + lifeSpanVariation; width: cw.width * 1.3; x: -cw.width * 0.2; y: -60; height: 1
        emitRate: Math.max(4, 260 * cw.n) * cw.pace; lifeSpan: 1000 * cw.height / (800 * cw.k) / cw.pace + 300
        size: 34 * cw.k; sizeVariation: 12 * cw.k
        velocity: AngleDirection { angle: 97; angleVariation: 2; magnitude: 820 * cw.k * cw.pace; magnitudeVariation: 160 * cw.k * cw.pace } }

    // stars: points coming and going in the upper sky, never moving
    ImageParticle { system: sys; groups: ["stars"]; source: Qt.resolvedUrl("sprites/star.png"); color: cw.tint("#FFFFFF"); alphaVariation: 0.5; entryEffect: ImageParticle.Fade }
    Emitter { system: sys; group: "stars"; enabled: cw.has("stars"); startTime: lifeSpan + lifeSpanVariation; width: cw.width; height: cw.height * 0.62
        emitRate: Math.max(2, 30 * cw.n) * Math.max(0.5, cw.pace); lifeSpan: 7000 / Math.max(0.5, cw.pace); lifeSpanVariation: 3000
        size: 9 * cw.k; sizeVariation: 7 * cw.k }

    // fireflies: warm lights wandering low, fading in and out
    ImageParticle { system: sys; groups: ["fireflies"]; source: Qt.resolvedUrl("sprites/glow.png"); color: cw.tint("#D8FF6E"); colorVariation: 0.08; entryEffect: ImageParticle.Fade }
    Emitter { system: sys; group: "fireflies"; enabled: cw.has("fireflies"); startTime: lifeSpan + lifeSpanVariation; width: cw.width; y: cw.height * 0.35; height: cw.height * 0.65
        emitRate: Math.max(1, 9 * cw.n) * cw.pace; lifeSpan: 6000 / cw.pace; lifeSpanVariation: 2500
        size: 16 * cw.k; sizeVariation: 10 * cw.k
        velocity: PointDirection { xVariation: 18 * cw.k * cw.pace; yVariation: 14 * cw.k * cw.pace; y: -4 * cw.k } }
    Wander { system: sys; groups: ["fireflies"]; xVariance: 60 * cw.k; yVariance: 40 * cw.k; pace: 50 * cw.pace }

    // lights: big soft discs, out of focus, rising slowly
    ImageParticle { system: sys; groups: ["lights"]; source: Qt.resolvedUrl("sprites/bokeh.png"); color: cw.tint(cw.colours.glowA || "#FFD6A0"); colorVariation: 0.25; alpha: 0.5; alphaVariation: 0.3; entryEffect: ImageParticle.Fade }
    Emitter { system: sys; group: "lights"; enabled: cw.has("lights"); startTime: lifeSpan + lifeSpanVariation; width: cw.width; y: cw.height * 0.2; height: cw.height * 0.9
        emitRate: Math.max(0.5, 3 * cw.n) * cw.pace; lifeSpan: 12000 / cw.pace; lifeSpanVariation: 4000
        size: 90 * cw.k; sizeVariation: 60 * cw.k
        velocity: PointDirection { y: -10 * cw.k * cw.pace; yVariation: 6 * cw.k * cw.pace; xVariation: 6 * cw.k * cw.pace } }

    // leaves: falling, turning and swaying
    ImageParticle { system: sys; groups: ["leaves"]; source: Qt.resolvedUrl("sprites/leaf.png"); color: cw.tint("#E8833A"); colorVariation: 0.15; alpha: 0.95
        rotationVariation: 180; rotationVelocity: 30 * cw.pace; rotationVelocityVariation: 80 * cw.pace; entryEffect: ImageParticle.Fade }
    Emitter { system: sys; group: "leaves"; enabled: cw.has("leaves"); startTime: lifeSpan + lifeSpanVariation; width: cw.width * 1.2; x: -cw.width * 0.1; y: -40; height: 1
        emitRate: Math.max(0.5, 7 * cw.n) * cw.pace; lifeSpan: 1000 * cw.height / (60 * cw.k) / cw.pace + 3000
        size: 26 * cw.k; sizeVariation: 12 * cw.k
        velocity: PointDirection { y: 62 * cw.k * cw.pace; yVariation: 25 * cw.k * cw.pace; x: 12 * cw.k; xVariation: 20 * cw.k } }
    Wander { system: sys; groups: ["leaves"]; xVariance: 90 * cw.k; pace: 40 * cw.pace }

    // embers: small sparks rising from the bottom
    ImageParticle { system: sys; groups: ["embers"]; source: Qt.resolvedUrl("sprites/glow.png"); color: cw.tint("#FF8A3C"); colorVariation: 0.1; entryEffect: ImageParticle.Fade }
    Emitter { system: sys; group: "embers"; enabled: cw.has("embers"); startTime: lifeSpan + lifeSpanVariation; width: cw.width; y: cw.height + 10; height: 1
        emitRate: Math.max(1, 30 * cw.n) * cw.pace; lifeSpan: 1000 * cw.height / (70 * cw.k) / cw.pace; lifeSpanVariation: 2000
        size: 8 * cw.k; sizeVariation: 6 * cw.k
        velocity: PointDirection { y: -80 * cw.k * cw.pace; yVariation: 30 * cw.k * cw.pace; xVariation: 12 * cw.k } }
    Wander { system: sys; groups: ["embers"]; xVariance: 50 * cw.k; pace: 60 * cw.pace }
}
