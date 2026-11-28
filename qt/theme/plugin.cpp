// QT_QPA_PLATFORMTHEME=huginn
#include "theme.h"

#include <qpa/qplatformthemeplugin.h>

class HuginnThemePlugin : public QPlatformThemePlugin
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID QPlatformThemeFactoryInterface_iid FILE "huginn.json")
public:
    QPlatformTheme *create(const QString &key, const QStringList &) override
    {
        if (key.compare(QLatin1String("huginn"), Qt::CaseInsensitive) != 0 || HuginnTheme::making())
            return nullptr;
        return new HuginnTheme;
    }
};

#include "plugin.moc"
