from netbox.plugins import PluginConfig
from django.conf import settings


class NetboxBranchGuardConfig(PluginConfig):
    name = "netbox_branch_guard"
    verbose_name = "Netbox Branch Guard"
    description = "Guards against writes to the Main branch and enforces branch usage"
    version = "0.1.0"
    author = "KPTheProf"
    base_url = "netbox-branch-guard"
    URL = https://github.com/KPTheProf/netbox_branch_guard

    def ready(self):
        middleware_path = "netbox_branch_guard.middleware.NetboxBranchGuardMiddleware"

        if middleware_path in settings.MIDDLEWARE:
            return

        # ✅ find AuthenticationMiddleware
        try:
            index = settings.MIDDLEWARE.index(
                "django.contrib.messages.middleware.MessageMiddleware"
            )
        except ValueError:
            # fallback: append at end
            settings.MIDDLEWARE.append(middleware_path)
            return

        # ✅ insert AFTER auth middleware
        settings.MIDDLEWARE.insert(index + 1, middleware_path)

config = NetboxBranchGuardConfig
