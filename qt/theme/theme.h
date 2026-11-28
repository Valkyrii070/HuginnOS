// Huginn's platform theme for Qt apps that aren't Huginn's own (QT_QPA_PLATFORMTHEME=huginn).
//
// The look comes from ~/.config/huginn/qt.conf (apps/huginn_look.py writes it from the realm and dark or light;
// before that, /etc/xdg/huginn/qt.conf, Aurora dark), and apps follow it while open. Open and Save go through Qt's
// portal theme (so the windows are Huginn's own), tray icons and the rest through Qt's plain Unix theme. Menu bars
// go to the top bar (menus.h).
#pragma once

#include <QFont>
#include <QHash>
#include <QObject>
#include <QPalette>
#include <QScopedPointer>
#include <QString>
#include <qpa/qplatformtheme.h>

class QFileSystemWatcher;
class QTimer;

struct HuginnLook {
    bool dark = true;
    QString icons = QStringLiteral("Huginn");
    QString font, fixed;               // "Inter Variable,10" (no QFont here: see theme.cpp)
    QHash<QString, QString> colours;   // window, view, text, … (as tokens/gen_theme.py names them)
    bool topBar = true;                // menu bars in the top bar
    QString read;                      // the file it came from (or "" for the built-in Aurora dark)

    static HuginnLook load();
    QPalette palette() const;
    QPalette tooltips() const;
    QPalette menus() const;          // (pop-up menus: the menu colour)
    bool operator==(const HuginnLook &o) const;
};

class HuginnTheme;

class HuginnLookWatch : public QObject
{
    Q_OBJECT
public:
    explicit HuginnLookWatch(HuginnTheme *theme);
private:
    void watch();
    void changed();
    HuginnTheme *m_theme;
    QFileSystemWatcher *m_watch;
    QTimer *m_later;
};

class HuginnTheme : public QPlatformTheme
{
public:
    HuginnTheme();
    ~HuginnTheme() override;

    QPlatformMenuBar *createPlatformMenuBar() const override;
    QPlatformMenu *createPlatformMenu() const override { return nullptr; }          // pop-up menus stay Qt's own
    QPlatformMenuItem *createPlatformMenuItem() const override { return nullptr; }

    bool usePlatformNativeDialog(DialogType type) const override;
    QPlatformDialogHelper *createPlatformDialogHelper(DialogType type) const override;
#ifndef QT_NO_SYSTEMTRAYICON
    QPlatformSystemTrayIcon *createPlatformSystemTrayIcon() const override;
#endif
    Qt::ColorScheme colorScheme() const override;
    const QPalette *palette(Palette type = SystemPalette) const override;
    const QFont *font(Font type = SystemFont) const override;
    QVariant themeHint(ThemeHint hint) const override;
    QIcon fileIcon(const QFileInfo &fileInfo, QPlatformTheme::IconOptions iconOptions = {}) const override;
    QIconEngine *createIconEngine(const QString &iconName) const override;
    QList<QKeySequence> keyBindings(QKeySequence::StandardKey key) const override;
    QString standardButtonText(int button) const override;

    const HuginnLook &look() const { return m_look; }
    bool reload();                     // true when the look changed
    static bool making();              // (while this theme makes Qt's own: see theme.cpp)

private:
    QPlatformTheme *base() const;
    QPlatformTheme *portal() const;
    mutable QPlatformTheme *m_base = nullptr;    // Qt's plain Unix theme (key bindings, file icons, tray icons, the rest)
    mutable QPlatformTheme *m_portal = nullptr;  // Qt's portal theme (Open and Save)
    mutable bool m_triedBase = false, m_triedPortal = false;
    mutable QScopedPointer<QFont> m_font, m_fixed;
    HuginnLook m_look;
    QPalette m_palette, m_tips, m_menus;
    HuginnLookWatch *m_watch = nullptr;
};
