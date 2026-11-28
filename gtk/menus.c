/* Old GTK 3 apps' menu bars (GtkMenuBar: Audacity, Geany, Thunar, FileZilla, wxWidgets apps…), shown in Huginn's
 * top bar instead of in the window. GtkApplication apps hand theirs over without this (the compositor's gtk_shell1);
 * this is for the rest, and replaces appmenu-gtk-module, which doesn't work on Wayland.
 *
 * Every GTK 3 app in Huginn's session loads it: GTK_MODULES=huginn-menus (huginn-desktop-session; on Wayland GTK
 * takes modules from nowhere else: settings.ini's gtk-modules is for X11 alone). While
 * Huginn's shell is on the session bus the app answers as org.huginn.App.p<pid> (/org/huginn/App, org.huginn.App),
 * as Huginn's own apps and Qt apps do: Menus() gives the menu bar of the window in front as JSON, Trigger(id) does
 * one of its items. The menu bar itself is hidden from the window, its shortcuts still work (can-activate-accel), and
 * it comes back if the shell goes away. HUGINN_GTK_MENUS=0 leaves an app's menu bar where it was.
 */
#include <gtk/gtk.h>
#include <string.h>
#include <unistd.h>

#define APP_PATH "/org/huginn/App"
#define MAX_DEPTH 4

static const char XML[] =
    "<node><interface name='org.huginn.App'>"
    "<method name='Menus'><arg type='s' direction='out'/></method>"
    "<method name='Trigger'><arg type='s' direction='in'/></method>"
    "</interface></node>";

typedef struct {
    GtkWidget *bar;         /* (weak) */
    GtkWidget *window;      /* (weak) the window it's in */
    gboolean app_visible;   /* what the app last asked for */
    guint busy;             /* we're changing its visibility ourselves */
} Bar;

static GDBusConnection *bus;
static gboolean disabled, shell_here, exported, tried_export;
static guint registration;
static GList *bars;                  /* Bar*, oldest first */
static GtkWidget *last_active;       /* (weak) the window that last had the keyboard */
static GHashTable *items;            /* number -> GtkMenuItem (weak) */
static guint next_number = 1;
static GQuark q_bar, q_number, q_watched;

/* ------------------------------------------------------------------------------------------------ hiding the bar */
static gboolean taking_over (void)
{
    return !disabled && shell_here && exported;
}

static void set_visible (Bar *b, gboolean visible)
{
    if (!b->bar || gtk_widget_get_visible (b->bar) == visible)
        return;
    b->busy++;
    gtk_widget_set_visible (b->bar, visible);
    b->busy--;
}

static void apply (Bar *b)
{
    set_visible (b, taking_over () ? FALSE : b->app_visible);
}

static void apply_all (void)
{
    for (GList *l = bars; l; l = l->next)
        apply (l->data);
}

static void on_visible (GtkWidget *bar, GParamSpec *pspec, Bar *b)
{
    if (b->busy)
        return;
    b->app_visible = gtk_widget_get_visible (bar);     /* the app showed or hid it */
    if (b->app_visible && taking_over ())
        set_visible (b, FALSE);
}

/* The menu items' shortcuts ask the menu bar whether they may act (GTK says no while it's hidden). */
static gboolean on_can_accel (GtkWidget *bar, guint signal_id, Bar *b)
{
    return taking_over () && gtk_widget_is_sensitive (bar);
}

static void on_active (GtkWindow *window, GParamSpec *pspec, gpointer data)
{
    if (!gtk_window_is_active (window) || last_active == GTK_WIDGET (window))
        return;
    if (last_active)
        g_object_remove_weak_pointer (G_OBJECT (last_active), (gpointer *) &last_active);
    last_active = GTK_WIDGET (window);
    g_object_add_weak_pointer (G_OBJECT (last_active), (gpointer *) &last_active);
}

static void forget (Bar *b)
{
    if (b->window)
        g_object_remove_weak_pointer (G_OBJECT (b->window), (gpointer *) &b->window);
    b->window = NULL;
}

static void bar_gone (gpointer data, GObject *was)
{
    Bar *b = data;
    b->bar = NULL;
    forget (b);
    bars = g_list_remove (bars, b);
    g_free (b);
}

static void release (Bar *b)
{
    /* out of its window: the app's again */
    GtkWidget *bar = b->bar;
    g_signal_handlers_disconnect_by_data (bar, b);
    set_visible (b, b->app_visible);
    g_object_weak_unref (G_OBJECT (bar), bar_gone, b);
    g_object_set_qdata (G_OBJECT (bar), q_bar, NULL);
    bar_gone (b, G_OBJECT (bar));
}

static void export (void);

static void adopt (GtkWidget *bar, GtkWidget *window)
{
    Bar *b = g_new0 (Bar, 1);
    b->bar = bar;
    b->window = window;
    b->app_visible = gtk_widget_get_visible (bar);
    g_object_add_weak_pointer (G_OBJECT (window), (gpointer *) &b->window);
    g_object_weak_ref (G_OBJECT (bar), bar_gone, b);
    g_object_set_qdata (G_OBJECT (bar), q_bar, b);
    g_signal_connect (bar, "notify::visible", G_CALLBACK (on_visible), b);
    g_signal_connect (bar, "can-activate-accel", G_CALLBACK (on_can_accel), b);
    if (!g_object_get_qdata (G_OBJECT (window), q_watched)) {
        g_object_set_qdata (G_OBJECT (window), q_watched, GINT_TO_POINTER (1));
        g_signal_connect (window, "notify::is-active", G_CALLBACK (on_active), NULL);
    }
    bars = g_list_append (bars, b);
    if (shell_here && !tried_export)
        export ();
    apply (b);
}

/* A menu bar the window shows as its menu bar: not one inside a header bar, toolbar, popover or menu. */
static gboolean fits (GtkWidget *bar, GtkWidget *top)
{
    if (!GTK_IS_WINDOW (top) || !gtk_widget_is_toplevel (top) || gtk_window_get_window_type (GTK_WINDOW (top)) != GTK_WINDOW_TOPLEVEL)
        return FALSE;
    for (GtkWidget *w = gtk_widget_get_parent (bar); w && w != top; w = gtk_widget_get_parent (w))
        if (GTK_IS_HEADER_BAR (w) || GTK_IS_TOOLBAR (w) || GTK_IS_TOOL_ITEM (w) || GTK_IS_POPOVER (w) || GTK_IS_MENU_SHELL (w))
            return FALSE;
    for (GList *l = bars; l; l = l->next)             /* one per window: the first */
        if (((Bar *) l->data)->window == top && ((Bar *) l->data)->bar != bar)
            return FALSE;
    return TRUE;
}

static void consider (GtkWidget *bar)
{
    GtkWidget *top = gtk_widget_get_toplevel (bar);
    Bar *b = g_object_get_qdata (G_OBJECT (bar), q_bar);
    if (b && b->window == top)
        return;
    if (b)
        release (b);
    if (fits (bar, top))
        adopt (bar, top);
}

static gboolean on_hierarchy (GSignalInvocationHint *hint, guint n, const GValue *params, gpointer data)
{
    GObject *o = g_value_get_object (&params[0]);
    if (GTK_IS_MENU_BAR (o))
        consider (GTK_WIDGET (o));
    return TRUE;
}

/* ------------------------------------------------------------------------------------------------ as the shell reads them */
static void js (GString *s, const char *text)
{
    g_string_append_c (s, '"');
    for (const unsigned char *p = (const unsigned char *) (text ? text : ""); *p; p++) {
        if (*p == '"' || *p == '\\')
            g_string_append_printf (s, "\\%c", *p);
        else if (*p < 0x20)
            g_string_append_printf (s, "\\u%04x", *p);
        else
            g_string_append_c (s, *p);
    }
    g_string_append_c (s, '"');
}

static GtkWidget *first_label (GtkWidget *w)
{
    if (GTK_IS_LABEL (w))
        return w;
    if (!GTK_IS_CONTAINER (w))
        return NULL;
    GList *kids = gtk_container_get_children (GTK_CONTAINER (w));
    GtkWidget *found = NULL;
    for (GList *l = kids; l && !found; l = l->next)
        found = first_label (l->data);
    g_list_free (kids);
    return found;
}

/* What the item says, as shown: no mnemonic underline, no markup, no "(_O)" mnemonic in brackets. */
static char *label_of (GtkWidget *item)
{
    GtkWidget *label = first_label (gtk_bin_get_child (GTK_BIN (item)));
    char *text = g_strdup (label ? gtk_label_get_text (GTK_LABEL (label)) : "");
    char *tab = strchr (text, '\t');
    if (tab)
        *tab = 0;
    g_strstrip (text);
    size_t n = strlen (text);
    if (n >= 3 && text[n - 1] == ')' && text[n - 3] == '(' && g_ascii_isalnum (text[n - 2])) {
        text[n - 3] = 0;
        g_strstrip (text);
    }
    if (!g_utf8_validate (text, -1, NULL)) {
        char *valid = g_utf8_make_valid (text, -1);
        g_free (text);
        text = valid;
    }
    return text;
}

static const struct { const char *gdk, *huginn; } KEY_NAMES[] = {
    {"plus", "+"}, {"minus", "-"}, {"equal", "="}, {"comma", ","}, {"period", "."}, {"slash", "/"}, {"backslash", "\\"},
    {"Return", "Enter"}, {"KP_Enter", "Enter"}, {"BackSpace", "Backspace"}, {"Delete", "Del"}, {"Escape", "Esc"},
    {"Page_Up", "PgUp"}, {"Page_Down", "PgDown"}, {"space", "Space"}, {"Tab", "Tab"}, {"Home", "Home"}, {"End", "End"},
    {"Insert", "Ins"}, {"bracketleft", "["}, {"bracketright", "]"}, {"semicolon", ";"}, {"apostrophe", "'"},
    {"grave", "`"}, {"question", "?"}, {"exclam", "!"}, {"asterisk", "*"}, {"underscore", "_"}, {"Left", "Left"},
    {"Right", "Right"}, {"Up", "Up"}, {"Down", "Down"},
};

/* "Ctrl+Shift+Z", as Huginn writes keys (shell/huginn_gtkmenus.py writes GTK's the same way) */
static char *key_text (guint key, GdkModifierType mods)
{
    const char *name = gdk_keyval_name (gdk_keyval_to_lower (key));
    if (!name)
        return g_strdup ("");
    GString *s = g_string_new (NULL);
    if (mods & GDK_CONTROL_MASK)
        g_string_append (s, "Ctrl+");
    if (mods & GDK_MOD1_MASK)
        g_string_append (s, "Alt+");
    if (mods & GDK_SHIFT_MASK)
        g_string_append (s, "Shift+");
    if (mods & (GDK_SUPER_MASK | GDK_MOD4_MASK))
        g_string_append (s, "Super+");
    if (mods & GDK_META_MASK)
        g_string_append (s, "Meta+");
    if (mods & GDK_HYPER_MASK)
        g_string_append (s, "Hyper+");
    for (guint i = 0; i < G_N_ELEMENTS (KEY_NAMES); i++)
        if (!strcmp (name, KEY_NAMES[i].gdk)) {
            g_string_append (s, KEY_NAMES[i].huginn);
            return g_string_free (s, FALSE);
        }
    if (strlen (name) == 1) {
        g_string_append_c (s, g_ascii_toupper (name[0]));
    } else {
        char *spaced = g_strdelimit (g_strdup (name), "_", ' ');
        g_string_append (s, spaced);
        g_free (spaced);
    }
    return g_string_free (s, FALSE);
}

static gboolean same_closure (GtkAccelKey *key, GClosure *closure, gpointer data)
{
    return closure == data;
}

/* Its shortcut: one set on its label (menus made from a GMenuModel), else the accel group's (add_accelerator, or an
 * accel path as GtkUIManager gives them) */
static char *keys_of (GtkWidget *item)
{
    guint key = 0;
    GdkModifierType mods = 0;
    GtkWidget *child = gtk_bin_get_child (GTK_BIN (item));
    if (GTK_IS_ACCEL_LABEL (child))
        gtk_accel_label_get_accel (GTK_ACCEL_LABEL (child), &key, &mods);
    if (!key) {
        GList *closures = gtk_widget_list_accel_closures (item);
        for (GList *l = closures; l && !key; l = l->next) {
            GtkAccelGroup *group = gtk_accel_group_from_accel_closure (l->data);
            GtkAccelKey *k = group ? gtk_accel_group_find (group, same_closure, l->data) : NULL;
            if (k && k->accel_key && (k->accel_flags & GTK_ACCEL_VISIBLE)) {
                key = k->accel_key;
                mods = k->accel_mods;
            }
        }
        g_list_free (closures);
    }
    return key ? key_text (key, mods) : g_strdup ("");
}

static void item_gone (gpointer number, GObject *was)
{
    g_hash_table_remove (items, number);
}

static guint number_of (GtkWidget *item)
{
    guint n = GPOINTER_TO_UINT (g_object_get_qdata (G_OBJECT (item), q_number));
    if (!n) {
        n = next_number++;
        g_object_set_qdata (G_OBJECT (item), q_number, GUINT_TO_POINTER (n));
        g_hash_table_insert (items, GUINT_TO_POINTER (n), item);
        g_object_weak_ref (G_OBJECT (item), item_gone, GUINT_TO_POINTER (n));
    }
    return n;
}

/* Checked or not, and whether it's one of a group (radio). Items made from a GMenuModel are all check items to GTK,
 * and the role their action gives them doesn't read back (GTK 3.24 says "normal" for all): those with a check or radio
 * mark keep room for it, and radio ones are drawn as radio. */
static gboolean check_state (GtkWidget *item, gboolean *checked, gboolean *radio)
{
    if (!GTK_IS_CHECK_MENU_ITEM (item))
        return FALSE;
    GtkCheckMenuItem *check = GTK_CHECK_MENU_ITEM (item);
    if (g_object_class_find_property (G_OBJECT_GET_CLASS (item), "action-role")) {
        int role = 0, room = 0;
        g_object_get (item, "action-role", &role, NULL);
        if (role == 0) {
            gtk_menu_item_toggle_size_request (GTK_MENU_ITEM (item), &room);
            if (room <= 0)
                return FALSE;
        }
        *radio = role == 2 || gtk_check_menu_item_get_draw_as_radio (check);
    } else {
        *radio = GTK_IS_RADIO_MENU_ITEM (item) || gtk_check_menu_item_get_draw_as_radio (check);
    }
    *checked = gtk_check_menu_item_get_active (check);
    return TRUE;
}

static GList *children_of (GtkWidget *menu)
{
    return menu ? gtk_container_get_children (GTK_CONTAINER (menu)) : NULL;
}

/* An item with a menu of its own is opened, as GTK opens it: "activate" (menus the app fills as they open then have
 * their items, and their items say whether they can be used). */
static GtkWidget *open_menu (GtkWidget *item)
{
    GtkWidget *menu = gtk_menu_item_get_submenu (GTK_MENU_ITEM (item));
    if (menu && gtk_widget_is_sensitive (item))
        g_signal_emit_by_name (item, "activate");
    return gtk_menu_item_get_submenu (GTK_MENU_ITEM (item));
}

typedef struct {
    GtkWidget *about, *settings, *quit;
} Special;

static gboolean is_line (GtkWidget *item)
{
    G_GNUC_BEGIN_IGNORE_DEPRECATIONS                    /* (tear-off items: gone from GTK, still in old apps) */
    gboolean tearoff = GTK_IS_TEAROFF_MENU_ITEM (item);
    G_GNUC_END_IGNORE_DEPRECATIONS
    return tearoff || GTK_IS_SEPARATOR_MENU_ITEM (item) || !gtk_bin_get_child (GTK_BIN (item));
}

/* The app's About, Settings and Quit go where they are in every Huginn app's menu (first, and last), by what they say */
static void find_special (GtkWidget *menu, Special *s, const char *app)
{
    char *app_lower = g_utf8_strdown (app, -1);
    char *configure = g_strconcat ("configure ", app_lower, NULL), *quit_app = g_strconcat ("quit ", app_lower, NULL),
         *exit_app = g_strconcat ("exit ", app_lower, NULL);
    GList *kids = children_of (menu);
    for (GList *l = kids; l; l = l->next) {
        GtkWidget *it = l->data;
        if (!GTK_IS_MENU_ITEM (it) || !gtk_widget_get_visible (it) || is_line (it) || gtk_menu_item_get_submenu (GTK_MENU_ITEM (it)))
            continue;
        char *label = label_of (it), *t = g_utf8_strdown (label, -1);
        GString *g = g_string_new (t);
        for (const char *dots = "…"; strstr (g->str, dots);)
            g_string_erase (g, strstr (g->str, dots) - g->str, strlen (dots));
        while (strstr (g->str, "..."))
            g_string_erase (g, strstr (g->str, "...") - g->str, 3);
        g_strstrip (g->str);
        const char *x = g->str;
        if (!s->about && g_str_has_prefix (x, "about ") && !strstr (x, " gtk") && !strstr (x, " qt") && !strstr (x, "kde"))
            s->about = it;
        else if (!s->settings && (!strcmp (x, "preferences") || !strcmp (x, "settings") || !strcmp (x, "options") || !strcmp (x, configure)))
            s->settings = it;
        else if (!s->quit && (!strcmp (x, "quit") || !strcmp (x, "exit") || !strcmp (x, quit_app) || !strcmp (x, exit_app)))
            s->quit = it;
        g_string_free (g, TRUE);
        g_free (label);
        g_free (t);
    }
    g_list_free (kids);
    g_free (app_lower);
    g_free (configure);
    g_free (quit_app);
    g_free (exit_app);
}

static void entry (GString *s, const char *label, const char *id, const char *keys, gboolean enabled)
{
    g_string_append (s, "{\"label\":");
    js (s, label);
    g_string_append (s, ",\"id\":");
    js (s, id);
    g_string_append (s, ",\"keys\":");
    js (s, keys);
    g_string_append_printf (s, ",\"enabled\":%s}", enabled ? "true" : "false");
}

static void mine (GString *s, GtkWidget *it, const char *label)
{
    char *id = g_strdup_printf ("gtk3:%u", number_of (it)), *keys = keys_of (it);
    entry (s, label, id, keys, gtk_widget_is_sensitive (it));
    g_free (id);
    g_free (keys);
}

/* The menu's items as JSON (into s, "[...]"); FALSE when there are none */
static gboolean items_of (GString *s, GtkWidget *menu, const Special *sp, gboolean enabled, int depth)
{
    gboolean any = FALSE, line = FALSE;
    g_string_append_c (s, '[');
    GList *kids = children_of (menu);
    for (GList *l = kids; l; l = l->next) {
        GtkWidget *it = l->data;
        if (!GTK_IS_MENU_ITEM (it) || !gtk_widget_get_visible (it) || it == sp->about || it == sp->settings || it == sp->quit)
            continue;
        if (is_line (it)) {
            line = any;
            continue;
        }
        gboolean on = enabled && gtk_widget_get_sensitive (it);
        GString *row = g_string_new (NULL);
        char *label = label_of (it);
        char *id = g_strdup_printf ("gtk3:%u", number_of (it));
        gboolean checked = FALSE, radio = FALSE, keep = TRUE;
        if (gtk_menu_item_get_submenu (GTK_MENU_ITEM (it))) {
            GtkWidget *sub = depth < MAX_DEPTH ? open_menu (it) : NULL;
            GString *kids_json = g_string_new (NULL);
            keep = sub && items_of (kids_json, sub, sp, on && gtk_widget_get_sensitive (sub), depth + 1);
            if (keep) {
                g_string_append (row, "{\"label\":");
                js (row, label);
                g_string_append (row, ",\"id\":");
                js (row, id);
                g_string_append_printf (row, ",\"keys\":\"\",\"enabled\":%s,\"children\":%s}", on ? "true" : "false", kids_json->str);
            }
            g_string_free (kids_json, TRUE);
        } else {
            char *keys = keys_of (it);
            entry (row, label, id, keys, on);
            g_free (keys);
            if (check_state (it, &checked, &radio)) {
                g_string_truncate (row, row->len - 1);
                g_string_append_printf (row, ",\"checked\":%s%s}", checked ? "true" : "false", radio ? ",\"radio\":true" : "");
            }
        }
        if (keep) {
            if (any)
                g_string_append_c (s, ',');
            if (line)
                g_string_append (s, "{\"sep\":true},");
            g_string_append (s, row->str);
            any = TRUE;
            line = FALSE;
        }
        g_string_free (row, TRUE);
        g_free (label);
        g_free (id);
    }
    g_list_free (kids);
    g_string_append_c (s, ']');
    return any;
}

static Bar *front_bar (void)
{
    /* the window with the keyboard (or the last one that had it: the top bar's menu takes it meanwhile), or the one a
     * dialog belongs to; else the newest menu bar in a window that's showing */
    GtkWidget *w = NULL;
    GList *tops = gtk_window_list_toplevels ();
    for (GList *l = tops; l; l = l->next)
        if (gtk_window_is_active (l->data))
            w = l->data;
    g_list_free (tops);
    if (!w)
        w = last_active;
    for (GtkWidget *x = w; x; x = GTK_WIDGET (gtk_window_get_transient_for (GTK_WINDOW (x))))
        for (GList *l = bars; l; l = l->next)
            if (((Bar *) l->data)->window == x && ((Bar *) l->data)->bar)
                return l->data;
    for (GList *l = g_list_last (bars); l; l = l->prev) {
        Bar *b = l->data;
        if (b->bar && b->window && gtk_widget_get_visible (b->window))
            return b;
    }
    return NULL;
}

static const char *app_name (void)
{
    /* the name the app gave itself; else GDK's for it (the program's name with a capital: "geany" -> "Geany") */
    const char *name = g_get_application_name (), *program = g_get_prgname ();
    if (!name || !*name || (program && !strcmp (name, program)))
        name = gdk_get_program_class ();
    return name && *name ? name : "App";
}

static char *menus_json (void)
{
    const char *app = app_name ();
    Bar *b = front_bar ();
    GList *tops = b ? children_of (b->bar) : NULL;
    Special s = {0};
    GString *groups = g_string_new ("[");
    gboolean first = TRUE;
    for (GList *l = tops; l; l = l->next) {             /* open each menu, then find About, Settings and Quit */
        GtkWidget *top = l->data;
        if (GTK_IS_MENU_ITEM (top) && gtk_widget_get_visible (top) && gtk_menu_item_get_submenu (GTK_MENU_ITEM (top)))
            find_special (open_menu (top), &s, app);
    }
    for (GList *l = tops; l; l = l->next) {
        GtkWidget *top = l->data;
        if (!GTK_IS_MENU_ITEM (top) || !gtk_widget_get_visible (top) || is_line (top))
            continue;
        GtkWidget *menu = gtk_menu_item_get_submenu (GTK_MENU_ITEM (top));
        if (!menu)
            continue;                                   /* (an item right on the bar: nothing to show it in) */
        GString *its = g_string_new (NULL);
        if (items_of (its, menu, &s, gtk_widget_get_sensitive (top) && gtk_widget_get_sensitive (menu), 0)) {
            char *name = label_of (top);
            g_string_append (groups, first ? "{\"name\":" : ",{\"name\":");
            js (groups, name);
            g_string_append_printf (groups, ",\"items\":%s}", its->str);
            first = FALSE;
            g_free (name);
        }
        g_string_free (its, TRUE);
    }
    g_list_free (tops);
    g_string_append_c (groups, ']');

    GString *out = g_string_new ("{\"app\":");
    js (out, app);
    g_string_append (out, ",\"key\":\"\",\"toolkit\":\"gtk3\",\"settings\":");
    g_string_append (out, s.settings ? "true" : "false");
    g_string_append (out, ",\"groups\":");
    g_string_append (out, groups->str);
    g_string_free (groups, TRUE);
    char *about = g_strconcat ("About ", app, NULL), *settings = g_strconcat (app, " Settings…", NULL),
         *quit = g_strconcat ("Quit ", app, NULL);
    g_string_append (out, ",\"top\":[");
    if (s.about) {
        char *label = label_of (s.about);
        mine (out, s.about, label);
        g_free (label);
    } else {
        entry (out, about, "shell:aboutApp", "", TRUE);
    }
    g_string_append_c (out, ',');
    if (s.settings)
        mine (out, s.settings, settings);
    else
        entry (out, settings, "", "Ctrl+,", FALSE);
    g_string_append (out, "],\"middle\":[");
    entry (out, "Show all its windows", "shell:appWindows", "", TRUE);
    g_string_append_c (out, ',');
    entry (out, "Keep in the dock", "shell:pin", "", TRUE);
    g_string_append (out, "],\"bottom\":[");
    entry (out, "Keep on Top", "shell:ontop", "Super+Ctrl+T", TRUE);
    g_string_append_c (out, ',');
    entry (out, "Minimise", "shell:minimise", "", TRUE);
    g_string_append_c (out, ',');
    entry (out, "Close window", "shell:close", "Ctrl+W", TRUE);
    g_string_append_c (out, ',');
    if (s.quit)
        mine (out, s.quit, quit);
    else
        entry (out, quit, "shell:quit", "Ctrl+Q", TRUE);
    g_string_append (out, "]}");
    g_free (about);
    g_free (settings);
    g_free (quit);
    return g_string_free (out, FALSE);
}

/* ------------------------------------------------------------------------------------------------ doing one */
static gboolean activate_later (gpointer data)
{
    GWeakRef *ref = data;
    GtkWidget *item = g_weak_ref_get (ref);
    if (item) {
        if (gtk_widget_is_sensitive (item))
            gtk_menu_item_activate (GTK_MENU_ITEM (item));
        g_object_unref (item);
    }
    g_weak_ref_clear (ref);
    g_free (ref);
    return G_SOURCE_REMOVE;
}

static gboolean trigger (const char *id)
{
    if (!g_str_has_prefix (id, "gtk3:"))
        return FALSE;
    char *end = NULL;
    guint64 n = g_ascii_strtoull (id + 5, &end, 10);
    if (!n || !end || *end || n > G_MAXUINT)
        return FALSE;
    GtkWidget *item = g_hash_table_lookup (items, GUINT_TO_POINTER ((guint) n));
    if (!item || !gtk_widget_is_sensitive (item) || !gtk_widget_get_visible (item) || is_line (item)
        || gtk_menu_item_get_submenu (GTK_MENU_ITEM (item)))
        return FALSE;
    GWeakRef *ref = g_new0 (GWeakRef, 1);
    g_weak_ref_init (ref, item);
    /* after the answer has gone back (what it does may open a dialog and wait there) */
    g_idle_add (activate_later, ref);
    return TRUE;
}

/* ------------------------------------------------------------------------------------------------ on the bus */
static void method_call (GDBusConnection *c, const char *sender, const char *path, const char *iface,
                         const char *method, GVariant *params, GDBusMethodInvocation *inv, gpointer data)
{
    if (!strcmp (method, "Menus")) {
        char *json = menus_json ();
        g_dbus_method_invocation_return_value (inv, g_variant_new ("(s)", json));
        g_free (json);
    } else if (!strcmp (method, "Trigger")) {
        const char *id = NULL;
        g_variant_get (params, "(&s)", &id);
        trigger (id);
        g_dbus_method_invocation_return_value (inv, NULL);
    } else {
        g_dbus_method_invocation_return_dbus_error (inv, "org.freedesktop.DBus.Error.UnknownMethod", method);
    }
}

static const GDBusInterfaceVTable VTABLE = {method_call, NULL, NULL, {0}};

/* Answer as org.huginn.App.p<pid>, there and then (so the menu bar is gone before the window is first drawn) */
static void export (void)
{
    tried_export = TRUE;
    GError *err = NULL;
    GDBusNodeInfo *info = g_dbus_node_info_new_for_xml (XML, NULL);
    registration = g_dbus_connection_register_object (bus, APP_PATH, info->interfaces[0], &VTABLE, NULL, NULL, &err);
    g_dbus_node_info_unref (info);
    if (!registration) {
        g_clear_error (&err);
        return;                                         /* (something else in the app answers there already) */
    }
    char *name = g_strdup_printf ("org.huginn.App.p%d", (int) getpid ());
    GVariant *got = g_dbus_connection_call_sync (bus, "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                                 "RequestName", g_variant_new ("(su)", name, 4u /* do not queue */),
                                                 G_VARIANT_TYPE ("(u)"), G_DBUS_CALL_FLAGS_NONE, 2000, NULL, &err);
    guint answer = 0;
    if (got) {
        g_variant_get (got, "(u)", &answer);
        g_variant_unref (got);
    }
    g_clear_error (&err);
    g_free (name);
    if (answer == 1) {
        exported = TRUE;
    } else {
        g_dbus_connection_unregister_object (bus, registration);
        registration = 0;
    }
}

static void shell_appeared (GDBusConnection *c, const char *name, const char *owner, gpointer data)
{
    shell_here = TRUE;
    if (bars && !tried_export)
        export ();
    apply_all ();
}

static void shell_vanished (GDBusConnection *c, const char *name, gpointer data)
{
    shell_here = FALSE;                                 /* (the menu bars come back until it's here again) */
    apply_all ();
}

G_MODULE_EXPORT void gtk_module_init (gint *argc, gchar ***argv)
{
    static gboolean done;
    if (done)
        return;
    done = TRUE;
    const char *off = g_getenv ("HUGINN_GTK_MENUS");
    disabled = off && !strcmp (off, "0");
    if (disabled)
        return;
    bus = g_bus_get_sync (G_BUS_TYPE_SESSION, NULL, NULL);
    if (!bus)
        return;
    q_bar = g_quark_from_static_string ("huginn-menus-bar");
    q_number = g_quark_from_static_string ("huginn-menus-number");
    q_watched = g_quark_from_static_string ("huginn-menus-watched");
    items = g_hash_table_new (NULL, NULL);
    GVariant *got = g_dbus_connection_call_sync (bus, "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                                 "NameHasOwner", g_variant_new ("(s)", "org.huginn.Shell"),
                                                 G_VARIANT_TYPE ("(b)"), G_DBUS_CALL_FLAGS_NONE, 2000, NULL, NULL);
    if (got) {
        g_variant_get (got, "(b)", &shell_here);
        g_variant_unref (got);
    }
    g_bus_watch_name_on_connection (bus, "org.huginn.Shell", G_BUS_NAME_WATCHER_FLAGS_NONE, shell_appeared, shell_vanished, NULL, NULL);
    g_type_class_unref (g_type_class_ref (GTK_TYPE_WIDGET));  /* (its signals exist once its class does; GTK keeps it) */
    g_signal_add_emission_hook (g_signal_lookup ("hierarchy-changed", GTK_TYPE_WIDGET), 0, on_hierarchy, NULL, NULL);
    /* (a module stays loaded: what it hooked into stays valid) */
}
