// Huginn's widget style for Qt apps that aren't Huginn's own (Fusion underneath; what shows is drawn here, in
// Huginn's shapes and the realm's colours, which come in the palette from Huginn's platform theme).
//
// Rounded controls (7 px, as tokens.json's radius.control), cards and menus (10 px), the accent for what's chosen
// and for the button a dialog would press, thin scroll bars without arrows, flat tool bars and headers.
#include <QAbstractItemView>
#include <QAbstractSpinBox>
#include <QApplication>
#include <QCheckBox>
#include <QComboBox>
#include <QHeaderView>
#include <QLineEdit>
#include <QMenu>
#include <QPainter>
#include <QPainterPath>
#include <QProxyStyle>
#include <QPushButton>
#include <QRadioButton>
#include <QScrollBar>
#include <QSlider>
#include <QStyleFactory>
#include <QStyleOption>
#include <QStylePlugin>
#include <QTabBar>
#include <QToolButton>
#include <QtMath>

namespace {

constexpr qreal CONTROL = 7;      // tokens.json radius.control
constexpr qreal CARD = 10;        // radius.card (menus, tab panes, group boxes)
constexpr qreal ITEM = 6;         // a chosen row in a menu or a list

bool isDark(const QPalette &p) { return p.color(QPalette::Window).lightness() < 128; }

QColor alpha(QColor c, int a)
{
    c.setAlpha(a);
    return c;
}

QColor mix(const QColor &a, const QColor &b, qreal t)
{
    return QColor::fromRgbF(a.redF() + (b.redF() - a.redF()) * t, a.greenF() + (b.greenF() - a.greenF()) * t,
                            a.blueF() + (b.blueF() - a.blueF()) * t, a.alphaF() + (b.alphaF() - a.alphaF()) * t);
}

QColor ink(const QPalette &p) { return p.color(QPalette::Active, QPalette::WindowText); }
QColor hoverTint(const QPalette &p) { return alpha(ink(p), isDark(p) ? 22 : 24); }
QColor pressTint(const QPalette &p) { return alpha(ink(p), isDark(p) ? 38 : 40); }
QColor line(const QPalette &p) { return p.color(QPalette::Active, QPalette::Mid); }
QColor accent(const QPalette &p, QPalette::ColorGroup g = QPalette::Active) { return p.color(g, QPalette::Accent); }
QColor ring(const QPalette &p) { return alpha(accent(p), 190); }

QRectF crisp(const QRect &r) { return QRectF(r).adjusted(0.5, 0.5, -0.5, -0.5); }

void chevron(QPainter *p, const QRectF &box, Qt::ArrowType dir, const QColor &c, qreal size = 0)
{
    if (size <= 0)
        size = qBound<qreal>(5, qMin(box.width(), box.height()) * 0.55, 9);
    const QPointF m = box.center();
    const qreal s = size / 2, h = size / 4;
    QPainterPath path;
    switch (dir) {
    case Qt::UpArrow:    path.moveTo(m.x() - s, m.y() + h); path.lineTo(m.x(), m.y() - h); path.lineTo(m.x() + s, m.y() + h); break;
    case Qt::LeftArrow:  path.moveTo(m.x() + h, m.y() - s); path.lineTo(m.x() - h, m.y()); path.lineTo(m.x() + h, m.y() + s); break;
    case Qt::RightArrow: path.moveTo(m.x() - h, m.y() - s); path.lineTo(m.x() + h, m.y()); path.lineTo(m.x() - h, m.y() + s); break;
    default:             path.moveTo(m.x() - s, m.y() - h); path.lineTo(m.x(), m.y() + h); path.lineTo(m.x() + s, m.y() - h); break;
    }
    p->save();
    p->setRenderHint(QPainter::Antialiasing);
    p->setPen(QPen(c, 1.5, Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin));
    p->setBrush(Qt::NoBrush);
    p->drawPath(path);
    p->restore();
}

void tick(QPainter *p, const QRectF &b, const QColor &c)
{
    QPainterPath path;
    path.moveTo(b.left() + b.width() * 0.24, b.top() + b.height() * 0.53);
    path.lineTo(b.left() + b.width() * 0.43, b.top() + b.height() * 0.71);
    path.lineTo(b.left() + b.width() * 0.77, b.top() + b.height() * 0.31);
    p->save();
    p->setRenderHint(QPainter::Antialiasing);
    p->setPen(QPen(c, qMax<qreal>(1.6, b.width() / 8), Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin));
    p->setBrush(Qt::NoBrush);
    p->drawPath(path);
    p->restore();
}

struct Look {
    bool enabled, hover, pressed, on, focus, isDefault, flat;
};

Look lookOf(const QStyleOption *o)
{
    const QStyle::State s = o->state;
    return {bool(s & QStyle::State_Enabled), bool(s & QStyle::State_MouseOver), bool(s & QStyle::State_Sunken),
            bool(s & QStyle::State_On), bool(s & QStyle::State_HasFocus) && bool(s & QStyle::State_KeyboardFocusChange), false, false};
}

// a button: the realm's accent for the one a dialog would press, else the button colour with a fine line around
void button(QPainter *p, const QRect &rect, const QPalette &pal, const Look &l, qreal radius = CONTROL)
{
    const QRectF r = crisp(rect);
    p->save();
    p->setRenderHint(QPainter::Antialiasing);
    if (!l.enabled)
        p->setOpacity(0.5);
    if (l.isDefault && l.enabled) {
        QColor fill = accent(pal);
        if (l.pressed)
            fill = isDark(pal) ? fill.darker(118) : fill.darker(112);
        else if (l.hover)
            fill = isDark(pal) ? fill.lighter(108) : fill.lighter(112);
        p->setPen(Qt::NoPen);
        p->setBrush(fill);
        p->drawRoundedRect(r, radius, radius);
    } else if (!l.flat || l.hover || l.pressed || l.on) {
        if (!l.flat) {
            p->setPen(QPen(line(pal), 1));
            p->setBrush(pal.color(QPalette::Button));
            p->drawRoundedRect(r, radius, radius);
        }
        if (l.pressed || l.on || l.hover) {
            p->setPen(Qt::NoPen);
            p->setBrush(l.pressed ? pressTint(pal) : l.on ? (l.hover ? pressTint(pal) : alpha(ink(pal), isDark(pal) ? 30 : 32)) : hoverTint(pal));
            p->drawRoundedRect(r, radius, radius);
        }
    }
    if (l.focus) {
        p->setOpacity(1);
        p->setPen(QPen(ring(pal), 2));
        p->setBrush(Qt::NoBrush);
        p->drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius - 0.5, radius - 0.5);
    }
    p->restore();
}

// a field you type in: the view's colour, a fine line, the accent around it while it has the keyboard
void field(QPainter *p, const QRect &rect, const QPalette &pal, bool enabled, bool focus, bool hover)
{
    const QRectF r = crisp(rect);
    p->save();
    p->setRenderHint(QPainter::Antialiasing);
    p->setBrush(pal.color(enabled ? QPalette::Active : QPalette::Disabled, QPalette::Base));
    QColor edge = line(pal);
    if (hover && enabled && !focus)
        edge = mix(edge, ink(pal), 0.18);
    p->setPen(QPen(enabled ? edge : alpha(edge, 120), 1));
    p->drawRoundedRect(r, CONTROL, CONTROL);
    if (focus && enabled) {
        p->setPen(QPen(ring(pal), 2));
        p->setBrush(Qt::NoBrush);
        p->drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), CONTROL - 0.5, CONTROL - 0.5);
    }
    p->restore();
}

// a rounded rectangle with only some corners rounded (a row chosen across a table's columns)
QPainterPath roundedSome(const QRectF &r, qreal rad, bool left, bool right)
{
    QPainterPath path;
    const qreal l = left ? rad : 0, rr = right ? rad : 0;
    path.moveTo(r.left() + l, r.top());
    path.lineTo(r.right() - rr, r.top());
    if (rr) path.quadTo(r.right(), r.top(), r.right(), r.top() + rr);
    path.lineTo(r.right(), r.bottom() - rr);
    if (rr) path.quadTo(r.right(), r.bottom(), r.right() - rr, r.bottom());
    path.lineTo(r.left() + l, r.bottom());
    if (l) path.quadTo(r.left(), r.bottom(), r.left(), r.bottom() - l);
    path.lineTo(r.left(), r.top() + l);
    if (l) path.quadTo(r.left(), r.top(), r.left() + l, r.top());
    path.closeSubpath();
    return path;
}

bool translucent(const QWidget *w) { return w && w->testAttribute(Qt::WA_TranslucentBackground); }

} // namespace

class HuginnStyle : public QProxyStyle
{
    Q_OBJECT
public:
    HuginnStyle() : QProxyStyle(QStyleFactory::create(QStringLiteral("Fusion"))) {}

    // ---------------------------------------------------------------------------------------------- shapes
    void drawPrimitive(PrimitiveElement pe, const QStyleOption *o, QPainter *p, const QWidget *w) const override
    {
        switch (pe) {
        case PE_PanelButtonCommand: {
            Look l = lookOf(o);
            if (auto b = qstyleoption_cast<const QStyleOptionButton *>(o)) {
                l.isDefault = b->features & QStyleOptionButton::DefaultButton;
                l.flat = b->features & QStyleOptionButton::Flat;
            }
            button(p, o->rect, o->palette, l);
            return;
        }
        case PE_PanelButtonBevel:
            button(p, o->rect, o->palette, lookOf(o));
            return;
        case PE_PanelButtonTool: {
            Look l = lookOf(o);
            l.flat = true;
            if (!(o->state & State_AutoRaise) && !(o->state & (State_MouseOver | State_Sunken | State_On)) && w && !qobject_cast<const QToolButton *>(w))
                l.flat = false;
            button(p, o->rect, o->palette, l, 6);
            return;
        }
        case PE_FrameDefaultButton:
        case PE_FrameFocusRect:
        case PE_FrameButtonTool:
        case PE_FrameStatusBarItem:
        case PE_PanelMenuBar:
        case PE_PanelToolBar:
        case PE_FrameTabBarBase:
        case PE_IndicatorToolBarHandle:
            return;
        case PE_IndicatorToolBarSeparator: {
            const bool horiz = o->state & State_Horizontal;
            const QRect r = o->rect;
            p->fillRect(horiz ? QRect(r.center().x(), r.top() + 4, 1, r.height() - 8) : QRect(r.left() + 4, r.center().y(), r.width() - 8, 1), alpha(line(o->palette), 200));
            return;
        }
        case PE_PanelLineEdit:
            if (w && (qobject_cast<const QComboBox *>(w->parentWidget()) || qobject_cast<const QAbstractSpinBox *>(w->parentWidget())))
                return;                                      // (the combo box or spin box draws it)
            if (auto f = qstyleoption_cast<const QStyleOptionFrame *>(o)) {
                if (f->lineWidth > 0)
                    field(p, o->rect, o->palette, o->state & State_Enabled, o->state & State_HasFocus, o->state & State_MouseOver);
                else
                    p->fillRect(o->rect, o->palette.base());
            }
            return;
        case PE_FrameLineEdit:
            field(p, o->rect, o->palette, o->state & State_Enabled, o->state & State_HasFocus, o->state & State_MouseOver);
            return;
        case PE_IndicatorCheckBox:
        case PE_IndicatorItemViewItemCheck: {
            const QRectF r = crisp(QRect(o->rect.topLeft(), QSize(qMin(o->rect.width(), o->rect.height()), qMin(o->rect.width(), o->rect.height())))
                                       .translated(0, (o->rect.height() - qMin(o->rect.width(), o->rect.height())) / 2));
            const bool enabled = o->state & State_Enabled, on = o->state & State_On, partly = o->state & State_NoChange;
            p->save();
            p->setRenderHint(QPainter::Antialiasing);
            if (!enabled)
                p->setOpacity(0.5);
            if (on || partly) {
                QColor fill = accent(o->palette);
                if (o->state & State_Sunken)
                    fill = fill.darker(115);
                p->setPen(Qt::NoPen);
                p->setBrush(fill);
                p->drawRoundedRect(r, 4, 4);
                const QColor mark = o->palette.color(QPalette::HighlightedText);
                if (partly) {
                    p->setPen(QPen(mark, 1.8, Qt::SolidLine, Qt::RoundCap));
                    p->drawLine(QPointF(r.left() + r.width() * 0.28, r.center().y()), QPointF(r.right() - r.width() * 0.28, r.center().y()));
                } else {
                    tick(p, r, mark);
                }
            } else {
                p->setPen(QPen(o->state & State_MouseOver && enabled ? mix(line(o->palette), accent(o->palette), 0.6) : mix(line(o->palette), ink(o->palette), 0.15), 1));
                p->setBrush(o->palette.color(QPalette::Base));
                p->drawRoundedRect(r, 4, 4);
                if (o->state & State_Sunken) {
                    p->setPen(Qt::NoPen);
                    p->setBrush(pressTint(o->palette));
                    p->drawRoundedRect(r, 4, 4);
                }
            }
            if ((o->state & State_HasFocus) && (o->state & State_KeyboardFocusChange)) {
                p->setOpacity(1);
                p->setPen(QPen(ring(o->palette), 2));
                p->setBrush(Qt::NoBrush);
                p->drawRoundedRect(r.adjusted(-2, -2, 2, 2), 6, 6);
            }
            p->restore();
            return;
        }
        case PE_IndicatorRadioButton: {
            const int d = qMin(o->rect.width(), o->rect.height());
            const QRectF r = crisp(QRect(o->rect.left(), o->rect.top() + (o->rect.height() - d) / 2, d, d));
            const bool enabled = o->state & State_Enabled, on = o->state & State_On;
            p->save();
            p->setRenderHint(QPainter::Antialiasing);
            if (!enabled)
                p->setOpacity(0.5);
            if (on) {
                p->setPen(Qt::NoPen);
                p->setBrush(o->state & State_Sunken ? accent(o->palette).darker(115) : accent(o->palette));
                p->drawEllipse(r);
                p->setBrush(o->palette.color(QPalette::HighlightedText));
                const qreal dot = r.width() * 0.36;
                p->drawEllipse(QRectF(r.center().x() - dot / 2, r.center().y() - dot / 2, dot, dot));
            } else {
                p->setPen(QPen(o->state & State_MouseOver && enabled ? mix(line(o->palette), accent(o->palette), 0.6) : mix(line(o->palette), ink(o->palette), 0.15), 1));
                p->setBrush(o->palette.color(QPalette::Base));
                p->drawEllipse(r);
            }
            if ((o->state & State_HasFocus) && (o->state & State_KeyboardFocusChange)) {
                p->setOpacity(1);
                p->setPen(QPen(ring(o->palette), 2));
                p->setBrush(Qt::NoBrush);
                p->drawEllipse(r.adjusted(-2, -2, 2, 2));
            }
            p->restore();
            return;
        }
        case PE_IndicatorArrowUp:
        case PE_IndicatorArrowDown:
        case PE_IndicatorArrowLeft:
        case PE_IndicatorArrowRight:
        case PE_IndicatorSpinUp:
        case PE_IndicatorSpinDown:
        case PE_IndicatorHeaderArrow: {
            Qt::ArrowType dir = Qt::DownArrow;
            if (pe == PE_IndicatorArrowUp || pe == PE_IndicatorSpinUp)
                dir = Qt::UpArrow;
            else if (pe == PE_IndicatorArrowLeft)
                dir = Qt::LeftArrow;
            else if (pe == PE_IndicatorArrowRight)
                dir = Qt::RightArrow;
            else if (pe == PE_IndicatorHeaderArrow)
                if (auto h = qstyleoption_cast<const QStyleOptionHeader *>(o))
                    dir = h->sortIndicator == QStyleOptionHeader::SortUp ? Qt::UpArrow : Qt::DownArrow;
            QColor c = o->palette.color(o->state & State_Enabled ? QPalette::Active : QPalette::Disabled, QPalette::ButtonText);
            if (o->state & State_On && w && qobject_cast<const QMenu *>(w))
                c = o->palette.color(QPalette::HighlightedText);
            chevron(p, o->rect, dir, c, pe == PE_IndicatorHeaderArrow ? 7 : 0);
            return;
        }
        case PE_PanelMenu: {
            const QColor bg = o->palette.color(QPalette::Window);
            if (!translucent(w)) {
                p->fillRect(o->rect, bg);
                p->setPen(line(o->palette));
                p->setBrush(Qt::NoBrush);
                p->drawRect(o->rect.adjusted(0, 0, -1, -1));
                return;
            }
            p->save();
            p->setRenderHint(QPainter::Antialiasing);
            p->setCompositionMode(QPainter::CompositionMode_Source);
            p->fillRect(o->rect, Qt::transparent);
            p->setCompositionMode(QPainter::CompositionMode_SourceOver);
            p->setPen(QPen(line(o->palette), 1));
            p->setBrush(bg);
            p->drawRoundedRect(crisp(o->rect), CARD, CARD);
            p->restore();
            return;
        }
        case PE_FrameMenu:
            if (translucent(w))
                return;                                      // (drawn with the panel)
            break;
        case PE_PanelTipLabel: {
            p->save();
            p->setRenderHint(QPainter::Antialiasing);
            if (translucent(w)) {
                p->setCompositionMode(QPainter::CompositionMode_Source);
                p->fillRect(o->rect, Qt::transparent);
                p->setCompositionMode(QPainter::CompositionMode_SourceOver);
            }
            p->setPen(QPen(line(o->palette), 1));
            p->setBrush(o->palette.color(QPalette::ToolTipBase));
            if (translucent(w))
                p->drawRoundedRect(crisp(o->rect), CONTROL, CONTROL);
            else
                p->drawRect(crisp(o->rect));
            p->restore();
            return;
        }
        case PE_FrameTabWidget:
        case PE_FrameGroupBox: {
            p->save();
            p->setRenderHint(QPainter::Antialiasing);
            p->setPen(QPen(alpha(line(o->palette), 210), 1));
            p->setBrush(mix(o->palette.color(QPalette::Window), ink(o->palette), isDark(o->palette) ? 0.025 : 0.018));
            p->drawRoundedRect(crisp(o->rect), CARD, CARD);
            p->restore();
            return;
        }
        case PE_Frame:
        case PE_FrameWindow:
        case PE_FrameDockWidget: {
            if (auto f = qstyleoption_cast<const QStyleOptionFrame *>(o))
                if (f->lineWidth <= 0 && pe == PE_Frame)
                    return;
            p->save();
            p->setPen(alpha(line(o->palette), 220));
            p->setBrush(Qt::NoBrush);
            p->drawRect(o->rect.adjusted(0, 0, -1, -1));
            p->restore();
            return;
        }
        case PE_PanelItemViewItem: {
            auto v = qstyleoption_cast<const QStyleOptionViewItem *>(o);
            const bool selected = o->state & State_Selected, hover = (o->state & State_MouseOver) && (o->state & State_Enabled);
            if (v && v->backgroundBrush.style() != Qt::NoBrush)
                p->fillRect(o->rect, v->backgroundBrush);
            if (!selected && !hover)
                return;
            bool left = true, right = true;
            if (v) {
                switch (v->viewItemPosition) {
                case QStyleOptionViewItem::Beginning: right = false; break;
                case QStyleOptionViewItem::Middle: left = right = false; break;
                case QStyleOptionViewItem::End: left = false; break;
                default: break;
                }
            }
            QRectF r = QRectF(o->rect).adjusted(left ? 1 : 0, 1, right ? -1 : 0, -1);
            const QPalette::ColorGroup g = !(o->state & State_Enabled) ? QPalette::Disabled
                                           : (o->state & State_Active) ? QPalette::Active : QPalette::Inactive;
            p->save();
            p->setRenderHint(QPainter::Antialiasing);
            p->setPen(Qt::NoPen);
            p->setBrush(selected ? o->palette.color(g, QPalette::Highlight) : hoverTint(o->palette));
            p->drawPath(roundedSome(r, ITEM, left, right));
            p->restore();
            return;
        }
        case PE_IndicatorDockWidgetResizeHandle:
            return;
        default:
            break;
        }
        QProxyStyle::drawPrimitive(pe, o, p, w);
    }

    // ---------------------------------------------------------------------------------------------- whole controls
    void drawControl(ControlElement ce, const QStyleOption *o, QPainter *p, const QWidget *w) const override
    {
        switch (ce) {
        case CE_PushButtonLabel:
            if (auto b = qstyleoption_cast<const QStyleOptionButton *>(o))
                if ((b->features & QStyleOptionButton::DefaultButton) && (b->state & State_Enabled)) {
                    QStyleOptionButton on(*b);
                    on.palette.setColor(QPalette::ButtonText, b->palette.color(QPalette::HighlightedText));
                    QProxyStyle::drawControl(ce, &on, p, w);
                    return;
                }
            break;
        case CE_MenuItem:
            if (auto m = qstyleoption_cast<const QStyleOptionMenuItem *>(o)) {
                menuItem(m, p, w);
                return;
            }
            break;
        case CE_MenuEmptyArea:
        case CE_MenuHMargin:
        case CE_MenuVMargin:
        case CE_ToolBar:
        case CE_Splitter:
        case CE_SizeGrip:
            return;
        case CE_MenuBarEmptyArea:
            p->fillRect(o->rect, o->palette.window());
            return;
        case CE_MenuBarItem:
            if (auto m = qstyleoption_cast<const QStyleOptionMenuItem *>(o)) {
                p->fillRect(o->rect, o->palette.window());
                if ((o->state & State_Selected) || (o->state & State_Sunken)) {
                    p->save();
                    p->setRenderHint(QPainter::Antialiasing);
                    p->setPen(Qt::NoPen);
                    p->setBrush(o->state & State_Sunken ? pressTint(o->palette) : hoverTint(o->palette));
                    p->drawRoundedRect(QRectF(o->rect).adjusted(1, 2, -1, -2), ITEM, ITEM);
                    p->restore();
                }
                int flags = Qt::AlignCenter | Qt::TextShowMnemonic | Qt::TextDontClip | Qt::TextSingleLine;
                if (!proxy()->styleHint(SH_UnderlineShortcut, m, w))
                    flags |= Qt::TextHideMnemonic;
                proxy()->drawItemText(p, m->rect, flags, m->palette, m->state & State_Enabled, m->text, QPalette::WindowText);
                return;
            }
            break;
        case CE_ProgressBarGroove: {
            p->save();
            p->setRenderHint(QPainter::Antialiasing);
            const QRectF r = QRectF(o->rect).adjusted(0.5, 0.5, -0.5, -0.5);
            const qreal rad = qMin<qreal>(qMin(r.width(), r.height()) / 2, CONTROL);
            p->setPen(Qt::NoPen);
            p->setBrush(alpha(ink(o->palette), isDark(o->palette) ? 30 : 26));
            p->drawRoundedRect(r, rad, rad);
            p->restore();
            return;
        }
        case CE_ProgressBarContents:
            if (auto b = qstyleoption_cast<const QStyleOptionProgressBar *>(o)) {
                if (b->minimum == 0 && b->maximum == 0)
                    break;                                   // (busy: Fusion's moving bar)
                const bool horiz = b->state & State_Horizontal;
                const qreal span = qMax<qreal>(1, qreal(b->maximum) - b->minimum);
                const qreal part = qBound<qreal>(0, (qreal(b->progress) - b->minimum) / span, 1);
                QRectF r = QRectF(o->rect).adjusted(0.5, 0.5, -0.5, -0.5);
                const bool flip = b->invertedAppearance != (horiz && b->direction == Qt::RightToLeft);
                if (horiz) {
                    const qreal wdt = r.width() * part;
                    r = flip ? QRectF(r.right() - wdt, r.top(), wdt, r.height()) : QRectF(r.left(), r.top(), wdt, r.height());
                } else {
                    const qreal hgt = r.height() * part;
                    r = flip ? QRectF(r.left(), r.top(), r.width(), hgt) : QRectF(r.left(), r.bottom() - hgt, r.width(), hgt);
                }
                if (r.width() < 1 || r.height() < 1)
                    return;
                const qreal rad = qMin<qreal>(qMin(QRectF(o->rect).width(), QRectF(o->rect).height()) / 2, CONTROL);
                p->save();
                p->setRenderHint(QPainter::Antialiasing);
                p->setPen(Qt::NoPen);
                p->setBrush(accent(o->palette, o->state & State_Enabled ? QPalette::Active : QPalette::Disabled));
                p->drawRoundedRect(r, qMin(rad, qMin(r.width(), r.height()) / 2), qMin(rad, qMin(r.width(), r.height()) / 2));
                p->restore();
                return;
            }
            break;
        case CE_TabBarTabShape:
            if (auto t = qstyleoption_cast<const QStyleOptionTab *>(o)) {
                const bool vertical = t->shape == QTabBar::RoundedWest || t->shape == QTabBar::RoundedEast
                                      || t->shape == QTabBar::TriangularWest || t->shape == QTabBar::TriangularEast;
                QRect r = vertical ? t->rect.adjusted(3, 2, -3, -2) : t->rect.adjusted(2, 3, -2, -3);
                Look l = lookOf(o);
                if (t->state & State_Selected) {
                    l.flat = false;
                    l.pressed = l.hover = false;
                    p->save();
                    p->setRenderHint(QPainter::Antialiasing);
                    p->setPen(QPen(line(o->palette), 1));
                    p->setBrush(o->palette.color(QPalette::Button));
                    p->drawRoundedRect(crisp(r), CONTROL, CONTROL);
                    p->restore();
                } else if (l.hover && l.enabled) {
                    p->save();
                    p->setRenderHint(QPainter::Antialiasing);
                    p->setPen(Qt::NoPen);
                    p->setBrush(hoverTint(o->palette));
                    p->drawRoundedRect(crisp(r), CONTROL, CONTROL);
                    p->restore();
                }
                return;
            }
            break;
        case CE_HeaderSection: {
            p->fillRect(o->rect, o->palette.base());
            if ((o->state & State_MouseOver) && (o->state & State_Enabled))
                p->fillRect(o->rect, hoverTint(o->palette));
            const QColor sep = alpha(line(o->palette), 200);
            p->fillRect(QRect(o->rect.left(), o->rect.bottom(), o->rect.width(), 1), sep);
            auto h = qstyleoption_cast<const QStyleOptionHeader *>(o);
            if (!h || (h->position != QStyleOptionHeader::End && h->position != QStyleOptionHeader::OnlyOneSection) || h->orientation == Qt::Vertical)
                p->fillRect(QRect(o->rect.right(), o->rect.top() + 5, 1, qMax(0, o->rect.height() - 10)), sep);
            return;
        }
        case CE_HeaderEmptyArea:
            p->fillRect(o->rect, o->palette.base());
            p->fillRect(QRect(o->rect.left(), o->rect.bottom(), o->rect.width(), 1), alpha(line(o->palette), 200));
            return;
        case CE_RubberBand: {
            p->save();
            p->setRenderHint(QPainter::Antialiasing);
            p->setPen(QPen(alpha(accent(o->palette), 200), 1));
            p->setBrush(alpha(accent(o->palette), 50));
            p->drawRoundedRect(crisp(o->rect), 4, 4);
            p->restore();
            return;
        }
        default:
            break;
        }
        QProxyStyle::drawControl(ce, o, p, w);
    }

    void menuItem(const QStyleOptionMenuItem *m, QPainter *p, const QWidget *w) const
    {
        const QRect r = m->rect;
        const QPalette &pal = m->palette;
        if (m->menuItemType == QStyleOptionMenuItem::Separator) {
            if (!m->text.isEmpty()) {                    // a section's heading
                QFont f = m->font;
                f.setPointSizeF(f.pointSizeF() * 0.85);
                f.setWeight(QFont::DemiBold);
                p->save();
                p->setFont(f);
                p->setPen(pal.color(QPalette::Disabled, QPalette::WindowText));
                p->drawText(r.adjusted(10, 0, -10, 0), Qt::AlignLeft | Qt::AlignVCenter | Qt::TextSingleLine, m->text);
                p->restore();
            } else {
                p->fillRect(QRect(r.left() + 8, r.center().y(), r.width() - 16, 1), alpha(line(pal), 220));
            }
            return;
        }
        if (m->menuItemType == QStyleOptionMenuItem::EmptyArea || m->menuItemType == QStyleOptionMenuItem::Margin)
            return;
        const bool enabled = m->state & State_Enabled, selected = (m->state & State_Selected) && enabled;
        const QPalette::ColorGroup g = enabled ? QPalette::Active : QPalette::Disabled;
        if (selected) {
            p->save();
            p->setRenderHint(QPainter::Antialiasing);
            p->setPen(Qt::NoPen);
            p->setBrush(pal.color(QPalette::Active, QPalette::Highlight));
            p->drawRoundedRect(QRectF(r), ITEM, ITEM);
            p->restore();
        }
        const QColor text = selected ? pal.color(QPalette::Active, QPalette::HighlightedText) : pal.color(g, QPalette::WindowText);
        const QColor soft = selected ? alpha(text, 200) : pal.color(g, enabled ? QPalette::PlaceholderText : QPalette::WindowText);
        int x = r.left() + 8;
        const int col = (m->menuHasCheckableItems || m->maxIconWidth > 0) ? 20 : 0;
        const QRect mark(x, r.top(), col, r.height());
        if (col) {
            if (m->checkType != QStyleOptionMenuItem::NotCheckable && m->checked) {
                p->save();
                p->setRenderHint(QPainter::Antialiasing);
                if (m->checkType == QStyleOptionMenuItem::Exclusive) {
                    p->setPen(Qt::NoPen);
                    p->setBrush(text);
                    p->drawEllipse(QPointF(mark.center()) + QPointF(0.5, 0.5), 3.2, 3.2);
                } else {
                    tick(p, QRectF(mark.center().x() - 7, mark.center().y() - 7, 15, 15), text);
                }
                p->restore();
            } else if (!m->icon.isNull()) {
                const int s = 16;
                const QIcon::Mode mode = !enabled ? QIcon::Disabled : selected ? QIcon::Selected : QIcon::Normal;
                const QPixmap px = m->icon.pixmap(QSize(s, s), p->device() ? p->device()->devicePixelRatioF() : 1.0, mode);
                p->drawPixmap(QRect(mark.center().x() - s / 2 + 1, mark.center().y() - s / 2 + 1, s, s), px);
            }
            x += col + 4;
        }
        QString label = m->text, keys;
        const int tab = label.indexOf(QLatin1Char('\t'));
        if (tab >= 0) {
            keys = label.mid(tab + 1);
            label.truncate(tab);
        }
        int flags = Qt::AlignVCenter | Qt::TextShowMnemonic | Qt::TextDontClip | Qt::TextSingleLine;
        if (!proxy()->styleHint(SH_UnderlineShortcut, m, w))
            flags |= Qt::TextHideMnemonic;
        const int right = r.right() - 10;
        p->save();
        p->setFont(m->font);
        p->setPen(text);
        p->drawText(QRect(x, r.top(), right - x, r.height()), flags | Qt::AlignLeft, label);
        if (!keys.isEmpty()) {
            p->setPen(soft);
            p->drawText(QRect(x, r.top(), right - x, r.height()), (flags & ~Qt::TextShowMnemonic) | Qt::AlignRight, keys);
        }
        p->restore();
        if (m->menuItemType == QStyleOptionMenuItem::SubMenu)
            chevron(p, QRectF(right - 8, r.top(), 8, r.height()), m->direction == Qt::RightToLeft ? Qt::LeftArrow : Qt::RightArrow, text, 7);
    }

    void drawComplexControl(ComplexControl cc, const QStyleOptionComplex *o, QPainter *p, const QWidget *w) const override
    {
        switch (cc) {
        case CC_ScrollBar:
            if (auto s = qstyleoption_cast<const QStyleOptionSlider *>(o)) {
                if (s->minimum == s->maximum)
                    return;
                const bool horiz = s->orientation == Qt::Horizontal;
                const bool over = (o->state & State_MouseOver) && (o->state & State_Enabled);
                const bool onHandle = s->activeSubControls & SC_ScrollBarSlider;
                const bool dragging = onHandle && (o->state & State_Sunken);
                if (over) {
                    p->fillRect(o->rect, alpha(ink(o->palette), 10));
                }
                QRect h = proxy()->subControlRect(CC_ScrollBar, s, SC_ScrollBarSlider, w);
                const int thick = over ? (horiz ? o->rect.height() : o->rect.width()) - 4 : (horiz ? o->rect.height() : o->rect.width()) - 6;
                QRectF r = horiz ? QRectF(h.left() + 2, o->rect.center().y() + 1 - thick / 2.0, h.width() - 4, thick)
                                 : QRectF(o->rect.center().x() + 1 - thick / 2.0, h.top() + 2, thick, h.height() - 4);
                p->save();
                p->setRenderHint(QPainter::Antialiasing);
                p->setPen(Qt::NoPen);
                p->setBrush(alpha(ink(o->palette), dragging ? 150 : onHandle && over ? 125 : over ? 100 : 80));
                p->drawRoundedRect(r, thick / 2.0, thick / 2.0);
                p->restore();
                return;
            }
            break;
        case CC_Slider:
            if (auto s = qstyleoption_cast<const QStyleOptionSlider *>(o)) {
                const QRect groove = proxy()->subControlRect(CC_Slider, s, SC_SliderGroove, w);
                const QRect handle = proxy()->subControlRect(CC_Slider, s, SC_SliderHandle, w);
                const bool horiz = s->orientation == Qt::Horizontal, enabled = o->state & State_Enabled;
                p->save();
                p->setRenderHint(QPainter::Antialiasing);
                if (!enabled)
                    p->setOpacity(0.5);
                if (s->subControls & SC_SliderGroove) {
                    const qreal t = 4;
                    QRectF g = horiz ? QRectF(groove.left() + 2, groove.center().y() + 0.5 - t / 2, groove.width() - 4, t)
                                     : QRectF(groove.center().x() + 0.5 - t / 2, groove.top() + 2, t, groove.height() - 4);
                    p->setPen(Qt::NoPen);
                    p->setBrush(alpha(ink(o->palette), isDark(o->palette) ? 40 : 36));
                    p->drawRoundedRect(g, t / 2, t / 2);
                    QRectF fill = g;
                    if (horiz) {
                        const qreal c = handle.center().x() + 0.5;
                        fill = s->upsideDown ? QRectF(c, g.top(), g.right() - c, t) : QRectF(g.left(), g.top(), c - g.left(), t);
                    } else {
                        const qreal c = handle.center().y() + 0.5;
                        fill = s->upsideDown ? QRectF(g.left(), c, t, g.bottom() - c) : QRectF(g.left(), g.top(), t, c - g.top());
                    }
                    p->setBrush(accent(o->palette, enabled ? QPalette::Active : QPalette::Disabled));
                    p->drawRoundedRect(fill, t / 2, t / 2);
                }
                p->restore();
                if (s->subControls & SC_SliderTickmarks) {
                    QStyleOptionSlider ticks(*s);
                    ticks.subControls = SC_SliderTickmarks;
                    QProxyStyle::drawComplexControl(cc, &ticks, p, w);
                }
                if (s->subControls & SC_SliderHandle) {
                    const qreal d = qMin(handle.width(), handle.height()) - 1;
                    const QRectF knob(handle.center().x() + 0.5 - d / 2, handle.center().y() + 0.5 - d / 2, d, d);
                    const bool hover = (s->activeSubControls & SC_SliderHandle) && (o->state & State_MouseOver);
                    const bool press = (s->activeSubControls & SC_SliderHandle) && (o->state & State_Sunken);
                    p->save();
                    p->setRenderHint(QPainter::Antialiasing);
                    if (!enabled)
                        p->setOpacity(0.6);
                    p->setPen(Qt::NoPen);
                    p->setBrush(QColor(0, 0, 0, isDark(o->palette) ? 70 : 34));
                    p->drawEllipse(knob.translated(0, 1));
                    QColor face = isDark(o->palette) ? QColor(0xE6, 0xE9, 0xEE) : QColor(Qt::white);
                    if (press)
                        face = face.darker(112);
                    else if (hover)
                        face = isDark(o->palette) ? QColor(Qt::white) : face.darker(103);
                    p->setPen(QPen(alpha(line(o->palette), isDark(o->palette) ? 0 : 255), 1));
                    p->setBrush(face);
                    p->drawEllipse(knob.adjusted(0.5, 0.5, -0.5, -0.5));
                    if ((o->state & State_HasFocus) && (o->state & State_KeyboardFocusChange)) {
                        p->setPen(QPen(ring(o->palette), 2));
                        p->setBrush(Qt::NoBrush);
                        p->drawEllipse(knob.adjusted(-2, -2, 2, 2));
                    }
                    p->restore();
                }
                return;
            }
            break;
        case CC_ComboBox:
            if (auto c = qstyleoption_cast<const QStyleOptionComboBox *>(o)) {
                Look l = lookOf(o);
                l.pressed = (o->state & State_Sunken) || (c->activeSubControls & SC_ComboBoxArrow && o->state & State_Sunken);
                if (c->subControls & SC_ComboBoxFrame) {
                    if (c->editable)
                        field(p, o->rect, o->palette, l.enabled, o->state & State_HasFocus, l.hover);
                    else {
                        l.flat = !c->frame;
                        button(p, o->rect, o->palette, l);
                    }
                }
                if (c->subControls & SC_ComboBoxArrow) {
                    const QRect a = proxy()->subControlRect(CC_ComboBox, c, SC_ComboBoxArrow, w);
                    const QColor ink2 = o->palette.color(l.enabled ? QPalette::Active : QPalette::Disabled, QPalette::ButtonText);
                    if (c->editable) {
                        chevron(p, a, Qt::DownArrow, ink2, 7);
                    } else {                                   // (up and down: it opens over itself, as a menu)
                        chevron(p, QRectF(a.left(), a.center().y() - 5.5, a.width(), 6), Qt::UpArrow, ink2, 6.5);
                        chevron(p, QRectF(a.left(), a.center().y() + 0.5, a.width(), 6), Qt::DownArrow, ink2, 6.5);
                    }
                }
                return;
            }
            break;
        case CC_SpinBox:
            if (auto s = qstyleoption_cast<const QStyleOptionSpinBox *>(o)) {
                const bool enabled = o->state & State_Enabled;
                if (s->frame && (s->subControls & SC_SpinBoxFrame))
                    field(p, o->rect, o->palette, enabled, o->state & State_HasFocus, o->state & State_MouseOver);
                else
                    p->fillRect(o->rect, o->palette.base());
                if (s->buttonSymbols == QAbstractSpinBox::NoButtons)
                    return;
                for (auto part : {SC_SpinBoxUp, SC_SpinBoxDown}) {
                    if (!(s->subControls & part))
                        continue;
                    const QRect b = proxy()->subControlRect(CC_SpinBox, s, part, w);
                    const bool can = enabled && (s->stepEnabled & (part == SC_SpinBoxUp ? QAbstractSpinBox::StepUpEnabled : QAbstractSpinBox::StepDownEnabled));
                    if (can && (s->activeSubControls & part) && (o->state & (State_MouseOver | State_Sunken))) {
                        p->save();
                        p->setRenderHint(QPainter::Antialiasing);
                        p->setPen(Qt::NoPen);
                        p->setBrush((o->state & State_Sunken) ? pressTint(o->palette) : hoverTint(o->palette));
                        p->drawRoundedRect(QRectF(b).adjusted(1, part == SC_SpinBoxUp ? 2 : 0, -2, part == SC_SpinBoxUp ? 0 : -2), 4, 4);
                        p->restore();
                    }
                    const QColor c = o->palette.color(can ? QPalette::Active : QPalette::Disabled, QPalette::ButtonText);
                    if (s->buttonSymbols == QAbstractSpinBox::PlusMinus) {
                        p->save();
                        p->setRenderHint(QPainter::Antialiasing);
                        p->setPen(QPen(c, 1.5, Qt::SolidLine, Qt::RoundCap));
                        const QPointF m = QRectF(b).center();
                        p->drawLine(QPointF(m.x() - 3.5, m.y()), QPointF(m.x() + 3.5, m.y()));
                        if (part == SC_SpinBoxUp)
                            p->drawLine(QPointF(m.x(), m.y() - 3.5), QPointF(m.x(), m.y() + 3.5));
                        p->restore();
                    } else {
                        chevron(p, b, part == SC_SpinBoxUp ? Qt::UpArrow : Qt::DownArrow, c, 7);
                    }
                }
                return;
            }
            break;
        default:
            break;
        }
        QProxyStyle::drawComplexControl(cc, o, p, w);
    }

    // ---------------------------------------------------------------------------------------------- sizes
    QRect subControlRect(ComplexControl cc, const QStyleOptionComplex *o, SubControl sc, const QWidget *w) const override
    {
        if (cc == CC_ScrollBar)
            if (auto s = qstyleoption_cast<const QStyleOptionSlider *>(o)) {
                // no arrows: the whole length is for the handle
                const QRect r = s->rect;
                const bool horiz = s->orientation == Qt::Horizontal;
                const int len = horiz ? r.width() : r.height();
                int handle = len;
                if (s->maximum != s->minimum) {
                    const qint64 range = qint64(s->maximum) - s->minimum;
                    handle = int((qint64(s->pageStep) * len) / qMax<qint64>(1, range + s->pageStep));
                    handle = qBound(qMin(len, proxy()->pixelMetric(PM_ScrollBarSliderMin, s, w)), handle, len);
                }
                const int start = sliderPositionFromValue(s->minimum, s->maximum, s->sliderPosition, len - handle, s->upsideDown);
                QRect out;
                switch (sc) {
                case SC_ScrollBarSubLine:
                case SC_ScrollBarAddLine:
                    return QRect();
                case SC_ScrollBarGroove:
                    out = QRect(0, 0, r.width(), r.height());
                    break;
                case SC_ScrollBarSlider:
                    out = horiz ? QRect(start, 0, handle, r.height()) : QRect(0, start, r.width(), handle);
                    break;
                case SC_ScrollBarSubPage:
                    out = horiz ? QRect(0, 0, start, r.height()) : QRect(0, 0, r.width(), start);
                    break;
                case SC_ScrollBarAddPage:
                    out = horiz ? QRect(start + handle, 0, len - start - handle, r.height()) : QRect(0, start + handle, r.width(), len - start - handle);
                    break;
                default:
                    return QProxyStyle::subControlRect(cc, o, sc, w);
                }
                return visualRect(s->direction, r, out.translated(r.topLeft()));
            }
        return QProxyStyle::subControlRect(cc, o, sc, w);
    }

    QRect subElementRect(SubElement se, const QStyleOption *o, const QWidget *w) const override
    {
        QRect r = QProxyStyle::subElementRect(se, o, w);
        if (se == SE_LineEditContents)
            if (auto f = qstyleoption_cast<const QStyleOptionFrame *>(o))
                if (f->lineWidth > 0)
                    r.adjust(4, 0, -4, 0);
        return r;
    }

    QSize sizeFromContents(ContentsType ct, const QStyleOption *o, const QSize &size, const QWidget *w) const override
    {
        if (ct == CT_MenuItem)
            if (auto m = qstyleoption_cast<const QStyleOptionMenuItem *>(o)) {
                if (m->menuItemType == QStyleOptionMenuItem::Separator)
                    return QSize(size.width(), m->text.isEmpty() ? 9 : m->fontMetrics.height() + 8);
                const int col = (m->menuHasCheckableItems || m->maxIconWidth > 0) ? 24 : 0;
                const int keys = m->reservedShortcutWidth > 0 ? m->reservedShortcutWidth + 28 : 0;
                const int h = qMax(qMax(size.height(), m->fontMetrics.height()) + 8, 26);
                return QSize(qMax(8 + col + size.width() + keys + 22 + 10, 120), h);
            }
        QSize s = QProxyStyle::sizeFromContents(ct, o, size, w);
        switch (ct) {
        case CT_PushButton:
            if (auto b = qstyleoption_cast<const QStyleOptionButton *>(o))
                if (!b->text.isEmpty())
                    s = QSize(qMax(s.width() + 8, 80), qMax(s.height(), 30));
            break;
        case CT_LineEdit:
            s = QSize(s.width() + 8, qMax(s.height(), 30));
            break;
        case CT_ComboBox:
            s = QSize(s.width() + 6, qMax(s.height(), 30));
            break;
        case CT_SpinBox:
            s.setHeight(qMax(s.height(), 30));
            break;
        case CT_TabBarTab:
            s += QSize(8, 4);
            break;
        case CT_HeaderSection:
            s.setHeight(qMax(s.height(), 28));
            break;
        case CT_ItemViewItem:
            s.setHeight(s.height() + 4);
            break;
        case CT_MenuBarItem:
            s += QSize(8, 4);
            break;
        default:
            break;
        }
        return s;
    }

    int pixelMetric(PixelMetric pm, const QStyleOption *o = nullptr, const QWidget *w = nullptr) const override
    {
        switch (pm) {
        case PM_ScrollBarExtent: return 12;
        case PM_ScrollBarSliderMin: return 36;
        case PM_SliderThickness: return 24;
        case PM_SliderLength:
        case PM_SliderControlThickness: return 20;
        case PM_MenuHMargin:
        case PM_MenuVMargin: return 5;
        case PM_MenuPanelWidth: return 1;
        case PM_SubMenuOverlap: return -6;
        case PM_IndicatorWidth:
        case PM_IndicatorHeight:
        case PM_ExclusiveIndicatorWidth:
        case PM_ExclusiveIndicatorHeight: return 16;
        case PM_CheckBoxLabelSpacing:
        case PM_RadioButtonLabelSpacing: return 8;
        case PM_TabBarTabHSpace: return 22;
        case PM_TabBarTabVSpace: return 12;
        case PM_TabBarBaseOverlap: return 0;
        case PM_TabBarTabShiftVertical:
        case PM_TabBarTabShiftHorizontal: return 0;
        case PM_TabBar_ScrollButtonOverlap: return 0;
        case PM_MenuBarItemSpacing: return 2;
        case PM_MenuBarHMargin: return 4;
        case PM_MenuBarVMargin: return 2;
        case PM_MenuBarPanelWidth: return 0;
        case PM_HeaderMargin: return 6;
        case PM_ToolTipLabelFrameWidth: return 6;
        case PM_ToolBarFrameWidth: return 0;
        case PM_ToolBarItemMargin: return 2;
        case PM_ToolBarItemSpacing: return 4;
        case PM_ToolBarSeparatorExtent: return 9;
        case PM_DockWidgetTitleBarButtonMargin: return 4;
        case PM_SplitterWidth: return 5;
        default: break;
        }
        return QProxyStyle::pixelMetric(pm, o, w);
    }

    int styleHint(StyleHint sh, const QStyleOption *o = nullptr, const QWidget *w = nullptr, QStyleHintReturn *r = nullptr) const override
    {
        switch (sh) {
        case SH_ComboBox_Popup: return 1;                   // opens over itself, as a menu (with the menu's look)
        case SH_ComboBox_UseNativePopup: return 0;
        case SH_ToolTip_Mask:
        case SH_Menu_Mask: return 0;                         // (rounded by being see-through at the corners)
        case SH_Slider_AbsoluteSetButtons: return Qt::LeftButton;
        case SH_DialogButtonBox_ButtonsHaveIcons: return 0;
        case SH_EtchDisabledText:
        case SH_DitherDisabledText: return 0;
        case SH_ItemView_ShowDecorationSelected: return 1;
        case SH_Menu_SupportsSections: return 1;
        case SH_ScrollBar_ContextMenu: return 1;
        case SH_ScrollView_FrameOnlyAroundContents: return 0;
        case SH_Table_GridLineColor:
            if (o)
                return int(alpha(line(o->palette), 140).rgba());
            break;
        case SH_Menu_FlashTriggeredItem: return 0;
        case SH_ToolBox_SelectedPageTitleBold: return 1;
        default:
            break;
        }
        return QProxyStyle::styleHint(sh, o, w, r);
    }

    // ---------------------------------------------------------------------------------------------- widgets
    void polish(QWidget *w) override
    {
        QProxyStyle::polish(w);
        if (qobject_cast<QMenu *>(w) || w->inherits("QTipLabel")) {
            // see-through at the corners (menus and tool tips are rounded); only before Qt makes its window
            if (!w->testAttribute(Qt::WA_WState_Created))
                w->setAttribute(Qt::WA_TranslucentBackground, true);
        }
        if (qobject_cast<QAbstractButton *>(w) || qobject_cast<QComboBox *>(w) || qobject_cast<QAbstractSpinBox *>(w)
            || qobject_cast<QAbstractSlider *>(w) || qobject_cast<QTabBar *>(w) || qobject_cast<QHeaderView *>(w)
            || qobject_cast<QLineEdit *>(w))
            w->setAttribute(Qt::WA_Hover, true);
        if (auto v = qobject_cast<QAbstractItemView *>(w))
            v->viewport()->setAttribute(Qt::WA_Hover, true);
    }

    using QProxyStyle::polish;
};

class HuginnStylePlugin : public QStylePlugin
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID QStyleFactoryInterface_iid FILE "huginnstyle.json")
public:
    QStyle *create(const QString &key) override
    {
        return key.compare(QLatin1String("huginn"), Qt::CaseInsensitive) == 0 ? new HuginnStyle : nullptr;
    }
};

#include "style.moc"
