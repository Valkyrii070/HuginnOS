#include "theme.h"
#include "menus.h"

#include <QColor>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QFileSystemWatcher>
#include <QGuiApplication>
#include <QIcon>
#include <QStandardPaths>
#include <QTimer>
#include <QVariant>
#include <private/qguiapplication_p.h>
#include <qpa/qplatformdialoghelper.h>
#include <qpa/qplatformintegration.h>
#include <qpa/qplatformthemefactory_p.h>
#include <qpa/qwindowsysteminterface.h>

// Aurora dark (tokens/tokens.json), for when no file says otherwise.
static const char *const BUILT_IN[][2] = {
    {"window", "#1E2227"}, {"view", "#15181C"}, {"alternate", "#1A1D22"}, {"text", "#ECEFF3"},
    {"secondary", "#9AA3AD"}, {"disabled", "#5C646D"}, {"button", "#303338"}, {"button_border", "#35393D"},
    {"accent", "#43D9B8"}, {"on_accent", "#0B1512"}, {"tooltip", "#22262B"}, {"menu", "#23272D"},
    {"border", "#3A4047"}, {"separator", "#2A2F35"}, {"link", "#43D9B8"}, {"visited", "#6EBEB2"},
    {"danger", "#FF5F57"}, {"header", "#17192C"}, {"sidebar", "#0F2624"},
};

static QString configHome()
{
    QString dir = qEnvironmentVariable("XDG_CONFIG_HOME");
    return dir.isEmpty() ? QDir::homePath() + QStringLiteral("/.config") : dir;
}

static QStringList lookFiles()
{
    QStringList files{configHome() + QStringLiteral("/huginn/qt.conf")};
    QString dirs = qEnvironmentVariable("XDG_CONFIG_DIRS");
    for (const QString &d : (dirs.isEmpty() ? QStringLiteral("/etc/xdg") : dirs).split(QLatin1Char(':'), Qt::SkipEmptyParts))
        files << d + QStringLiteral("/huginn/qt.conf");
    return files;
}

// "Inter Variable,10" (a family and a size in points; the family may not have commas). Made only when Qt asks for
// it: a QFont made before the theme is in place settles the app's font (QFont() starts from it) without the theme.
static QFont fontFrom(const QString &text, const QString &family, qreal size, const QString &fallback)
{
    QString name = family;
    qreal pt = size;
    int comma = text.lastIndexOf(QLatin1Char(','));
    if (!text.trimmed().isEmpty()) {
        name = (comma > 0 ? text.left(comma) : text).trimmed();
        bool ok = false;
        qreal v = comma > 0 ? text.mid(comma + 1).trimmed().toDouble(&ok) : 0;
        if (ok && v >= 5 && v <= 40)
            pt = v;
    }
    QFont f(name);
    f.setPointSizeF(pt);
    f.setFamilies({name, fallback});
    return f;
}

HuginnLook HuginnLook::load()
{
    HuginnLook look;
    for (const auto &pair : BUILT_IN)
        look.colours.insert(QString::fromLatin1(pair[0]), QString::fromLatin1(pair[1]));
    QString font, fixed;
    for (const QString &path : lookFiles()) {
        QFile f(path);
        if (!f.open(QIODevice::ReadOnly | QIODevice::Text))
            continue;
        look.read = path;
        QString section;
        while (!f.atEnd()) {
            const QString line = QString::fromUtf8(f.readLine()).trimmed();
            if (line.isEmpty() || line.startsWith(QLatin1Char(';')))
                continue;
            if (line.startsWith(QLatin1Char('[')) && line.endsWith(QLatin1Char(']'))) {
                section = line.mid(1, line.size() - 2).trimmed().toLower();
                continue;
            }
            const int eq = line.indexOf(QLatin1Char('='));
            if (eq <= 0)
                continue;
            const QString key = line.left(eq).trimmed().toLower(), value = line.mid(eq + 1).trimmed();
            if (section == QLatin1String("colours")) {
                if (QColor::fromString(value).isValid())
                    look.colours.insert(key, value);
            } else if (section == QLatin1String("look")) {
                if (key == QLatin1String("scheme"))
                    look.dark = value.compare(QLatin1String("light"), Qt::CaseInsensitive) != 0;
                else if (key == QLatin1String("icons") && !value.isEmpty())
                    look.icons = value;
                else if (key == QLatin1String("font"))
                    font = value;
                else if (key == QLatin1String("fixed"))
                    fixed = value;
            } else if (section == QLatin1String("menus") && key == QLatin1String("top_bar")) {
                look.topBar = value.compare(QLatin1String("false"), Qt::CaseInsensitive) != 0;
            }
        }
        break;                                    // the first file there is the one
    }
    look.font = font;
    look.fixed = fixed;
    return look;
}

bool HuginnLook::operator==(const HuginnLook &o) const
{
    return dark == o.dark && icons == o.icons && font == o.font && fixed == o.fixed && colours == o.colours && topBar == o.topBar;
}

static QColor mixed(const QColor &a, const QColor &b, qreal t)
{
    return QColor::fromRgbF(a.redF() + (b.redF() - a.redF()) * t, a.greenF() + (b.greenF() - a.greenF()) * t,
                            a.blueF() + (b.blueF() - a.blueF()) * t, 1.0);
}

QPalette HuginnLook::palette() const
{
    auto c = [this](const char *name) { return QColor::fromString(colours.value(QString::fromLatin1(name))); };
    const QColor window = c("window"), view = c("view"), text = c("text"), soft = c("secondary"), off = c("disabled"),
                 button = c("button"), accent = c("accent"), onAccent = c("on_accent"), border = c("border");
    QPalette p;
    for (auto group : {QPalette::Active, QPalette::Inactive, QPalette::Disabled}) {
        const bool disabled = group == QPalette::Disabled;
        p.setColor(group, QPalette::Window, window);
        p.setColor(group, QPalette::WindowText, disabled ? off : text);
        p.setColor(group, QPalette::Base, disabled ? mixed(view, window, 0.5) : view);
        p.setColor(group, QPalette::AlternateBase, c("alternate"));
        p.setColor(group, QPalette::Text, disabled ? off : text);
        p.setColor(group, QPalette::PlaceholderText, disabled ? off : soft);
        p.setColor(group, QPalette::Button, button);
        p.setColor(group, QPalette::ButtonText, disabled ? off : text);
        p.setColor(group, QPalette::BrightText, c("danger"));
        p.setColor(group, QPalette::Highlight, disabled ? mixed(accent, window, 0.6) : (group == QPalette::Inactive ? mixed(accent, window, 0.35) : accent));
        p.setColor(group, QPalette::HighlightedText, onAccent);
        p.setColor(group, QPalette::Accent, disabled ? mixed(accent, window, 0.6) : accent);
        p.setColor(group, QPalette::Link, c("link"));
        p.setColor(group, QPalette::LinkVisited, c("visited"));
        p.setColor(group, QPalette::ToolTipBase, c("tooltip"));
        p.setColor(group, QPalette::ToolTipText, text);
        // the 3D roles, for styles that shade with them
        p.setColor(group, QPalette::Light, dark ? mixed(button, text, 0.12) : view);
        p.setColor(group, QPalette::Midlight, mixed(button, border, 0.5));
        p.setColor(group, QPalette::Mid, border);
        p.setColor(group, QPalette::Dark, mixed(border, dark ? QColor(Qt::black) : text, 0.35));
        p.setColor(group, QPalette::Shadow, QColor(0, 0, 0, dark ? 160 : 70));
    }
    return p;
}

QPalette HuginnLook::menus() const
{
    QPalette p = palette();
    const QColor menu = QColor::fromString(colours.value(QStringLiteral("menu")));
    for (auto group : {QPalette::Active, QPalette::Inactive, QPalette::Disabled})
        p.setColor(group, QPalette::Window, menu);
    return p;
}

QPalette HuginnLook::tooltips() const
{
    QPalette p = palette();
    const QColor tip = QColor::fromString(colours.value(QStringLiteral("tooltip"))), text = QColor::fromString(colours.value(QStringLiteral("text")));
    for (auto group : {QPalette::Active, QPalette::Inactive, QPalette::Disabled}) {
        p.setColor(group, QPalette::Window, tip);
        p.setColor(group, QPalette::WindowText, text);
    }
    return p;
}

// ------------------------------------------------------------------------------------------------ following it
HuginnLookWatch::HuginnLookWatch(HuginnTheme *theme) : m_theme(theme), m_watch(nullptr), m_later(nullptr)
{
    // (the theme is made before Qt can watch files: once the app's loop runs)
    QMetaObject::invokeMethod(this, &HuginnLookWatch::watch, Qt::QueuedConnection);
}

void HuginnLookWatch::watch()
{
    if (!m_watch) {
        m_watch = new QFileSystemWatcher(this);
        m_later = new QTimer(this);
        m_later->setSingleShot(true);
        m_later->setInterval(120);
        connect(m_later, &QTimer::timeout, this, &HuginnLookWatch::changed);
        connect(m_watch, &QFileSystemWatcher::fileChanged, m_later, qOverload<>(&QTimer::start));
        connect(m_watch, &QFileSystemWatcher::directoryChanged, m_later, qOverload<>(&QTimer::start));
    }
    // the folder too: huginn_look.py replaces the file (a new file, so the old one's watch ends)
    const QString dir = configHome() + QStringLiteral("/huginn");
    QDir().mkpath(dir);
    QStringList want{dir};
    for (const QString &f : lookFiles())
        if (QFileInfo::exists(f))
            want << f;
    const QStringList now = m_watch->files() + m_watch->directories();
    for (const QString &w : want)
        if (!now.contains(w))
            m_watch->addPath(w);
}

void HuginnLookWatch::changed()
{
    watch();
    if (m_theme->reload())
        QWindowSystemInterface::handleThemeChange();
}

// ------------------------------------------------------------------------------------------------ the theme
HuginnTheme::HuginnTheme()
{
    m_look = HuginnLook::load();
    m_palette = m_look.palette();
    m_tips = m_look.tooltips();
    m_menus = m_look.menus();
    m_watch = new HuginnLookWatch(this);
}

HuginnTheme::~HuginnTheme()
{
    delete m_watch;
    delete m_portal;
    delete m_base;
}

// While this theme makes another, the factory may be asked for this one again (Qt's portal theme looks for a base
// theme by the session's name, and Huginn's session is called "huginn"): it says no then, so there's no chain.
static bool s_making = false;

bool HuginnTheme::making()
{
    return s_making;
}

QPlatformTheme *HuginnTheme::base() const
{
    // Qt's plain Unix theme, for what this one doesn't settle itself (key bindings, file icons, tray icons…). Made
    // the first time it's needed, not with this theme: making it asks for the app's font, which would then be
    // settled before this theme is there to give it.
    if (!m_triedBase) {
        m_triedBase = true;
        s_making = true;
        if (QPlatformIntegration *pi = QGuiApplicationPrivate::platformIntegration())
            m_base = pi->createPlatformTheme(QStringLiteral("generic"));
        s_making = false;
    }
    return m_base;
}

QPlatformTheme *HuginnTheme::portal() const
{
    // Qt's portal theme, for Open and Save (and colours): only when a dialog is wanted, as making it asks the
    // desktop portal and waits for an answer
    if (!m_triedPortal) {
        m_triedPortal = true;
        s_making = true;
        m_portal = QPlatformThemeFactory::create(QStringLiteral("xdgdesktopportal"));
        s_making = false;
    }
    return m_portal;
}

bool HuginnTheme::reload()
{
    HuginnLook now = HuginnLook::load();
    if (now == m_look)
        return false;
    m_look = now;
    m_palette = m_look.palette();
    m_tips = m_look.tooltips();
    m_menus = m_look.menus();
    m_font.reset();
    m_fixed.reset();
    return true;
}

QPlatformMenuBar *HuginnTheme::createPlatformMenuBar() const
{
    if (!m_look.topBar)
        return nullptr;
    return HuginnMenus::createBar();
}

bool HuginnTheme::usePlatformNativeDialog(DialogType type) const
{
    return portal() && portal()->usePlatformNativeDialog(type);
}

QPlatformDialogHelper *HuginnTheme::createPlatformDialogHelper(DialogType type) const
{
    return portal() ? portal()->createPlatformDialogHelper(type) : nullptr;
}

#ifndef QT_NO_SYSTEMTRAYICON
QPlatformSystemTrayIcon *HuginnTheme::createPlatformSystemTrayIcon() const
{
    return base() ? base()->createPlatformSystemTrayIcon() : nullptr;
}
#endif

Qt::ColorScheme HuginnTheme::colorScheme() const
{
    return m_look.dark ? Qt::ColorScheme::Dark : Qt::ColorScheme::Light;
}

const QPalette *HuginnTheme::palette(Palette type) const
{
    if (type == SystemPalette)
        return &m_palette;
    if (type == ToolTipPalette)
        return &m_tips;
    if (type == MenuPalette || type == MenuBarPalette)
        return &m_menus;
    return nullptr;
}

const QFont *HuginnTheme::font(Font type) const
{
    if (type == FixedFont) {
        if (!m_fixed) {
            m_fixed.reset(new QFont(fontFrom(m_look.fixed, QStringLiteral("JetBrains Mono"), 10, QStringLiteral("monospace"))));
            m_fixed->setStyleHint(QFont::Monospace);
        }
        return m_fixed.data();
    }
    if (type == SystemFont) {
        if (!m_font)
            m_font.reset(new QFont(fontFrom(m_look.font, QStringLiteral("Inter Variable"), 10, QStringLiteral("Inter"))));
        return m_font.data();
    }
    return nullptr;
}

QVariant HuginnTheme::themeHint(ThemeHint hint) const
{
    switch (hint) {
    case StyleNames:
        return QStringList{QStringLiteral("Huginn"), QStringLiteral("Fusion")};
    case SystemIconThemeName:
        return m_look.icons;
    case SystemIconFallbackThemeName:
        return QStringLiteral("hicolor");
    case DialogButtonBoxLayout:
        return 3;                                            // GnomeLayout: Cancel, then the button that does it, on the right
    case ShowShortcutsInContextMenus:
        return true;
    case UnderlineShortcut:
        return false;                                        // (shown while Alt is held)
    case PreferFileIconFromTheme:
        return true;
    case WheelScrollLines:
        return 3;
    case ToolButtonStyle:
        return int(Qt::ToolButtonTextBesideIcon);
    case ToolBarIconSize:
        return 22;
    case ItemViewActivateItemOnSingleClick:
        return false;
    case DialogSnapToDefaultButton:
        return false;
    default:
        break;
    }
    return base() ? base()->themeHint(hint) : QPlatformTheme::themeHint(hint);
}

QIcon HuginnTheme::fileIcon(const QFileInfo &fileInfo, QPlatformTheme::IconOptions iconOptions) const
{
    return base() ? base()->fileIcon(fileInfo, iconOptions) : QPlatformTheme::fileIcon(fileInfo, iconOptions);
}

QIconEngine *HuginnTheme::createIconEngine(const QString &iconName) const
{
    return base() ? base()->createIconEngine(iconName) : QPlatformTheme::createIconEngine(iconName);
}

QList<QKeySequence> HuginnTheme::keyBindings(QKeySequence::StandardKey key) const
{
    return base() ? base()->keyBindings(key) : QPlatformTheme::keyBindings(key);
}

QString HuginnTheme::standardButtonText(int button) const
{
    return base() ? base()->standardButtonText(button) : QPlatformTheme::standardButtonText(button);
}
