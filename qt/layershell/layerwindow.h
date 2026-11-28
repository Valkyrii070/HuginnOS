// Huginn's own layer-shell windows for Qt Quick (the shell's bar, dock and overlays, the lock screen, the sign-in
// screen, the session's banners): a QML module, org.huginn.layershell, whose attached Window makes a window a
// wlr-layer-shell surface instead of an ordinary one. It speaks the protocol itself, through Qt's own Wayland client,
// so the shell needs nothing of KDE's (it used layer-shell-qt).
//
//     import org.huginn.layershell 1.0 as LayerShell
//     Window { LayerShell.Window.layer: LayerShell.Window.LayerTop
//              LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
//              LayerShell.Window.exclusionZone: 32 ... }
//
// The properties (as layer-shell-qt named them): layer, anchors, exclusionZone, keyboardInteractivity, scope,
// screen and wantsToBeOnActiveScreen. A surface stays on the screen it was made on: to move one, hide and show it.
#pragma once

#include <QObject>
#include <QPointer>
#include <QScreen>
#include <QString>
#include <QWindow>
#include <QtQml/qqml.h>

class HuginnLayerWindow : public QObject
{
    Q_OBJECT
    QML_NAMED_ELEMENT(Window)
    QML_UNCREATABLE("Set it on a Window: LayerShell.Window.layer and so on")
    QML_ATTACHED(HuginnLayerWindow)

    Q_PROPERTY(Layer layer READ layer WRITE setLayer NOTIFY layerChanged)
    Q_PROPERTY(Anchors anchors READ anchors WRITE setAnchors NOTIFY anchorsChanged)
    Q_PROPERTY(int exclusionZone READ exclusionZone WRITE setExclusionZone NOTIFY exclusionZoneChanged)
    Q_PROPERTY(KeyboardInteractivity keyboardInteractivity READ keyboardInteractivity WRITE setKeyboardInteractivity NOTIFY keyboardInteractivityChanged)
    Q_PROPERTY(QString scope READ scope WRITE setScope NOTIFY scopeChanged)
    Q_PROPERTY(QScreen *screen READ screen WRITE setScreen NOTIFY screenChanged)
    Q_PROPERTY(bool wantsToBeOnActiveScreen READ wantsToBeOnActiveScreen WRITE setWantsToBeOnActiveScreen NOTIFY wantsToBeOnActiveScreenChanged)

public:
    // (the protocol's own numbers)
    enum Layer { LayerBackground = 0, LayerBottom = 1, LayerTop = 2, LayerOverlay = 3 };
    Q_ENUM(Layer)
    enum Anchor { AnchorNone = 0, AnchorTop = 1, AnchorBottom = 2, AnchorLeft = 4, AnchorRight = 8 };
    Q_DECLARE_FLAGS(Anchors, Anchor)
    Q_FLAG(Anchors)
    enum KeyboardInteractivity { KeyboardInteractivityNone = 0, KeyboardInteractivityExclusive = 1, KeyboardInteractivityOnDemand = 2 };
    Q_ENUM(KeyboardInteractivity)

    static HuginnLayerWindow *get(QWindow *window);     // made (and the window made a layer surface) the first time
    static HuginnLayerWindow *find(QWindow *window);    // or nullptr
    static HuginnLayerWindow *qmlAttachedProperties(QObject *object);

    Layer layer() const { return m_layer; }
    void setLayer(Layer layer);
    Anchors anchors() const { return m_anchors; }
    void setAnchors(Anchors anchors);
    int exclusionZone() const { return m_zone; }
    void setExclusionZone(int zone);
    KeyboardInteractivity keyboardInteractivity() const { return m_keys; }
    void setKeyboardInteractivity(KeyboardInteractivity keys);
    QString scope() const { return m_scope; }
    void setScope(const QString &scope);
    QScreen *screen() const { return m_screen; }
    void setScreen(QScreen *screen);
    bool wantsToBeOnActiveScreen() const { return m_active; }
    void setWantsToBeOnActiveScreen(bool on);

    QWindow *window() const { return m_window; }

Q_SIGNALS:
    void layerChanged();
    void anchorsChanged();
    void exclusionZoneChanged();
    void keyboardInteractivityChanged();
    void scopeChanged();
    void screenChanged();
    void wantsToBeOnActiveScreenChanged();

private:
    explicit HuginnLayerWindow(QWindow *window);
    QWindow *m_window;
    Layer m_layer = LayerTop;
    Anchors m_anchors = AnchorNone;
    int m_zone = 0;
    KeyboardInteractivity m_keys = KeyboardInteractivityOnDemand;
    QString m_scope = QStringLiteral("window");
    QPointer<QScreen> m_screen;
    bool m_active = true;
};

Q_DECLARE_OPERATORS_FOR_FLAGS(HuginnLayerWindow::Anchors)
