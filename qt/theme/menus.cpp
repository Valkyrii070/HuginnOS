#include "menus.h"

#include <QCoreApplication>
#include <QDBusConnection>
#include <QDBusConnectionInterface>
#include <QGuiApplication>
#include <QHash>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>

static int s_numbers = 0;
static QHash<int, HuginnMenuItem *> s_items;          // every item there is, by its number (the id the shell sends back)
static QList<QPointer<HuginnMenuBar>> s_bars;
static QPointer<QWindow> s_lastFocus;

// ------------------------------------------------------------------------------------------------ the parts
HuginnMenuItem::HuginnMenuItem() : m_number(++s_numbers)
{
    s_items.insert(m_number, this);
}

HuginnMenuItem::~HuginnMenuItem()
{
    s_items.remove(m_number);
}

void HuginnMenuItem::setMenu(QPlatformMenu *menu)
{
    m_menu = qobject_cast<HuginnMenu *>(menu);
}

void HuginnMenu::insertMenuItem(QPlatformMenuItem *item, QPlatformMenuItem *before)
{
    auto *mine = qobject_cast<HuginnMenuItem *>(item);
    if (!mine)
        return;
    m_items.removeAll(mine);
    int at = m_items.size();
    for (int i = 0; before && i < m_items.size(); ++i)
        if (m_items[i] == before) {
            at = i;
            break;
        }
    m_items.insert(at, mine);
}

void HuginnMenu::removeMenuItem(QPlatformMenuItem *item)
{
    if (item)
        m_items.removeAll(qobject_cast<HuginnMenuItem *>(item));
}

QPlatformMenuItem *HuginnMenu::menuItemAt(int position) const
{
    return position >= 0 && position < m_items.size() ? m_items[position].data() : nullptr;
}

QPlatformMenuItem *HuginnMenu::menuItemForTag(quintptr tag) const
{
    for (const auto &it : m_items)
        if (it && it->tag() == tag)
            return it;
    return nullptr;
}

void HuginnMenu::opening(int depth)
{
    emit aboutToShow();
    if (depth < 4)
        for (const auto &it : m_items)
            if (it && it->m_menu && it->m_visible)
                it->m_menu->opening(depth + 1);
}

void HuginnMenu::closing(int depth)
{
    if (depth < 4)
        for (const auto &it : m_items)
            if (it && it->m_menu && it->m_visible)
                it->m_menu->closing(depth + 1);
    emit aboutToHide();
}

HuginnMenuBar::HuginnMenuBar()
{
    s_bars.append(this);
}

HuginnMenuBar::~HuginnMenuBar()
{
    s_bars.removeAll(this);
}

void HuginnMenuBar::insertMenu(QPlatformMenu *menu, QPlatformMenu *before)
{
    auto *mine = qobject_cast<HuginnMenu *>(menu);
    if (!mine)
        return;
    m_menus.removeAll(mine);
    int at = m_menus.size();
    for (int i = 0; before && i < m_menus.size(); ++i)
        if (m_menus[i] == before) {
            at = i;
            break;
        }
    m_menus.insert(at, mine);
}

void HuginnMenuBar::removeMenu(QPlatformMenu *menu)
{
    m_menus.removeAll(qobject_cast<HuginnMenu *>(menu));
}

QPlatformMenu *HuginnMenuBar::menuForTag(quintptr tag) const
{
    for (const auto &m : m_menus)
        if (m && m->tag() == tag)
            return m;
    return nullptr;
}

// ------------------------------------------------------------------------------------------------ as the shell reads them
static QString plain(QString text)
{
    // "&Open Recent\tCtrl+R" -> "Open Recent"; "Save && Quit" -> "Save & Quit"
    const int tab = text.indexOf(QLatin1Char('\t'));
    if (tab >= 0)
        text.truncate(tab);
    text.replace(QStringLiteral("&&"), QStringLiteral("\x01"));
    text.remove(QLatin1Char('&'));
    text.replace(QStringLiteral("\x01"), QStringLiteral("&"));
    static const QRegularExpression mnemonic(QStringLiteral("\\s*\\(\\w\\)$"));   // "Open(O)": a mnemonic in brackets
    return text.remove(mnemonic).trimmed();
}

static QString appName()
{
    QString name = QGuiApplication::applicationDisplayName();
    if (name.isEmpty())
        name = QCoreApplication::applicationName();
    return name.isEmpty() ? QStringLiteral("App") : name;
}

static QJsonObject entry(const QString &label, const QString &id, const QString &keys = QString(), bool enabled = true)
{
    return QJsonObject{{QStringLiteral("label"), label}, {QStringLiteral("id"), id}, {QStringLiteral("keys"), keys},
                       {QStringLiteral("enabled"), enabled}};
}

namespace {
struct Special {
    HuginnMenuItem *about = nullptr, *settings = nullptr, *quit = nullptr;
};
}

// The app's About, Settings and Quit go where they are in every Huginn app's menu (first, and last), as macOS does:
// by the role the app gave them, else by what they say.
static void findSpecial(HuginnMenu *menu, Special &s, const QString &app, int depth)
{
    const QString appLower = app.toLower();
    for (const auto &it : menu->m_items) {
        if (!it || !it->m_visible || it->m_separator)
            continue;
        if (it->m_menu) {
            if (depth < 1)
                findSpecial(it->m_menu, s, app, depth + 1);
            continue;
        }
        QString t = plain(it->m_text).toLower();
        t.remove(QStringLiteral("…")).remove(QStringLiteral("..."));
        t = t.trimmed();
        const bool guess = it->m_role == QPlatformMenuItem::TextHeuristicRole && depth == 0;
        if (!s.about && (it->m_role == QPlatformMenuItem::AboutRole
                         || (guess && t.startsWith(QStringLiteral("about ")) && !t.contains(QStringLiteral(" qt"))
                             && !t.contains(QStringLiteral("kde")))))
            s.about = it;
        else if (!s.settings && (it->m_role == QPlatformMenuItem::PreferencesRole
                                 || (guess && (t == QStringLiteral("preferences") || t == QStringLiteral("settings") || t == QStringLiteral("options")
                                               || t == QStringLiteral("configure ") + appLower))))
            s.settings = it;
        else if (!s.quit && (it->m_role == QPlatformMenuItem::QuitRole
                             || (guess && (t == QStringLiteral("quit") || t == QStringLiteral("exit") || t == QStringLiteral("quit ") + appLower
                                           || t == QStringLiteral("exit ") + appLower))))
            s.quit = it;
    }
}

static QString keysOf(const HuginnMenuItem *it)
{
#if QT_CONFIG(shortcut)
    return it->m_shortcut.isEmpty() ? QString() : QKeySequence(it->m_shortcut[0]).toString(QKeySequence::PortableText);
#else
    return QString();
#endif
}

static QJsonArray itemsOf(const HuginnMenu *menu, const Special &s, bool enabled, int depth)
{
    QJsonArray out;
    bool lineWanted = false;
    for (const auto &it : menu->m_items) {
        if (!it || !it->m_visible || it == s.about || it == s.settings || it == s.quit)
            continue;
        if (it->m_separator) {
            lineWanted = !out.isEmpty();
            continue;
        }
        QJsonObject row = entry(plain(it->m_text), QStringLiteral("qt:%1").arg(it->number()), keysOf(it), enabled && it->m_enabled);
        if (it->m_menu) {
            if (depth >= 4 || !it->m_menu->m_visible)
                continue;
            const QJsonArray children = itemsOf(it->m_menu, s, enabled && it->m_enabled && it->m_menu->m_enabled, depth + 1);
            if (children.isEmpty())
                continue;
            row.insert(QStringLiteral("children"), children);
            row.insert(QStringLiteral("keys"), QString());
        } else if (it->m_checkable) {
            row.insert(QStringLiteral("checked"), it->m_checked);
            if (it->m_exclusive)
                row.insert(QStringLiteral("radio"), true);
        }
        if (lineWanted)
            out.append(QJsonObject{{QStringLiteral("sep"), true}});
        lineWanted = false;
        out.append(row);
    }
    return out;
}

static HuginnMenuBar *frontBar()
{
    // the window with the keyboard (or the last one that had it: the top bar's menu takes it meanwhile), or the one
    // a dialog belongs to; else the newest menu bar with a window showing
    QWindow *w = QGuiApplication::focusWindow();
    if (!w)
        w = s_lastFocus;
    for (QWindow *x = w; x; x = x->parent(QWindow::IncludeTransients))
        for (const auto &bar : s_bars)
            if (bar && bar->m_window == x)
                return bar;
    for (int i = s_bars.size() - 1; i >= 0; --i)
        if (s_bars[i] && s_bars[i]->m_window && s_bars[i]->m_window->isVisible())
            return s_bars[i];
    return nullptr;
}

QString HuginnMenus::menusJson()
{
    const QString app = appName();
    HuginnMenuBar *bar = frontBar();
    QList<HuginnMenu *> menus;
    if (bar)
        for (const auto &m : bar->m_menus)
            if (m && m->m_visible)
                menus.append(m);
    for (HuginnMenu *m : menus)
        m->opening();                                         // (so menus the app fills as they open have their items)
    Special s;
    for (HuginnMenu *m : menus)
        findSpecial(m, s, app, 0);
    QJsonArray groups;
    for (HuginnMenu *m : menus) {
        const QJsonArray items = itemsOf(m, s, m->m_enabled, 0);
        if (!items.isEmpty())
            groups.append(QJsonObject{{QStringLiteral("name"), plain(m->m_text)}, {QStringLiteral("items"), items}});
    }
    for (int i = menus.size() - 1; i >= 0; --i)
        menus[i]->closing();
    auto mine = [](HuginnMenuItem *it, const QString &label) {
        return entry(label, QStringLiteral("qt:%1").arg(it->number()), keysOf(it), it->m_enabled);
    };
    QJsonArray top{s.about ? mine(s.about, plain(s.about->m_text)) : entry(QStringLiteral("About ") + app, QStringLiteral("shell:aboutApp")),
                   s.settings ? mine(s.settings, app + QStringLiteral(" Settings…"))
                              : entry(app + QStringLiteral(" Settings…"), QString(), QStringLiteral("Ctrl+,"), false)};
    QJsonArray middle{entry(QStringLiteral("Show all its windows"), QStringLiteral("shell:appWindows")),
                      entry(QStringLiteral("Keep in the dock"), QStringLiteral("shell:pin"))};
    QJsonArray bottom{entry(QStringLiteral("Keep on Top"), QStringLiteral("shell:ontop"), QStringLiteral("Super+Ctrl+T")),
                      entry(QStringLiteral("Minimise"), QStringLiteral("shell:minimise")),
                      entry(QStringLiteral("Close window"), QStringLiteral("shell:close"), QStringLiteral("Ctrl+W")),
                      s.quit ? mine(s.quit, QStringLiteral("Quit ") + app) : entry(QStringLiteral("Quit ") + app, QStringLiteral("shell:quit"), QStringLiteral("Ctrl+Q"))};
    QJsonObject out{{QStringLiteral("app"), app}, {QStringLiteral("key"), QString()}, {QStringLiteral("toolkit"), QStringLiteral("qt")},
                    {QStringLiteral("settings"), s.settings != nullptr}, {QStringLiteral("groups"), groups},
                    {QStringLiteral("top"), top}, {QStringLiteral("middle"), middle}, {QStringLiteral("bottom"), bottom}};
    return QString::fromUtf8(QJsonDocument(out).toJson(QJsonDocument::Compact));
}

bool HuginnMenus::trigger(const QString &id)
{
    if (!id.startsWith(QStringLiteral("qt:")))
        return false;
    bool ok = false;
    HuginnMenuItem *it = s_items.value(id.mid(3).toInt(&ok));
    if (!ok || !it || !it->m_enabled || it->m_separator || it->m_menu)
        return false;
    QPointer<HuginnMenuItem> later(it);
    // after the answer has gone back (what it does may open a dialog and wait there)
    QMetaObject::invokeMethod(it, [later] { if (later) emit later->activated(); }, Qt::QueuedConnection);
    return true;
}

// ------------------------------------------------------------------------------------------------ on the bus
class HuginnMenuExport : public QObject
{
    Q_OBJECT
    Q_CLASSINFO("D-Bus Interface", "org.huginn.App")
public:
    using QObject::QObject;
public Q_SLOTS:
    Q_SCRIPTABLE QString Menus() { return HuginnMenus::menusJson(); }
    Q_SCRIPTABLE void Trigger(const QString &id) { HuginnMenus::trigger(id); }
};

static HuginnMenuExport *s_export = nullptr;

QPlatformMenuBar *HuginnMenus::createBar()
{
    if (qEnvironmentVariable("HUGINN_QT_MENUS") == QLatin1String("0"))
        return nullptr;
    QDBusConnection bus = QDBusConnection::sessionBus();
    if (!bus.isConnected() || !bus.interface())
        return nullptr;
    if (!s_export) {
        // Huginn's shell shows them; without it, the app's own menu bar stays in the window
        if (!bus.interface()->isServiceRegistered(QStringLiteral("org.huginn.Shell")))
            return nullptr;
        const QString name = QStringLiteral("org.huginn.App.p%1").arg(QCoreApplication::applicationPid());
        auto *exporter = new HuginnMenuExport(qApp);
        if (!bus.registerObject(QStringLiteral("/org/huginn/App"), exporter, QDBusConnection::ExportScriptableSlots)
            || !bus.registerService(name)) {
            bus.unregisterObject(QStringLiteral("/org/huginn/App"));
            delete exporter;
            return nullptr;
        }
        s_export = exporter;
        QObject::connect(qGuiApp, &QGuiApplication::focusWindowChanged, exporter, [](QWindow *w) {
            if (w)
                s_lastFocus = w;
        });
    }
    return new HuginnMenuBar;
}

#include "menus.moc"
