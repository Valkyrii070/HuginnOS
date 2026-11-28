// Qt apps' menu bars, shown in Huginn's top bar (the app's name, top left) instead of in the window.
//
// The app answers on the session bus as org.huginn.App.p<pid> (/org/huginn/App, org.huginn.App), as Huginn's own
// apps do (apps/huginn_menu.py): Menus() gives them as JSON, Trigger(id) does one. While Huginn's shell isn't there
// (or the person turned it off) the app keeps its menu bar in the window.
#pragma once

#include <QIcon>
#include <QKeySequence>
#include <QList>
#include <QObject>
#include <QPointer>
#include <QString>
#include <QWindow>
#include <qpa/qplatformmenu.h>

class HuginnMenu;

class HuginnMenuItem : public QPlatformMenuItem
{
    Q_OBJECT
public:
    HuginnMenuItem();
    ~HuginnMenuItem() override;

    void setText(const QString &text) override { m_text = text; }
    void setIcon(const QIcon &) override {}
    void setMenu(QPlatformMenu *menu) override;
    void setVisible(bool visible) override { m_visible = visible; }
    void setIsSeparator(bool separator) override { m_separator = separator; }
    void setFont(const QFont &) override {}
    void setRole(MenuRole role) override { m_role = role; }
    void setCheckable(bool checkable) override { m_checkable = checkable; }
    void setChecked(bool checked) override { m_checked = checked; }
#if QT_CONFIG(shortcut)
    void setShortcut(const QKeySequence &shortcut) override { m_shortcut = shortcut; }
#endif
    void setEnabled(bool enabled) override { m_enabled = enabled; }
    void setIconSize(int) override {}
    void setHasExclusiveGroup(bool exclusive) override { m_exclusive = exclusive; }

    int number() const { return m_number; }
    QString m_text;
    QKeySequence m_shortcut;
    QPointer<HuginnMenu> m_menu;
    MenuRole m_role = TextHeuristicRole;
    bool m_visible = true, m_separator = false, m_checkable = false, m_checked = false, m_enabled = true, m_exclusive = false;
private:
    int m_number;
};

class HuginnMenu : public QPlatformMenu
{
    Q_OBJECT
public:
    void insertMenuItem(QPlatformMenuItem *item, QPlatformMenuItem *before) override;
    void removeMenuItem(QPlatformMenuItem *item) override;
    void syncMenuItem(QPlatformMenuItem *) override {}
    void syncSeparatorsCollapsible(bool) override {}
    void setText(const QString &text) override { m_text = text; }
    void setIcon(const QIcon &) override {}
    void setEnabled(bool enabled) override { m_enabled = enabled; }
    bool isEnabled() const override { return m_enabled; }
    void setVisible(bool visible) override { m_visible = visible; }
    QPlatformMenuItem *menuItemAt(int position) const override;
    QPlatformMenuItem *menuItemForTag(quintptr tag) const override;
    QPlatformMenuItem *createMenuItem() const override { return new HuginnMenuItem; }
    QPlatformMenu *createSubMenu() const override { return new HuginnMenu; }

    void opening(int depth = 0);       // aboutToShow, here and in its submenus (apps fill some menus only then)
    void closing(int depth = 0);
    QString m_text;
    bool m_enabled = true, m_visible = true;
    QList<QPointer<HuginnMenuItem>> m_items;
};

class HuginnMenuBar : public QPlatformMenuBar
{
    Q_OBJECT
public:
    HuginnMenuBar();
    ~HuginnMenuBar() override;
    void insertMenu(QPlatformMenu *menu, QPlatformMenu *before) override;
    void removeMenu(QPlatformMenu *menu) override;
    void syncMenu(QPlatformMenu *) override {}
    void handleReparent(QWindow *window) override { m_window = window; }
    QWindow *parentWindow() const override { return m_window; }
    QPlatformMenu *menuForTag(quintptr tag) const override;
    QPlatformMenu *createMenu() const override { return new HuginnMenu; }

    QList<QPointer<HuginnMenu>> m_menus;
    QPointer<QWindow> m_window;
};

namespace HuginnMenus {
    // A menu bar for the top bar, or nullptr (Qt then shows the app's own in the window): not while Huginn's shell
    // isn't on the bus, HUGINN_QT_MENUS=0, or this process can't take its name.
    QPlatformMenuBar *createBar();
    QString menusJson();                       // (for tests too)
    bool trigger(const QString &id);
}
